from __future__ import annotations

import shutil
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urljoin

from aws_extractor.config import Settings
from aws_extractor.extractors.base import download_resource
from aws_extractor.media.ffmpeg import burn_subtitles
from aws_extractor.media.subtitles import (
    choose_spanish_subtitle_source,
    is_spanish_track,
    write_vtt_from_cues,
)
from aws_extractor.utils import looks_like_mp4_url, looks_like_vtt_url


def remember_subtitle_track(capture: dict, track: dict, log_fn=None):
    if not capture:
        return

    url = (track.get("url") or "").strip()
    language = (track.get("language") or "").strip()
    label = (track.get("label") or "").strip()
    kind = (track.get("kind") or "").strip()
    referer = (track.get("referer") or "").strip()

    if not url:
        return

    key = (url, language.lower(), label.lower(), kind.lower())

    for existing in capture.get("subtitle_tracks", []):
        existing_key = (
            (existing.get("url") or ""),
            (existing.get("language") or "").lower(),
            (existing.get("label") or "").lower(),
            (existing.get("kind") or "").lower(),
        )
        if existing_key == key:
            return

    normalized = {
        "url": url,
        "language": language,
        "label": label,
        "kind": kind,
        "referer": referer,
        "source": track.get("source", ""),
    }

    capture.setdefault("subtitle_tracks", []).append(normalized)
    capture.setdefault("referers", {})[url] = referer

    if log_fn:
        log_fn(
            "Pista de subtítulos detectada por Video.js: "
            f"idioma={language or '?'} | "
            f"label={label or '?'} | "
            f"{url[:150]}"
        )


def remember_text_track(capture: dict, track: dict):
    if not capture:
        return

    cues = track.get("cues") or []
    if not cues:
        return

    language = (track.get("language") or "").strip()
    label = (track.get("label") or "").strip()
    kind = (track.get("kind") or "").strip()

    key = (language.lower(), label.lower(), kind.lower(), len(cues))

    for existing in capture.get("text_tracks", []):
        existing_key = (
            (existing.get("language") or "").lower(),
            (existing.get("label") or "").lower(),
            (existing.get("kind") or "").lower(),
            len(existing.get("cues") or []),
        )
        if existing_key == key:
            return

    capture.setdefault("text_tracks", []).append({
        "language": language,
        "label": label,
        "kind": kind,
        "mode": track.get("mode", ""),
        "cues": cues,
        "referer": track.get("referer", ""),
        "source": track.get("source", ""),
    })


def remember_media_url(capture: dict, url: str, referer: str = "", log_fn=None):
    if not capture or not url:
        return

    if looks_like_vtt_url(url):
        if url not in capture.get("vtt_urls", []):
            capture.setdefault("vtt_urls", []).append(url)
            capture.setdefault("referers", {})[url] = referer
            if log_fn:
                log_fn("Subtítulo detectado: " + url[:170])
        return

    if looks_like_mp4_url(url):
        if url not in capture.get("mp4_urls", []):
            capture.setdefault("mp4_urls", []).append(url)
            capture.setdefault("referers", {})[url] = referer
            if log_fn:
                log_fn("MP4 detectado: " + url[:170])


