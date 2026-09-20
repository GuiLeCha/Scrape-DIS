from __future__ import annotations

import math
import random
import re
import threading
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from aws_extractor.config import Settings
from aws_extractor.core.discovery import discover_module_items, evaluation_reason
from aws_extractor.extractors.viewer_pdf import find_pdf_frame, total_pages
from aws_extractor.utils import cleanup_profile_lock, safe_name


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
    Controlador para reproducción online y recorrido simulado
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
        self.log_fn(msg)

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
        - Si es un PDF: recorre sus páginas simulando tiempos de lectura.
        - Si es una página HTML: hace scroll gradual simulando lectura humana.
        - Si es un quiz o laboratorio: se omite automáticamente.
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

                all_items = discovery.get("items") or []
                downloadables = discovery.get("downloadables") or []
                skipped = discovery.get("skipped") or []

                # Reportar ítems omitidos de entrada (laboratorios, quizzes)
                if skipped:
                    self.log(f"--- Ítems omitidos automáticamente ({len(skipped)}) ---")
                    for sk in skipped:
                        title = sk.get("title") or "Sin título"
                        reason = sk.get("reason") or "omisión automática"
                        self.log(f"  [OMITIDO] {title} → ({reason})")
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
                    self.log(f"[{idx}/{total}] Accediendo a: {title}")
                    self.log(f"URL: {url}")
                    self.log(f"==================================================")

                    self._process_single_item(
                        context=context,
                        page=work_page,
                        url=url,
                        title=title,
                        item_index=idx,
                        total_items=total,
                        cancel_event=cancel_event,
                    )

                    pct = round(idx / total * 100)
                    self.progress(pct)

                    if cancel_event and cancel_event.is_set():
                        break

                    # Pausa natural de 2 a 3 segundos entre contenidos
                    time.sleep(2.0 + random.uniform(0.5, 1.5))

                self.log("\n✓ Recorrido del módulo finalizado.")

            finally:
                try:
                    context.close()
                except Exception:
                    pass

    def _process_single_item(
        self,
        context,
        page,
        url: str,
        title: str,
        item_index: int,
        total_items: int,
        cancel_event: threading.Event | None = None,
    ):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        except PlaywrightTimeoutError:
            self.log("Carga de página demorada; analizando contenido disponible...")

        # Esperar 2.5s a que inicialicen posibles reproductores / iframes
        time.sleep(2.5)

        if cancel_event and cancel_event.is_set():
            return

        # 1. Intentar detectar y reproducir video
        video_handled = self._try_play_video(
            context=context,
            cancel_event=cancel_event,
        )
        if video_handled:
            return

        if cancel_event and cancel_event.is_set():
            return

        # 2. Intentar detectar y hojear PDF
        pdf_handled = self._try_read_pdf(
            context=context,
            cancel_event=cancel_event,
        )
        if pdf_handled:
            return

        if cancel_event and cancel_event.is_set():
            return

        # 3. Contenido de lectura estándar HTML
        self._simulate_html_reading(
            page=page,
            cancel_event=cancel_event,
        )

    def _try_play_video(
        self,
        context,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """
        Busca reproductores de video (Video.js o HTML5) en todas las páginas y frames.
        Si encuentra uno, activa los subtítulos en español, da Play y espera su duración.
        """
        speed = max(0.5, float(self.settings.sim_video_speed or 1.0))

        # Script para buscar video, configurar subtítulos en español y reproducir
        setup_script = """() => {
            // 1. Probar con Video.js
            if (typeof videojs !== 'undefined' && typeof videojs.getPlayers === 'function') {
                const players = Object.values(videojs.getPlayers()).filter(Boolean);
                for (const p of players) {
                    try {
                        p.muted(false);
                        p.playbackRate(""" + str(speed) + """);
                        
                        // Activar subtítulos en español
                        const tracks = p.textTracks();
                        for (let i = 0; i < tracks.length; i++) {
                            const t = tracks[i];
                            const lang = String(t.language || t.label || '').toLowerCase();
                            if (lang.includes('es') || lang.includes('spa') || lang.includes('spanish')) {
                                t.mode = 'showing';
                            }
                        }
                        
                        p.play();
                        return {
                            type: 'videojs',
                            id: p.id_ || '',
                            duration: p.duration() || 0,
                            current: p.currentTime() || 0,
                            paused: p.paused(),
                            ended: p.ended()
                        };
                    } catch (e) {}
                }
            }

            // 2. Probar con etiquetas <video> estándar
            const videos = Array.from(document.querySelectorAll('video'));
            for (const v of videos) {
                try {
                    v.muted = false;
                    v.playbackRate = """ + str(speed) + """;

                    const tracks = v.textTracks || [];
                    for (let i = 0; i < tracks.length; i++) {
                        const t = tracks[i];
                        const lang = String(t.language || t.label || '').toLowerCase();
                        if (lang.includes('es') || lang.includes('spa') || lang.includes('spanish')) {
                            t.mode = 'showing';
                        }
                    }

                    v.play();
                    return {
                        type: 'html5',
                        duration: v.duration || 0,
                        current: v.currentTime || 0,
                        paused: v.paused,
                        ended: v.ended
                    };
                } catch (e) {}
            }

            return null;
        }"""

        found_frame = None
        player_info = None

        # Escanear páginas y frames
        for pg in context.pages:
            for frame in pg.frames:
                try:
                    res = frame.evaluate(setup_script)
                    if res:
                        found_frame = frame
                        player_info = res
                        break
                except Exception:
                    pass
            if found_frame:
                break

        if not found_frame or not player_info:
            return False

        self.log("▶ Reproductor de video detectado. Subtítulos en español activados.")
        self.log(f"  Modo de reproducción iniciado a velocidad {speed}x.")

        # Script de sondeo periódico de estado
        poll_script = """() => {
            if (typeof videojs !== 'undefined' && typeof videojs.getPlayers === 'function') {
                const players = Object.values(videojs.getPlayers()).filter(Boolean);
                if (players.length > 0) {
                    const p = players[0];
                    return {
                        duration: p.duration() || 0,
                        current: p.currentTime() || 0,
                        paused: p.paused(),
                        ended: p.ended()
                    };
                }
            }
            const v = document.querySelector('video');
            if (v) {
                return {
                    duration: v.duration || 0,
                    current: v.currentTime || 0,
                    paused: v.paused,
                    ended: v.ended
                };
            }
            return null;
        }"""

        last_log_sec = -15
        stall_count = 0
        last_current = -1

        while True:
            if cancel_event and cancel_event.is_set():
                try:
                    found_frame.evaluate("() => { const v = document.querySelector('video'); if (v) v.pause(); }")
                except Exception:
                    pass
                self.log("  ⏹ Reproducción de video pausada por cancelación.")
                return True

            try:
                state = found_frame.evaluate(poll_script)
            except Exception:
                state = None

            if not state:
                break

            duration = state.get("duration") or 0
            current = state.get("current") or 0
            ended = state.get("ended", False)
            paused = state.get("paused", False)

            # Si se pausó inesperadamente, reintentar Play
            if paused and not ended and duration > 0:
                try:
                    found_frame.evaluate("() => { const v = document.querySelector('video'); if (v) v.play(); }")
                except Exception:
                    pass

            # Detectar finalización
            if ended or (duration > 0 and current >= duration - 0.6):
                self.log(f"  ✓ Video completado ({_format_time(duration)} / {_format_time(duration)}).")
                break

            # Monitorear estancamiento por buffering
            if current == last_current and not paused:
                stall_count += 1
            else:
                stall_count = 0
            last_current = current

            # Reportar en el log cada 15 segundos de reproducción
            if abs(current - last_log_sec) >= 15:
                last_log_sec = current
                pct_str = f" ({round(current / duration * 100)}%)" if duration > 0 else ""
                self.log(f"  ▶ En reproducción: {_format_time(current)} / {_format_time(duration)}{pct_str}")

            time.sleep(1.0)

        return True

    def _try_read_pdf(
        self,
        context,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """
        Detecta si la página contiene un documento PDF en el visor Canvas y lo recorre.
        """
        frame = find_pdf_frame(context)
        if not frame:
            return False

        pages = total_pages(frame)
        if pages <= 0:
            pages = 1

        sec_per_page = max(3, int(self.settings.sim_pdf_page_seconds or 12))
        self.log(f"📄 Visor PDF detectado con {pages} página(s). Simulando lectura...")

        scroll_script = """(targetPage) => {
            const pageEl = document.querySelector(`.pdfViewer .page[data-page-number="${targetPage}"]`);
            if (pageEl) {
                pageEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
                return true;
            }
            const container = document.querySelector('#viewerContainer') || document.querySelector('#viewer') || document.documentElement;
            if (container) {
                container.scrollBy({ top: 400, behavior: 'smooth' });
                return true;
            }
            return false;
        }"""

        for p in range(1, pages + 1):
            if cancel_event and cancel_event.is_set():
                self.log("  ⏹ Lectura de PDF interrumpida.")
                return True

            self.log(f"  📖 Hojeando página {p} de {pages}...")
            try:
                frame.evaluate(scroll_script, p)
            except Exception:
                pass

            # Pausa natural simulando lectura de la página
            wait_time = sec_per_page + random.uniform(-2, 3)
            wait_time = max(2.5, wait_time)

            steps = int(wait_time * 2)
            for _ in range(steps):
                if cancel_event and cancel_event.is_set():
                    return True
                time.sleep(0.5)

        self.log("  ✓ Documento PDF leído por completo.")
        return True

    def _simulate_html_reading(
        self,
        page,
        cancel_event: threading.Event | None = None,
    ):
        """
        Simula la lectura de un artículo o página web estándar de Canvas:
        realiza desplazamientos progresivos hacia abajo con pausas naturales.
        """
        self.log("📖 Lectura de página HTML detectada. Recorriendo contenido...")

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
                self.log("  ⏹ Lectura de página interrumpida.")
                return

            step = random.randint(250, 450)
            current_y += step
            try:
                page.evaluate(f"window.scrollBy({{ top: {step}, behavior: 'smooth' }});")
            except Exception:
                pass

            time.sleep(scroll_step_delay + random.uniform(0.1, 0.4))

        # Pausa final al final de la página
        steps = int(reading_time * 2)
        for _ in range(steps):
            if cancel_event and cancel_event.is_set():
                return
            time.sleep(0.5)

        self.log("  ✓ Contenido de lectura completado.")
