from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse


def is_spanish_track(language: str = "", label: str = "") -> bool:
    language = (language or "").strip().lower().replace("_", "-")
    label = (label or "").strip().lower()

    if language == "es" or language.startswith("es-"):
        return True

    spanish_labels = (
        "español",
        "espanol",
        "spanish",
        "castellano",
    )
    return any(token in label for token in spanish_labels)


def choose_spanish_vtt(urls: list[str]) -> str | None:
    if not urls:
        return None

    priorities = [
        "es-419",
        "es_la",
        "es-la",
        "es_es",
        "es-es",
        "_es_",
        "spanish",
        "espanol",
        "español",
    ]

    normalized = [(url, unquote(url).lower()) for url in urls]

    for token in priorities:
        for original, decoded in normalized:
            if token in decoded:
                return original

    for original, decoded in normalized:
        name = Path(urlparse(decoded).path).name
        if re.search(r"(^|[_\\-.])es([_\\-.]|$)", name):
            return original

    return None


def seconds_to_vtt_timestamp(seconds: float) -> str:
    try:
        total_ms = max(0, int(round(float(seconds) * 1000)))
    except Exception:
        total_ms = 0

    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)

    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def write_vtt_from_cues(track: dict, destination: Path, log_fn=None):
    cues = track.get("cues") or []
    if not cues:
        raise RuntimeError("El TextTrack no contiene cues.")

    lines = ["WEBVTT", ""]

    for index, cue in enumerate(cues, start=1):
        start = seconds_to_vtt_timestamp(cue.get("start", 0))
        end = seconds_to_vtt_timestamp(cue.get("end", 0))
        text = str(cue.get("text", "") or "")
        text = text.replace("\xa0", " ")

        lines.extend([
            str(index),
            f"{start} --> {end}",
            text,
            "",
        ])

    destination.write_text("\n".join(lines), encoding="utf-8")
    if log_fn:
        log_fn(f"VTT reconstruido desde Video.js: {len(cues)} cues.")


def choose_spanish_subtitle_source(capture: dict, log_fn=None):
    """
    Devuelve una tupla:
      ("url", track_dict)
      ("cues", text_track_dict)
      (None, None)

    Prioridad:
      1. metadata Video.js con srclang/label español
      2. cues Video.js en español
      3. heurística por nombre de URL
      4. si solo existe un VTT, usarlo como fallback
    """
    log = log_fn or (lambda msg: None)
    subtitle_tracks = capture.get("subtitle_tracks", [])
    text_tracks = capture.get("text_tracks", [])
    vtt_urls = capture.get("vtt_urls", [])

    # 1) URL remota con idioma declarado por Video.js
    for track in subtitle_tracks:
        if is_spanish_track(track.get("language", ""), track.get("label", "")):
            return "url", track

    # 2) Cues ya cargados por Video.js
    for track in text_tracks:
        if is_spanish_track(track.get("language", ""), track.get("label", "")) and track.get("cues"):
            return "cues", track

    # 3) Método histórico por nombre de archivo
    selected_vtt = choose_spanish_vtt(vtt_urls)
    if selected_vtt:
        return "url", {
            "url": selected_vtt,
            "language": "",
            "label": "",
            "kind": "",
            "referer": capture.get("referers", {}).get(selected_vtt, ""),
            "source": "network-name",
        }

    # 4) Fallback para única pista VTT
    if len(vtt_urls) == 1:
        only = vtt_urls[0]
        log("Solo hay una pista VTT disponible; la usaré como fallback de subtítulos.")
        return "url", {
            "url": only,
            "language": "",
            "label": "",
            "kind": "",
            "referer": capture.get("referers", {}).get(only, ""),
            "source": "single-vtt-fallback",
        }

    # Último recurso: único TextTrack con cues
    cue_tracks = [t for t in text_tracks if t.get("cues")]
    if len(cue_tracks) == 1:
        log("Solo hay un TextTrack con cues; lo usaré como fallback.")
        return "cues", cue_tracks[0]

    return None, None