def scan_media_resources(context, capture: dict, log_fn=None):
    for pg in context.pages:
        for frame in pg.frames:
            try:
                frame_url = frame.url or ""
            except Exception:
                frame_url = ""

            for selector in ("video", "video source", "track"):
                try:
                    loc = frame.locator(selector)
                    for i in range(loc.count()):
                        item = loc.nth(i)
                        src = item.get_attribute("src") or ""

                        if not src and selector == "video":
                            try:
                                src = item.evaluate("el => el.currentSrc || ''")
                            except Exception:
                                pass

                        if src:
                            absolute = urljoin(frame_url, src)
                            remember_media_url(capture, absolute, frame_url, log_fn)

                            if selector == "track":
                                try:
                                    remember_subtitle_track(
                                        capture,
                                        {
                                            "url": absolute,
                                            "language": item.get_attribute("srclang") or "",
                                            "label": item.get_attribute("label") or "",
                                            "kind": item.get_attribute("kind") or "",
                                            "referer": frame_url,
                                            "source": "dom",
                                        },
                                        log_fn,
                                    )
                                except Exception:
                                    pass
                except Exception:
                    pass

            try:
                resources = frame.evaluate(
                    """() => performance.getEntriesByType('resource')
                        .map(r => r.name)
                        .filter(u => /\\.mp4(?:\\?|$)|\\.vtt(?:\\?|$)/i.test(u))"""
                )
                for resource in resources or []:
                    remember_media_url(capture, resource, frame_url, log_fn)
            except Exception:
                pass

            try:
                videojs_data = frame.evaluate(
                    """() => {
                        if (
                            typeof videojs === 'undefined' ||
                            typeof videojs.getPlayers !== 'function'
                        ) {
                            return [];
                        }

                        const players = Object.values(
                            videojs.getPlayers()
                        ).filter(Boolean);

                        return players.map(p => {
                            let video = '';
                            try {
                                video = p.currentSrc() || '';
                            } catch (e) {}

                            let remoteTrackEls = [];
                            try {
                                if (
                                    typeof p.remoteTextTrackEls ===
                                    'function'
                                ) {
                                    remoteTrackEls = Array.from(
                                        p.remoteTextTrackEls()
                                    ).map(t => {
                                        let src = '';
                                        try {
                                            src = t.src ||
                                                  t.getAttribute?.('src') ||
                                                  '';
                                        } catch (e) {}

                                        let absolute = src;
                                        try {
                                            if (src) {
                                                absolute = new URL(
                                                    src,
                                                    location.href
                                                ).href;
                                            }
                                        } catch (e) {}

                                        return {
                                            url: absolute || src,
                                            language:
                                                t.srclang ||
                                                t.getAttribute?.(
                                                    'srclang'
                                                ) ||
                                                '',
                                            label:
                                                t.label ||
                                                t.getAttribute?.(
                                                    'label'
                                                ) ||
                                                '',
                                            kind:
                                                t.kind ||
                                                t.getAttribute?.(
                                                    'kind'
                                                ) ||
                                                ''
                                        };
                                    });
                                }
                            } catch (e) {}

                            let textTracks = [];
                            try {
                                textTracks = Array.from(
                                    p.textTracks()
                                ).map(t => {
                                    let cues = [];
                                    try {
                                        if (t.cues) {
                                            cues = Array.from(t.cues)
                                                .map(c => ({
                                                    start:
                                                        Number(
                                                            c.startTime
                                                        ),
                                                    end:
                                                        Number(
                                                            c.endTime
                                                        ),
                                                    text:
                                                        String(
                                                            c.text || ''
                                                        )
                                                }));
                                        }
                                    } catch (e) {}

                                    return {
                                        language: t.language || '',
                                        label: t.label || '',
                                        kind: t.kind || '',
                                        mode: t.mode || '',
                                        cues
                                    };
                                });
                            } catch (e) {}

                            return {
                                video,
                                remoteTrackEls,
                                textTracks
                            };
                        });
                    }"""
                )

                for player_data in videojs_data or []:
                    video_src = (player_data.get("video") or "").strip()
                    if video_src:
                        remember_media_url(
                            capture,
                            urljoin(frame_url, video_src),
                            frame_url,
                            log_fn,
                        )

                    for track in player_data.get("remoteTrackEls") or []:
                        absolute = urljoin(
                            frame_url,
                            (track.get("url") or "").strip(),
                        )
                        if not absolute:
                            continue

                        remember_media_url(capture, absolute, frame_url, log_fn)
                        remember_subtitle_track(
                            capture,
                            {
                                "url": absolute,
                                "language": track.get("language", ""),
                                "label": track.get("label", ""),
                                "kind": track.get("kind", ""),
                                "referer": frame_url,
                                "source": "videojs-remote",
                            },
                            log_fn,
                        )

                    for track in player_data.get("textTracks") or []:
                        cues = track.get("cues") or []
                        if not cues:
                            continue

                        remember_text_track(
                            capture,
                            {
                                "language": track.get("language", ""),
                                "label": track.get("label", ""),
                                "kind": track.get("kind", ""),
                                "mode": track.get("mode", ""),
                                "cues": cues,
                                "referer": frame_url,
                                "source": "videojs-cues",
                            },
                        )
            except Exception:
                pass


def wait_video_tracks(context, capture: dict, seconds: int = 5, log_fn=None):
    end = time.time() + seconds
    while time.time() < end:
        scan_media_resources(context, capture, log_fn)
        time.sleep(0.4)


