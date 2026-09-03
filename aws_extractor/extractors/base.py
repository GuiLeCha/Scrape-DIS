from __future__ import annotations

from pathlib import Path


def download_resource(
    context,
    resource_url: str,
    destination: Path,
    referer: str = "",
    is_video: bool = False,
):
    headers = {}
    if referer:
        headers["Referer"] = referer

    if is_video:
        headers["Range"] = "bytes=0-"

    response = context.request.get(
        resource_url,
        headers=headers,
        timeout=180_000,
    )

    if response.status not in (200, 206):
        raise RuntimeError(f"No pude descargar el recurso. HTTP {response.status}.")

    body = response.body()
    if not body:
        raise RuntimeError("El recurso descargado está vacío.")

    if is_video:
        content_type = (
            response.headers.get("content-type", "")
            .split(";")[0]
            .strip()
            .lower()
        )

        preview = body[:256].lstrip()

        if (
            "text/vtt" in content_type
            or "webvtt" in content_type
            or preview.upper().startswith(b"WEBVTT")
        ):
            raise RuntimeError(
                "El recurso seleccionado como video es en realidad "
                "un subtítulo WEBVTT. Se descartó antes de ejecutar FFmpeg."
            )

        has_mp4_signature = b"ftyp" in body[:64]

        if (
            not has_mp4_signature
            and "video/mp4" not in content_type
            and not content_type.startswith("video/")
        ):
            raise RuntimeError(
                "El recurso descargado no presenta una firma/contenido "
                "compatible con MP4."
            )

    destination.write_bytes(body)

