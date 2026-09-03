from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path
from PIL import Image


def find_pdf_frame(context):
    for pg in context.pages:
        for frame in pg.frames:
            try:
                if frame.locator("body#mediaContent.pdf").count():
                    return frame
            except Exception:
                pass

            try:
                if (
                    frame.locator("#rscpAu-TotalPageDisplay").count()
                    and frame.locator(".pdfViewer .page[data-page-number]").count()
                ):
                    return frame
            except Exception:
                pass

    return None


def save_original_pdf(context, capture: dict, final_path: Path) -> bool:
    responses = list(capture.get("pdf_responses", []))
    seen = set()

    for response in responses:
        try:
            url = response.url
            if url in seen:
                continue
            seen.add(url)

            headers = {"Range": "bytes=0-"}
            try:
                referer = response.request.headers.get("referer", "")
                if referer:
                    headers["Referer"] = referer
            except Exception:
                pass

            fetched = context.request.get(url, headers=headers, timeout=120_000)
            body = fetched.body()

            if fetched.status in (200, 206) and body.startswith(b"%PDF-"):
                final_path.write_bytes(body)
                return True
        except Exception:
            continue

    urls = []
    for pg in context.pages:
        for frame in pg.frames:
            try:
                resources = frame.evaluate(
                    """() => performance.getEntriesByType('resource')
                        .map(r => r.name)
                        .filter(u => /\\.pdf(?:\\?|$)/i.test(u))"""
                )
                urls.extend(resources or [])
            except Exception:
                pass

    for url in dict.fromkeys(urls):
        try:
            fetched = context.request.get(
                url,
                headers={"Range": "bytes=0-"},
                timeout=120_000,
            )
            body = fetched.body()
            if fetched.status in (200, 206) and body.startswith(b"%PDF-"):
                final_path.write_bytes(body)
                return True
        except Exception:
            continue

    return False


def total_pages(frame) -> int:
    try:
        text = frame.locator("#rscpAu-TotalPageDisplay").inner_text(timeout=800)
        digits = re.sub(r"\D", "", text)
        if digits:
            return int(digits)
    except Exception:
        pass

    try:
        return frame.locator(".pdfViewer .page[data-page-number]").count()
    except Exception:
        return 0


def wait_pdf_viewer_ready(
    context,
    initial_frame,
    timeout_seconds: int,
    log_fn=None,
):
    log = log_fn or (lambda msg: None)
    deadline = time.time() + timeout_seconds
    frame = initial_frame
    stable_since = None
    last_log = 0.0

    while time.time() < deadline:
        try:
            if frame is None or frame.is_detached():
                frame = find_pdf_frame(context)
        except Exception:
            frame = find_pdf_frame(context)

        if frame is None:
            time.sleep(0.5)
            continue

        tot = total_pages(frame)

        try:
            nodes = frame.locator(".pdfViewer .page[data-page-number]").count()
        except Exception:
            nodes = 0

        first_ready = False
        try:
            first_ready = frame.locator(
                '.page[data-page-number="1"]'
            ).evaluate(
                """el => {
                    const canvas = el.querySelector('canvas');
                    const loading = !!el.querySelector('.loadingIcon');
                    return !!canvas &&
                           canvas.width > 0 &&
                           canvas.height > 0 &&
                           !loading;
                }"""
            )
        except Exception:
            pass

        ready = tot > 0 and nodes >= tot and first_ready
        now = time.time()

        if ready:
            if stable_since is None:
                stable_since = now

            if now - stable_since >= 2:
                log(f"Visor listo: {tot} páginas.")
                return frame, tot
        else:
            stable_since = None

        if now - last_log >= 5:
            log(f"Esperando visor... total={tot}, páginas creadas={nodes}.")
            last_log = now

        time.sleep(0.5)

    raise RuntimeError("El visor PDF no terminó de inicializarse a tiempo.")


def wait_page_render(frame, number: int, timeout_seconds: int):
    selector = f'.page[data-page-number="{number}"]'
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        try:
            state = frame.locator(selector).evaluate(
                """el => {
                    const canvas = el.querySelector('canvas');
                    const loading = !!el.querySelector('.loadingIcon');
                    return {
                        ready: !!canvas &&
                               canvas.width > 0 &&
                               canvas.height > 0 &&
                               !loading
                    };
                }"""
            )
            if state["ready"]:
                return
        except Exception:
            pass

        time.sleep(0.2)

    raise RuntimeError(f"La página {number} no terminó de renderizar.")


def jpgs_to_pdf(jpg_paths: list[Path], output_path: Path):
    if not jpg_paths:
        raise RuntimeError("No se generaron páginas para el PDF.")

    opened = []
    try:
        for path in jpg_paths:
            img = Image.open(path)
            if img.mode != "RGB":
                img = img.convert("RGB")
            opened.append(img.copy())
            img.close()

        opened[0].save(
            output_path,
            "PDF",
            resolution=150.0,
            save_all=True,
            append_images=opened[1:],
        )
    finally:
        for img in opened:
            try:
                img.close()
            except Exception:
                pass


def render_pdf(
    frame,
    total: int,
    output_path: Path,
    page_render_timeout: int = 90,
    log_fn=None,
):
    log = log_fn or (lambda msg: None)

    with tempfile.TemporaryDirectory(prefix="aws_academy_pdf_") as td:
        temp_dir = Path(td)
        images = []

        for number in range(1, total + 1):
            log(f"Renderizando página {number}/{total}...")
            page_loc = frame.locator(f'.page[data-page-number="{number}"]').first

            if not page_loc.count():
                raise RuntimeError(f"No encontré la página {number}.")

            page_loc.scroll_into_view_if_needed(timeout=30_000)
            time.sleep(0.35)

            wait_page_render(
                frame=frame,
                number=number,
                timeout_seconds=page_render_timeout,
            )

            image_path = temp_dir / f"page_{number:04d}.jpg"
            page_loc.screenshot(
                path=str(image_path),
                type="jpeg",
                quality=94,
                timeout=max(30_000, page_render_timeout * 1000),
            )
            images.append(image_path)

        jpgs_to_pdf(images, output_path)


def save_pdf(
    context,
    capture: dict,
    module_dir: Path,
    base_name: str,
    viewer_load_timeout: int = 240,
    page_render_timeout: int = 90,
    log_fn=None,
) -> Path:
    log = log_fn or (lambda msg: None)
    final_path = module_dir / f"{base_name}.pdf"

    if final_path.exists():
        final_path.unlink()

    if save_original_pdf(context, capture, final_path):
        log("PDF original recuperado.")
        return final_path

    frame = find_pdf_frame(context)
    if frame is None:
        raise RuntimeError(
            "Detecté un PDF pero no pude recuperar el archivo ni localizar el visor."
        )

    log(f"Esperando que el visor PDF termine de inicializarse (máximo {viewer_load_timeout} s)...")
    frame, tot = wait_pdf_viewer_ready(
        context=context,
        initial_frame=frame,
        timeout_seconds=viewer_load_timeout,
        log_fn=log,
    )

    if save_original_pdf(context, capture, final_path):
        log("PDF original recuperado.")
        return final_path

    log("No pude bajar los bytes originales; reconstruyo el PDF desde el visor.")
    render_pdf(
        frame=frame,
        total=tot,
        output_path=final_path,
        page_render_timeout=page_render_timeout,
        log_fn=log,
    )

    return final_path

