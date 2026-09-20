from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from aws_extractor.config import Settings
from aws_extractor.core.checkpoint import CheckpointManager
from aws_extractor.core.discovery import discover_module_items, fetch_all_modules
from aws_extractor.extractors.html_pdf import find_canvas_html, save_html_as_pdf
from aws_extractor.extractors.video import (
    remember_media_url,
    save_video,
    scan_media_resources,
    wait_video_tracks,
)
from aws_extractor.extractors.viewer_pdf import find_pdf_frame, save_pdf
from aws_extractor.utils import (
    cleanup_profile_lock,
    looks_like_mp4_response,
    looks_like_pdf,
    looks_like_vtt_response,
    safe_name,
)


class Extractor:
    def __init__(
        self,
        settings: Settings,
        log_callback=None,
        progress_callback=None,
        sub_progress_callback=None,
    ):
        self.settings = settings
        self.profile_dir = settings.profile_dir
        self.log = log_callback or (lambda msg: None)
        self.progress = progress_callback or (lambda val: None)
        self.sub_progress = sub_progress_callback or (lambda val: None)
        self.capture = None
        self.checkpoint_manager = CheckpointManager(self.profile_dir, self.log)

    def open_login(self, home_url: str, login_done_event: threading.Event):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        cleanup_profile_lock(self.profile_dir)

        from aws_extractor.core.login import wait_or_auto_login

        with sync_playwright() as p:
            self.log("Abriendo Chromium con el perfil persistente...")
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=False,
                accept_downloads=True,
                viewport={"width": 1440, "height": 1000},
                args=["--start-maximized"],
            )

            page = context.pages[0] if context.pages else context.new_page()

            wait_or_auto_login(
                context=context,
                page=page,
                home_url=home_url,
                username=self.settings.aws_username,
                password=self.settings.aws_password,
                login_done_event=login_done_event,
                log_fn=self.log,
            )

            try:
                context.close()
            except Exception:
                pass

            self.log("Sesión guardada correctamente.")

    def list_course_modules(self, home_url: str) -> list[str]:
        """
        Abre el navegador en segundo plano y recupera la lista de todos los módulos disponibles.
        """
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        cleanup_profile_lock(self.profile_dir)

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=False,
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                modules = fetch_all_modules(
                    page,
                    home_url,
                    log_fn=self.log,
                    username=self.settings.aws_username,
                    password=self.settings.aws_password,
                )
                return modules
            finally:
                try:
                    context.close()
                except Exception:
                    pass

    def download_batch(
        self,
        items: list[tuple[int, str]] | None,
        module: str,
        output_root: str,
        home_url: str = "",
        discovery_callback=None,
        cancel_event: threading.Event | None = None,
    ) -> tuple[Path, list[Path], list[tuple[str, str]]]:
        module_dir = (
            Path(output_root).expanduser().resolve()
            / safe_name(module, "Sin_modulo")
        )
        module_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        cleanup_profile_lock(self.profile_dir)

        results = []
        errors = []

        checkpoint_state, checkpoint_path, checkpoint_history = (
            self.checkpoint_manager.load_checkpoint(module_dir)
        )

        self.log(
            "Reanudación persistente: "
            + ("ACTIVA" if self.settings.resume_enabled else "DESACTIVADA")
        )

        if self.settings.force_redownload:
            self.log(
                "FORCE_REDOWNLOAD=true: se ignorarán checkpoints "
                "y archivos previos en esta ejecución."
            )

        self.log(f"Checkpoint: {checkpoint_path}")

        with sync_playwright() as p:
            self.log("Abriendo navegador autenticado...")
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=False,
                accept_downloads=True,
                viewport={"width": 1440, "height": 1000},
                args=[
                    "--start-maximized",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            attached = set()

            def on_response(response):
                cap = self.capture
                if cap is None:
                    return

                try:
                    resource_url = response.url
                    headers = response.headers
                except Exception:
                    return

                try:
                    if looks_like_pdf(resource_url, headers):
                        cap["pdf_responses"].append(response)
                except Exception:
                    pass

                if (
                    looks_like_vtt_response(resource_url, headers)
                    and resource_url not in cap["vtt_urls"]
                ):
                    cap["vtt_urls"].append(resource_url)
                    try:
                        cap["referers"][resource_url] = (
                            response.request.headers.get("referer", "")
                        )
                    except Exception:
                        pass
                    self.log("Subtítulo detectado: " + resource_url[:170])

                elif (
                    looks_like_mp4_response(resource_url, headers)
                    and resource_url not in cap["mp4_urls"]
                ):
                    cap["mp4_urls"].append(resource_url)
                    try:
                        cap["referers"][resource_url] = (
                            response.request.headers.get("referer", "")
                        )
                    except Exception:
                        pass
                    self.log("MP4 detectado: " + resource_url[:170])

            def attach(page):
                key = id(page)
                if key in attached:
                    return
                attached.add(key)
                page.on("response", on_response)

            for pg in context.pages:
                attach(pg)

            context.on("page", attach)
            work_page = context.pages[0] if context.pages else context.new_page()
            attach(work_page)

            discovery = None

            if items is None:
                if cancel_event and cancel_event.is_set():
                    context.close()
                    raise RuntimeError("Operación cancelada.")

                discovery = discover_module_items(
                    page=work_page,
                    home_url=home_url,
                    module_title=module,
                    log_fn=self.log,
                    username=self.settings.aws_username,
                    password=self.settings.aws_password,
                )
                items = discovery["items"]

                if discovery_callback is not None:
                    try:
                        discovery_callback(discovery)
                    except Exception:
                        pass

            discovery_by_url = {}
            if discovery is not None:
                discovery_by_url = {
                    str(item.get("href") or "").strip(): item
                    for item in discovery.get("downloadables", [])
                    if str(item.get("href") or "").strip()
                }

            if not items:
                raise RuntimeError("No hay materiales para descargar.")

            total = len(items)
            self.progress(0)

            for position, (row_number, url) in enumerate(items, start=1):
                if cancel_event and cancel_event.is_set():
                    self.log("Proceso detenido por el usuario.")
                    break

                item_meta = discovery_by_url.get(url, {})
                item_title = str(item_meta.get("title") or "").strip()

                self.log(f"Procesando ({position}/{total}): {url}")

                if self.settings.resume_enabled and not self.settings.force_redownload:
                    resumed = self.checkpoint_manager.checkpoint_resume_item(
                        checkpoint_state, module_dir, url
                    )

                    if resumed:
                        results.extend(resumed)
                        self.log(f"SALTADO (checkpoint OK): {item_title or f'fila {row_number}'}")
                        for res in resumed:
                            self.log(f"  reutilizado: {res.name}")

                        self.checkpoint_manager.append_history(
                            checkpoint_history,
                            f"SKIP checkpoint | fila={row_number} | {item_title or url}",
                        )
                        self.progress(round(position / total * 100))
                        continue

                    bootstrapped, _ = self.checkpoint_manager.bootstrap_existing_item(
                        module_dir, row_number, item_title
                    )

                    if bootstrapped:
                        status = self.checkpoint_manager.mark_success(
                            checkpoint_state,
                            checkpoint_path,
                            checkpoint_history,
                            url,
                            row_number,
                            item_title,
                            bootstrapped,
                            source="existing-bootstrap",
                        )
                        if status == "ok":
                            results.extend(bootstrapped)
                            self.log(
                                "SALTADO (archivo previo validado y adoptado al checkpoint): "
                                + (item_title or f"fila {row_number}")
                            )
                            for res in bootstrapped:
                                self.log(f"  reutilizado: {res.name}")
                            self.progress(round(position / total * 100))
                            continue

                self.capture = {
                    "pdf_responses": [],
                    "mp4_urls": [],
                    "vtt_urls": [],
                    "referers": {},
                    "subtitle_tracks": [],
                    "text_tracks": [],
                }

                try:
                    item_results = self._download_one(
                        context=context,
                        page=work_page,
                        url=url,
                        row_number=row_number,
                        module_dir=module_dir,
                        attach_page=attach,
                        cancel_event=cancel_event,
                    )

                    results.extend(item_results)
                    for res in item_results:
                        self.log(f"OK: {res.name}")

                    checkpoint_title = item_title
                    if not checkpoint_title and item_results:
                        stem = Path(item_results[0]).stem
                        checkpoint_title = re.sub(rf"^{row_number}_", "", stem)

                    checkpoint_status = self.checkpoint_manager.mark_success(
                        checkpoint_state,
                        checkpoint_path,
                        checkpoint_history,
                        url,
                        row_number,
                        checkpoint_title,
                        item_results,
                        source="download",
                    )

                    if checkpoint_status == "ok":
                        self.log(f"CHECKPOINT OK: fila {row_number} no necesitará descargarse nuevamente.")
                    else:
                        self.log(f"CHECKPOINT PARCIAL: fila {row_number}. Se reintentará en una ejecución futura.")

                except Exception as exc:
                    if cancel_event and cancel_event.is_set():
                        self.log("Cancelación detectada. Deteniendo lote.")
                        break

                    errors.append((f"Fila {row_number}", str(exc)))
                    self.log(f"ERROR en fila {row_number}: {exc}")
                    self.checkpoint_manager.mark_error(
                        checkpoint_state,
                        checkpoint_path,
                        checkpoint_history,
                        url,
                        row_number,
                        item_title,
                        str(exc),
                    )

                finally:
                    self.capture = None
                    for pg in list(context.pages):
                        if pg is work_page:
                            continue
                        try:
                            pg.close()
                        except Exception:
                            pass
                    self.progress(round(position / total * 100))

            try:
                context.close()
            except Exception:
                pass

        return module_dir, results, errors

    def _download_one(
        self,
        context,
        page,
        url: str,
        row_number: int,
        module_dir: Path,
        attach_page,
        cancel_event: threading.Event | None = None,
    ) -> list[Path]:
        self.log(f"Abriendo material de la fila {row_number}...")

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        except PlaywrightTimeoutError:
            self.log(
                "La navegación superó 90 s. Continúo porque Canvas/SCORM puede seguir cargando."
            )

        if cancel_event and cancel_event.is_set():
            raise RuntimeError("Operación cancelada.")

        material_type = self._detect_type(
            context=context,
            page=page,
            attach_page=attach_page,
        )

        title = self._get_tab_title(page)
        base_name = safe_name(
            f"{row_number}_{title}",
            f"{row_number}_Material",
        )

        self.log(f"Detectado: {material_type.upper()}")
        self.log(f"Título de la pestaña: {title}")
        self.log(f"Nombre de salida: {base_name}")

        if material_type == "html":
            result = save_html_as_pdf(
                context=context,
                module_dir=module_dir,
                base_name=base_name,
                log_fn=self.log,
            )
            return [result]

        if material_type == "video":
            return save_video(
                context=context,
                capture=self.capture,
                module_dir=module_dir,
                base_name=base_name,
                settings=self.settings,
                log_fn=self.log,
                progress_fn=self.sub_progress,
                cancel_event=cancel_event,
            )

        if material_type == "pdf":
            result = save_pdf(
                context=context,
                capture=self.capture,
                module_dir=module_dir,
                base_name=base_name,
                viewer_load_timeout=self.settings.viewer_load_timeout,
                page_render_timeout=self.settings.page_render_timeout,
                log_fn=self.log,
            )
            return [result]

        raise RuntimeError("Formato de material no reconocido.")

    def _get_tab_title(self, page, timeout_seconds: int = 15) -> str:
        deadline = time.time() + timeout_seconds
        best = ""
        previous = None
        stable_since = None

        while time.time() < deadline:
            try:
                title = (page.title() or "").strip()
            except Exception:
                title = ""

            if title:
                best = title
                if title == previous:
                    if stable_since is not None and time.time() - stable_since >= 1.2:
                        break
                else:
                    previous = title
                    stable_since = time.time()

            time.sleep(0.25)

        return best or "Material"

    def _detect_type(self, context, page, attach_page) -> str:
        timeout = self.settings.auto_detect_timeout
        deadline = time.time() + timeout
        last_status = 0.0
        launch_attempted = False

        while time.time() < deadline:
            for pg in context.pages:
                attach_page(pg)

            html_match = find_canvas_html(context)
            if html_match is not None:
                return "html"

            scan_media_resources(context, self.capture, log_fn=self.log)

            if self.capture["mp4_urls"]:
                wait_video_tracks(context, self.capture, seconds=5, log_fn=self.log)
                return "video"

            if self.capture["pdf_responses"] or find_pdf_frame(context) is not None:
                return "pdf"

            if not launch_attempted:
                launch_attempted = self._try_launch_canvas_tool(context)

            now = time.time()
            if now - last_status >= 5:
                remaining = max(0, int(deadline - now))
                self.log(f"Detectando tipo de material... quedan hasta {remaining} s.")
                last_status = now

            time.sleep(0.5)

        raise RuntimeError(f"No pude identificar el material después de {timeout} segundos.")

    def _try_launch_canvas_tool(self, context) -> bool:
        selectors = [
            "a.external_tool_link",
            "button.external_tool_link",
            'a[href*="/external_tools/retrieve"]',
            'a[href*="/external_tools/"]',
        ]

        for pg in context.pages:
            for selector in selectors:
                try:
                    loc = pg.locator(selector).first
                    if loc.count() and loc.is_visible(timeout=500):
                        self.log("Lanzando herramienta externa de Canvas...")
                        loc.click(timeout=5_000)
                        return True
                except Exception:
                    continue

        return False

