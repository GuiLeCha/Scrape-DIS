from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

from aws_extractor.config import Settings


def find_ffmpeg_executable(configured_path: str = "") -> str:
    if configured_path:
        p = Path(configured_path).expanduser()
        if p.is_file():
            return str(p)

    found = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if found:
        return found

    candidates = []
    local_appdata = os.getenv("LOCALAPPDATA", "").strip()

    if local_appdata:
        local = Path(local_appdata)
        candidates.extend([
            local / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe",
            local / "Programs" / "ffmpeg" / "bin" / "ffmpeg.exe",
        ])

        winget_packages = local / "Microsoft" / "WinGet" / "Packages"
        if winget_packages.exists():
            for package_dir in winget_packages.glob("*FFmpeg*"):
                try:
                    candidates.extend(package_dir.rglob("ffmpeg.exe"))
                except Exception:
                    pass

    candidates.extend([
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"),
    ])

    for candidate in candidates:
        try:
            if Path(candidate).is_file():
                return str(candidate)
        except Exception:
            pass

    raise RuntimeError(
        "No pude localizar ffmpeg.exe. "
        "Definí FFMPEG_PATH en el .env si es necesario."
    )


def parse_time_to_seconds(timestr: str) -> float:
    try:
        parts = timestr.strip().split(":")
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    except Exception:
        pass
    return 0.0


def burn_subtitles(
    input_mp4: Path,
    input_vtt: Path,
    output_mp4: Path,
    settings: Settings,
    log_fn=None,
    progress_fn=None,
    cancel_event: threading.Event | None = None,
):
    """
    Perfil optimizado para material de estudio con reporte de progreso en vivo:
      - máximo 720p, sin ampliar videos menores;
      - FPS original;
      - H.264 / CRF configurable;
      - preset configurable;
      - audio AAC mono a bitrate configurable;
      - subtítulos en español quemados en la imagen.
    """
    log = log_fn or (lambda msg: None)
    ffmpeg = find_ffmpeg_executable(settings.ffmpeg_path)

    crf = str(settings.video_crf)
    preset = str(settings.video_preset)
    audio_bitrate = str(settings.audio_bitrate)
    max_height_int = max(1, int(settings.video_max_height))

    subtitle_arg = str(input_vtt.resolve()).replace("\\", "/")
    subtitle_arg = subtitle_arg.replace(":", r"\:")
    subtitle_arg = subtitle_arg.replace("'", r"\'")

    scale_filter = (
        f"scale='if(gt(ih,{max_height_int}),-2,iw)':"
        f"'if(gt(ih,{max_height_int}),{max_height_int},ih)'"
    )
    video_filter = f"{scale_filter},subtitles=filename='{subtitle_arg}'"

    log(
        "Perfil de video: "
        f"máx. {max_height_int}p | H.264 CRF {crf} | "
        f"preset {preset} | AAC mono {audio_bitrate} | FPS original"
    )

    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(input_mp4),
        "-vf",
        video_filter,
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        crf,
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-ac",
        "1",
        "-movflags",
        "+faststart",
        str(output_mp4),
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    duration_seconds = 0.0
    duration_regex = re.compile(r"Duration:\s*(\d{2}:\d{2}:\d{2}\.\d+)")
    time_regex = re.compile(r"time=\s*(\d{2}:\d{2}:\d{2}\.\d+)")
    stderr_lines = []
    last_log_pct = -1

    try:
        if process.stderr:
            for line in process.stderr:
                stderr_lines.append(line)
                if len(stderr_lines) > 200:
                    stderr_lines.pop(0)

                if cancel_event and cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except Exception:
                        process.kill()
                    if output_mp4.exists():
                        output_mp4.unlink()
                    raise RuntimeError("Operación cancelada por el usuario.")

                if not duration_seconds:
                    dur_match = duration_regex.search(line)
                    if dur_match:
                        duration_seconds = parse_time_to_seconds(dur_match.group(1))

                time_match = time_regex.search(line)
                if time_match and duration_seconds > 0:
                    current_sec = parse_time_to_seconds(time_match.group(1))
                    pct = min(99, max(0, int((current_sec / duration_seconds) * 100)))

                    if progress_fn:
                        progress_fn(pct)

                    if pct % 20 == 0 and pct != last_log_pct:
                        log(f"Codificando video: {pct}% completado...")
                        last_log_pct = pct

        return_code = process.wait()

        if return_code != 0:
            if cancel_event and cancel_event.is_set():
                raise RuntimeError("Operación cancelada por el usuario.")

            tail = "".join(stderr_lines)[-3500:]
            raise RuntimeError(
                "FFmpeg no pudo generar el MP4 subtitulado/optimizado.\n\n" + tail
            )

    finally:
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                process.kill()

