from __future__ import annotations

import base64
from pathlib import Path


def find_canvas_html(context):
    selectors = [
        'div[data-resource-type="wiki_page.body"]',
        'div.show-content.user_content[data-lti-page-content="true"]',
        'div.show-content.user_content',
    ]

    for pg in context.pages:
        for frame in pg.frames:
            for selector in selectors:
                try:
                    loc = frame.locator(selector).first
                    if not loc.count():
                        continue

                    text = loc.inner_text(timeout=500).strip()
                    if len(text) >= 20 and loc.is_visible(timeout=500):
                        return frame, selector
                except Exception:
                    continue

    return None


def image_placeholder() -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="800" height="100">'
        '<rect width="100%" height="100%" fill="#eeeeee"/>'
        '<text x="20" y="58" font-family="Arial" '
        'font-size="18" fill="#555555">'
        'Imagen no disponible'
        '</text></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def canvas_image_data_uri(
    context,
    image_info: dict,
    referer: str = "",
) -> str:
    candidates = []
    headers = {}

    if referer:
        headers["Referer"] = referer

    api_url = (image_info.get("api") or "").strip()
    src_url = (image_info.get("src") or "").strip()

    if api_url:
        try:
            response = context.request.get(
                api_url,
                headers=headers,
                timeout=30_000,
            )
            if response.ok:
                metadata = response.json()
                if isinstance(metadata, dict):
                    for key in (
                        "url",
                        "download_url",
                        "preview_url",
                        "thumbnail_url",
                    ):
                        candidate = metadata.get(key)
                        if candidate and candidate not in candidates:
                            candidates.append(candidate)
        except Exception:
            pass

    if src_url and src_url not in candidates:
        candidates.append(src_url)

    for candidate in candidates:
        try:
            response = context.request.get(
                candidate,
                headers=headers,
                timeout=60_000,
            )
            if response.status not in (200, 206):
                continue

            body = response.body()
            if not body:
                continue

            ctype = (
                response.headers.get("content-type", "")
                .split(";")[0]
                .strip()
                .lower()
            )

            if not ctype.startswith("image/"):
                if body.startswith(b"\x89PNG"):
                    ctype = "image/png"
                elif body.startswith(b"\xff\xd8\xff"):
                    ctype = "image/jpeg"
                elif body[:6] in (b"GIF87a", b"GIF89a"):
                    ctype = "image/gif"
                else:
                    continue

            encoded = base64.b64encode(body).decode("ascii")
            return f"data:{ctype};base64,{encoded}"

        except Exception:
            continue

    raise RuntimeError("No se pudo recuperar la imagen.")


def standalone_html(fragment: str) -> str:
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<style>
@page {{
    size: A4;
    margin: 16mm;
}}
* {{
    box-sizing: border-box;
}}
html, body {{
    margin: 0;
    padding: 0;
    background: white;
    color: #1f2933;
    font-family: "Segoe UI", Arial, Helvetica, sans-serif;
    font-size: 11pt;
    line-height: 1.5;
}}
h1 {{
    font-size: 22pt;
    line-height: 1.2;
    margin: 0 0 8mm 0;
}}
h2 {{
    font-size: 16pt;
    line-height: 1.25;
    margin: 8mm 0 3mm 0;
    break-after: avoid-page;
}}
h3 {{
    font-size: 13pt;
    margin: 6mm 0 2mm 0;
    break-after: avoid-page;
}}
p {{
    margin: 0 0 4mm 0;
    orphans: 3;
    widows: 3;
}}
img {{
    display: block;
    max-width: 100%;
    height: auto;
    margin: 4mm auto 5mm auto;
    break-inside: avoid;
}}
p:has(img) {{
    break-inside: avoid;
}}
ul, ol {{
    margin: 2mm 0 4mm 0;
    padding-left: 8mm;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    margin: 4mm 0;
}}
th, td {{
    border: 1px solid #d0d5dd;
    padding: 2mm;
    vertical-align: top;
}}
th {{
    background: #f2f4f7;
}}
a {{
    color: #175cd3;
    overflow-wrap: anywhere;
}}
#todo-date-mount-point,
#assign-to-mount-point,
#choose-editor-mount-point {{
    display: none !important;
}}
</style>
</head>
<body>
{fragment}
</body>
</html>
"""


def save_html_as_pdf(
    context,
    module_dir: Path,
    base_name: str,
    log_fn=None,
) -> Path:
    log = log_fn or (lambda msg: None)
    found = find_canvas_html(context)

    if found is None:
        raise RuntimeError("El contenido HTML desapareció antes de poder extraerlo.")

    frame, selector = found

    extracted = frame.locator(selector).first.evaluate(
        """el => {
            const originalImages = [...el.querySelectorAll('img')];
            const clone = el.cloneNode(true);
            const cloneImages = [...clone.querySelectorAll('img')];

            clone.querySelectorAll(
                'script, style, noscript, #todo-date-mount-point, ' +
                '#assign-to-mount-point, #choose-editor-mount-point'
            ).forEach(x => x.remove());

            const images = originalImages.map((img, i) => {
                const token = `__AWS_IMAGE_${i}__`;

                if (cloneImages[i]) {
                    cloneImages[i].setAttribute('src', token);
                    cloneImages[i].removeAttribute('srcset');
                    cloneImages[i].removeAttribute('loading');
                }

                return {
                    token,
                    src: img.currentSrc || img.src ||
                         img.getAttribute('src') || '',
                    api: img.getAttribute('data-api-endpoint') || '',
                    alt: img.getAttribute('alt') || ''
                };
            });

            return {
                html: clone.outerHTML,
                images
            };
        }"""
    )

    html_fragment = extracted["html"]
    images = extracted.get("images") or []
    frame_url = frame.url or ""

    log(f"Página HTML: {len(images)} imágenes encontradas.")

    for index, image in enumerate(images, start=1):
        token = image.get("token", "")
        if not token:
            continue

        try:
            data_uri = canvas_image_data_uri(
                context=context,
                image_info=image,
                referer=frame_url,
            )
            html_fragment = html_fragment.replace(token, data_uri)
            log(f"Imagen {index}/{len(images)} incorporada.")
        except Exception as exc:
            log(f"No pude incorporar la imagen {index}/{len(images)}: {exc}")
            html_fragment = html_fragment.replace(token, image_placeholder())

    standalone = standalone_html(html_fragment)
    final_path = module_dir / f"{base_name}.pdf"

    if final_path.exists():
        final_path.unlink()

    print_page = context.new_page()

    try:
        print_page.set_content(
            standalone,
            wait_until="load",
            timeout=60_000,
        )
        print_page.emulate_media(media="print")
        print_page.pdf(
            path=str(final_path),
            format="A4",
            print_background=True,
            margin={
                "top": "16mm",
                "right": "16mm",
                "bottom": "18mm",
                "left": "16mm",
            },
        )
    finally:
        try:
            print_page.close()
        except Exception:
            pass

    return final_path

