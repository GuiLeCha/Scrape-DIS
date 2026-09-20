from __future__ import annotations

import math
import random
import re
import threading
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from aws_extractor.config import Settings
from aws_extractor.core.discovery import discover_module_items
from aws_extractor.extractors.html_pdf import find_canvas_html
from aws_extractor.extractors.viewer_pdf import find_pdf_frame, total_pages, wait_pdf_viewer_ready
from aws_extractor.utils import cleanup_profile_lock


def _format_time(seconds: float) -> str:
    """Convierte segundos a formato MM:SS o HH:MM:SS."""
    if seconds is None or math.isnan(seconds) or seconds < 0:
        return "00:00"
    total = int(round(seconds))
    hrs = total // 3600
    mins = (total % 3600) // 60
    secs = total % 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


class ContentPlayer:
    """
    Controlador para reproducción online y recorrido simulado humano
    de contenidos de AWS Academy en Canvas LMS.
    """

    def __init__(
        self,
        settings: Settings,
        log_callback=None,
        progress_callback=None,
    ):
        self.settings = settings
        self.log_fn = log_callback or (lambda msg: print(f"[PLAYER] {msg}"))
        self.progress_fn = progress_callback or (lambda pct: None)
        self.profile_dir = settings.profile_dir

    def log(self, msg: str):
        try:
            self.log_fn(msg)
        except Exception:
            try:
                safe_msg = str(msg).encode("ascii", "replace").decode("ascii")
                self.log_fn(safe_msg)
            except Exception:
                pass

    def progress(self, pct: float):
        self.progress_fn(pct)

    def play_module(
        self,
        module_title: str,
        home_url: str,
        cancel_event: threading.Event | None = None,
    ):
        """
        Recorre todos los contenidos del módulo seleccionado:
        - Si es un video: activa subtítulos en español, da play y espera a que termine.
        - Si es un PDF: espera a que el visor cargue y recorre sus páginas simulando tiempos de lectura.
        - Si es una página HTML: hace scroll gradual simulando lectura humana.
        - Si es un quiz o laboratorio: se omite automáticamente.
        - Utiliza el botón «Next / Siguiente» de Canvas para avanzar entre secciones.
        """
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        cleanup_profile_lock(self.profile_dir)

        with sync_playwright() as p:
            self.log("Abriendo navegador para reproducción online...")
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=False,
                accept_downloads=False,
                viewport={"width": 1440, "height": 1000},
                args=[
                    "--start-maximized",
                    "--disable-blink-features=AutomationControlled",
                    "--autoplay-policy=no-user-gesture-required",
                ],
            )

            work_page = context.pages[0] if context.pages else context.new_page()

            try:
                if cancel_event and cancel_event.is_set():
                    self.log("Operación cancelada antes de iniciar.")
                    return

                discovery = discover_module_items(
                    page=work_page,
                    home_url=home_url,
                    module_title=module_title,
                    log_fn=self.log,
                    username=self.settings.aws_username,
                    password=self.settings.aws_password,
                )

                downloadables = discovery.get("downloadables") or []
                skipped = discovery.get("skipped") or []

                if skipped:
                    self.log(f"--- Ítems omitidos automáticamente ({len(skipped)}) ---")
                    for sk in skipped:
                        title = sk.get("title") or "Sin título"
                        reason = sk.get("reason") or "omisión automática"
                        self.log(f"  [OMITIDO] {title} -> ({reason})")
                    self.log("--------------------------------------------------")

                if not downloadables:
                    self.log("No se encontraron contenidos de estudio para reproducir.")
                    return

                total = len(downloadables)
                self.progress(0)

                for idx, item in enumerate(downloadables, start=1):
                    if cancel_event and cancel_event.is_set():
                        self.log("Recorrido interrumpido por el usuario.")
                        break

                    url = str(item.get("href") or "").strip()
                    title = str(item.get("title") or f"Ítem {idx}").strip()

                    self.log(f"\n==================================================")
                    self.log(f"[{idx}/{total}] Sección: {title}")
                    self.log(f"URL: {url}")
                    self.log(f"==================================================")

                    # Si es la sección 2 o superior, intentamos pasar mediante 'Next / Siguiente'
                    used_next_nav = False
                    if idx > 1:
                        used_next_nav = self._click_next_button(work_page)
                        if used_next_nav:
                            time.sleep(2.0)

                    self._process_single_item(
                        context=context,
                        page=work_page,
                        url=url,
                        title=title,
                        item_index=idx,
                        total_items=total,
                        use_next_nav=used_next_nav,
                        cancel_event=cancel_event,
                    )

                    pct = round(idx / total * 100)
                    self.progress(pct)

                    if cancel_event and cancel_event.is_set():
                        break

                    time.sleep(2.0 + random.uniform(0.5, 1.5))

                self.log("\n[OK] Recorrido del módulo finalizado.")

            finally:
                try:
                    context.close()
                except Exception:
                    pass

    def _click_next_button(self, page) -> bool:
        """
        Busca el botón 'Next' / 'Siguiente' en Canvas y hace clic para pasar
        a la siguiente sección del módulo de forma natural.
        """
        selectors = [
            "a[aria-label*='Next' i]",
            "a[aria-label*='Siguiente' i]",
            "a.module-sequence-footer-button--next",
            "a.btn.module-sequence-footer-button--next",
            "a[rel='next']",
            "a:has-text('Next')",
            "a:has-text('Siguiente')",
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel)
                if btn.count() and btn.first.is_visible(timeout=500):
                    self.log("Presionando botón «Next / Siguiente» para avanzar de sección...")
                    btn.first.click()
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=20_000)
                    except Exception:
                        pass
                    return True
            except Exception:
                continue
        return False

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

    def _find_video_frame(self, context):
        """
        Escanea todas las páginas y frames buscando elementos <video> o reproductores Video.js.
        """
        for pg in context.pages:
            for frame in pg.frames:
                try:
                    if frame.locator("video").count() > 0:
                        return frame
                    has_vjs = frame.evaluate(
                        "() => typeof videojs !== 'undefined' && typeof videojs.getPlayers === 'function' && Object.keys(videojs.getPlayers()).length > 0"
                    )
                    if has_vjs:
                        return frame
                except Exception:
                    pass
        return None

    def _process_single_item(
        self,
        context,
        page,
        url: str,
        title: str,
        item_index: int,
        total_items: int,
        use_next_nav: bool = False,
        cancel_event: threading.Event | None = None,
    ):
        if not use_next_nav:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            except PlaywrightTimeoutError:
                self.log("Carga inicial demorada; continuando con el DOM disponible...")

        if cancel_event and cancel_event.is_set():
            return

        self.log("Esperando que el contenido termine de cargar (video, PDF o lectura)...")

        # Bucle de detección de hasta 35 segundos para permitir que SCORM o el visor PDF inicialicen
        timeout = 35
        deadline = time.time() + timeout
        launch_attempted = False
        last_log = 0.0

        while time.time() < deadline:
            if cancel_event and cancel_event.is_set():
                return

            # 1. ¿Hay un reproductor de video listo en algún frame?
            video_frame = self._find_video_frame(context)
            if video_frame:
                self._play_video(context, video_frame, cancel_event=cancel_event)
                return

            # 2. ¿Hay un visor PDF presente en algún frame?
            pdf_frame = find_pdf_frame(context)
            if pdf_frame:
                self._read_pdf(context, pdf_frame, cancel_event=cancel_event)
                return

            # Si Canvas muestra botón de carga de herramienta externa, presionarlo
            if not launch_attempted:
                launch_attempted = self._try_launch_canvas_tool(context)

            # 3. Si han pasado al menos 15 segundos sin detectar video ni PDF, verificar si es lectura HTML
            elapsed = time.time() - (deadline - timeout)
            if elapsed >= 15.0:
                html_frame = find_canvas_html(context)
                if html_frame:
                    self.log("Contenido identificado como lectura HTML.")
                    self._simulate_html_reading(page, cancel_event=cancel_event)
                    return

            now = time.time()
            if now - last_log >= 6.0:
                rem = max(0, int(deadline - now))
                self.log(f"Cargando componentes interactivos... (quedan hasta {rem} s de espera)")
                last_log = now

            time.sleep(1.0)

        # Si agotó el tiempo de detección, ejecutar lectura HTML sobre la página
        self.log("Tiempo de espera completado. Procesando como lectura de página...")
        self._simulate_html_reading(page, cancel_event=cancel_event)

    def _play_video(
        self,
        context,
        video_frame,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """
        Activa subtítulos en español, da Play y monitorea la reproducción hasta el final.
        """
        speed = max(0.5, float(self.settings.sim_video_speed or 1.0))
        self.log(f"[VIDEO] Reproductor de video detectado en «{video_frame.name or 'frame'}».")

        # Configurar volumen, velocidad y activar subtítulos en español
        setup_script = f"""() => {{
            let p = null;
            if (typeof videojs !== 'undefined' && typeof videojs.getPlayers === 'function') {{
                const players = Object.values(videojs.getPlayers()).filter(Boolean);
                if (players.length > 0) p = players[0];
            }}
            
            const result = {{ spanish_activated: false, tracks: [] }};
            if (p) {{
                try {{
                    p.muted(false);
                    p.playbackRate({speed});
                    const tracks = p.textTracks();
                    for (let i = 0; i < tracks.length; i++) {{
                        const t = tracks[i];
                        result.tracks.push({{ lang: t.language, label: t.label }});
                        if (/es|spa|spanish/i.test(t.language || t.label)) {{
                            t.mode = 'showing';
                            result.spanish_activated = true;
                        }}
                    }}
                    p.play();
                }} catch (e) {{}}
            }} else {{
                const v = document.querySelector('video');
                if (v) {{
                    try {{
                        v.muted = false;
                        v.playbackRate = {speed};
                        for (let i = 0; i < (v.textTracks || []).length; i++) {{
                            const t = v.textTracks[i];
                            result.tracks.push({{ lang: t.language, label: t.label }});
                            if (/es|spa|spanish/i.test(t.language || t.label)) {{
                                t.mode = 'showing';
                                result.spanish_activated = true;
                            }}
                        }}
                        v.play();
                    }} catch (e) {{}}
                }}
            }}
            return result;
        }}"""

        try:
            res = video_frame.evaluate(setup_script)
            if res.get("spanish_activated"):
                self.log("  [OK] Subtítulos en español activados en pantalla.")
            else:
                self.log("  [INFO] Subtítulos en español no disponibles o no requeridos.")
        except Exception as e:
            self.log(f"  Aviso al inicializar reproductor: {e}")

        self.log(f"  Reproducción iniciada (velocidad: {speed}x). Monitoreando duración...")

        poll_script = """() => {
            let p = null;
            if (typeof videojs !== 'undefined' && typeof videojs.getPlayers === 'function') {
                const players = Object.values(videojs.getPlayers()).filter(Boolean);
                if (players.length > 0) p = players[0];
            }
            const v = document.querySelector('video');
            let dur = p ? p.duration() : (v ? v.duration : 0);
            let cur = p ? p.currentTime() : (v ? v.currentTime : 0);
            let pau = p ? p.paused() : (v ? v.paused : false);
            let end = p ? p.ended() : (v ? v.ended : false);
            return {
                duration: (dur && !isNaN(dur)) ? dur : 0,
                current: (cur && !isNaN(cur)) ? cur : 0,
                paused: pau,
                ended: end,
            };
        }"""

        last_log_time = -15.0
        last_current = -1.0

        while True:
            if cancel_event and cancel_event.is_set():
                try:
                    video_frame.evaluate("() => { const v = document.querySelector('video'); if (v) v.pause(); }")
                except Exception:
                    pass
                self.log("  [DETENIDO] Reproducción pausada por el usuario.")
                return True

            try:
                state = video_frame.evaluate(poll_script)
            except Exception:
                state = None

            if not state:
                break

            duration = float(state.get("duration") or 0)
            current = float(state.get("current") or 0)
            ended = bool(state.get("ended", False))
            paused = bool(state.get("paused", False))

            # Si se pausó inesperadamente y no ha finalizado, enviar play nuevamente
            if paused and not ended and duration > 0 and current < duration - 1.0:
                try:
                    video_frame.evaluate("() => { const v = document.querySelector('video'); if (v) v.play(); }")
                except Exception:
                    pass

            # Detectar si terminó
            if ended or (duration > 0 and current >= duration - 0.6):
                self.log(f"  [OK] Video finalizado ({_format_time(duration)} / {_format_time(duration)}).")
                break

            # Reportar en el log cada 10 segundos de avance
            if abs(current - last_log_time) >= 10.0 and current > 0:
                last_log_time = current
                pct = round(current / duration * 100) if duration > 0 else 0
                self.log(f"  [>] En reproducción: {_format_time(current)} / {_format_time(duration)} ({pct}%)")

            time.sleep(1.0)

        return True

    def _read_pdf(
        self,
        context,
        initial_frame,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """
        Espera a que el visor PDF renderice las páginas y simula la lectura hojeando el documento.
        """
        self.log("[PDF] Visor de PDF detectado. Esperando que renderice las páginas...")
        ready_frame, pages = wait_pdf_viewer_ready(
            context,
            initial_frame,
            timeout_seconds=40,
            log_fn=self.log,
        )

        if ready_frame is None or ready_frame.is_detached():
            ready_frame = find_pdf_frame(context)

        if pages <= 0:
            pages = total_pages(ready_frame) if ready_frame else 1

        sec_per_page = max(3, int(self.settings.sim_pdf_page_seconds or 12))
        self.log(f"[PDF] Visor PDF listo con {pages} página(s). Simulando lectura humana...")

        scroll_script = """(targetPage) => {
            const pageEl = document.querySelector(`.pdfViewer .page[data-page-number="${targetPage}"]`);
            if (pageEl) {
                pageEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
                return true;
            }
            const container = document.querySelector('#viewerContainer') || document.querySelector('#viewer') || document.documentElement;
            if (container) {
                container.scrollBy({ top: 500, behavior: 'smooth' });
                return true;
            }
            return false;
        }"""

        for p in range(1, pages + 1):
            if cancel_event and cancel_event.is_set():
                self.log("  [DETENIDO] Lectura de PDF interrumpida por el usuario.")
                return True

            self.log(f"  [HOJEANDO] Página {p} de {pages}...")
            try:
                if ready_frame and not ready_frame.is_detached():
                    ready_frame.evaluate(scroll_script, p)
            except Exception:
                pass

            wait_time = sec_per_page + random.uniform(-1.5, 2.5)
            wait_time = max(2.5, wait_time)

            steps = int(wait_time * 2)
            for _ in range(steps):
                if cancel_event and cancel_event.is_set():
                    return True
                time.sleep(0.5)

        self.log("  [OK] Documento PDF leído por completo.")
        return True

    def _simulate_html_reading(
        self,
        page,
        cancel_event: threading.Event | None = None,
    ):
        """
        Simula la lectura de un artículo o página HTML: desplaza progresivamente hacia abajo.
        """
        self.log("[HTML] Lectura de página HTML detectada. Recorriendo contenido...")

        scroll_step_delay = max(0.3, float(self.settings.sim_scroll_delay or 0.8))
        reading_time = max(4, int(self.settings.sim_html_reading_seconds or 10))

        try:
            total_height = page.evaluate("() => document.body.scrollHeight || document.documentElement.scrollHeight || 1000")
            viewport_height = page.evaluate("() => window.innerHeight || 800")
        except Exception:
            total_height = 2000
            viewport_height = 800

        current_y = 0
        while current_y < (total_height - viewport_height + 150):
            if cancel_event and cancel_event.is_set():
                self.log("  [DETENIDO] Lectura de página interrumpida.")
                return

            step = random.randint(250, 450)
            current_y += step
            try:
                page.evaluate(f"window.scrollBy({{ top: {step}, behavior: 'smooth' }});")
            except Exception:
                pass

            time.sleep(scroll_step_delay + random.uniform(0.1, 0.4))

        steps = int(reading_time * 2)
        for _ in range(steps):
            if cancel_event and cancel_event.is_set():
                return
            time.sleep(0.5)

        self.log("  [OK] Contenido de lectura completado.")