def save_video(
    context,
    capture: dict,
    module_dir: Path,
    base_name: str,
    settings: Settings,
    log_fn=None,
    progress_fn=None,
    cancel_event: threading.Event | None = None,
) -> list[Path]:
    log = log_fn or (lambda msg: None)
    wait_video_tracks(context, capture, seconds=4, log_fn=log)

    mp4_urls = [
        url for url in capture.get("mp4_urls", [])
        if looks_like_mp4_url(url)
    ]
    referers = capture.get("referers", {})

    if not mp4_urls:
        raise RuntimeError("No encontré un archivo MP4 válido.")

    selected_mp4 = sorted(
        dict.fromkeys(mp4_urls),
        key=lambda u: (
            0 if "/r/courses/" in u.lower() else 1,
            len(u),
        ),
    )[0]

    log(f"MP4 seleccionado: {selected_mp4[:170]}")
    subtitle_mode, subtitle_source = choose_spanish_subtitle_source(capture, log_fn=log)

    final_mp4 = module_dir / f"{base_name}.mp4"
    final_txt = module_dir / f"{base_name}.txt"

    if final_mp4.exists():
        final_mp4.unlink()

    if final_txt.exists():
        final_txt.unlink()

    results = []

    with tempfile.TemporaryDirectory(prefix="aws_academy_video_") as td:
        temp_dir = Path(td)
        temp_mp4 = temp_dir / "video.mp4"
        temp_vtt = temp_dir / "subtitulos_es.vtt"

        log("Descargando MP4 original...")
        download_resource(
            context=context,
            resource_url=selected_mp4,
            destination=temp_mp4,
            referer=referers.get(selected_mp4, ""),
            is_video=True,
        )

        if cancel_event and cancel_event.is_set():
            raise RuntimeError("Operación cancelada por el usuario.")

        have_subtitles = False

        if subtitle_mode == "url" and subtitle_source:
            subtitle_url = (subtitle_source.get("url") or "").strip()
            if subtitle_url:
                language = subtitle_source.get("language") or ""
                label = subtitle_source.get("label") or ""

                log(
                    f"Subtítulo seleccionado: idioma={language or '?'} | "
                    f"label={label or '?'} | fuente={subtitle_source.get('source') or '?'}"
                )

                try:
                    log("Descargando subtítulos...")
                    download_resource(
                        context=context,
                        resource_url=subtitle_url,
                        destination=temp_vtt,
                        referer=(
                            subtitle_source.get("referer")
                            or referers.get(subtitle_url, "")
                        ),
                    )

                    raw = temp_vtt.read_bytes()
                    preview = raw[:200].decode("utf-8-sig", errors="ignore")
                    if "WEBVTT" not in preview.upper():
                        raise RuntimeError("El recurso descargado no parece un archivo WEBVTT.")

                    have_subtitles = True
                except Exception as exc:
                    log(
                        f"No pude usar la URL del subtítulo ({exc}). "
                        "Intentaré reconstruirlo desde los cues de Video.js."
                    )

        if not have_subtitles:
            cue_track = None
            if subtitle_mode == "cues":
                cue_track = subtitle_source
            else:
                for track in capture.get("text_tracks", []):
                    if is_spanish_track(track.get("language", ""), track.get("label", "")) and track.get("cues"):
                        cue_track = track
                        break

                if cue_track is None:
                    cue_tracks = [t for t in capture.get("text_tracks", []) if t.get("cues")]
                    if len(cue_tracks) == 1:
                        cue_track = cue_tracks[0]

            if cue_track:
                write_vtt_from_cues(cue_track, temp_vtt, log_fn=log)
                have_subtitles = True

        if have_subtitles:
            raw_subtitles = temp_vtt.read_bytes()
            try:
                subtitle_text = raw_subtitles.decode("utf-8-sig")
            except UnicodeDecodeError:
                subtitle_text = raw_subtitles.decode("utf-8", errors="replace")

            final_txt.write_text(subtitle_text, encoding="utf-8")
            log(f"Subtítulos guardados como texto: {final_txt.name}")

            if settings.burn_subtitles:
                log("Incrustando subtítulos en el video con FFmpeg...")
                burn_subtitles(
                    input_mp4=temp_mp4,
                    input_vtt=temp_vtt,
                    output_mp4=final_mp4,
                    settings=settings,
                    log_fn=log,
                    progress_fn=progress_fn,
                    cancel_event=cancel_event,
                )
            else:
                log("BURN_SUBTITLES desactivado: copiando MP4 original...")
                shutil.copy2(temp_mp4, final_mp4)

            results.extend([final_mp4, final_txt])
        else:
            log("No pude recuperar subtítulos utilizables. Guardaré solamente el MP4 original.")
            shutil.copy2(temp_mp4, final_mp4)
            results.append(final_mp4)

    return results

