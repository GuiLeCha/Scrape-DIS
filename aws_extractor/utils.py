from __future__ import annotations

import ctypes
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

BAD_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1F]+')


def safe_name(text: str, fallback: str = "material") -> str:
    text = (text or "").strip()
    text = BAD_FILENAME.sub("_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:160] or fallback


def output_base_name(name: str) -> str:
    name = safe_name(name, "material")
    suffix = Path(name).suffix.lower()
    if suffix in {".pdf", ".mp4", ".html", ".vtt"}:
        name = name[: -len(suffix)]
    return safe_name(name, "material")


def media_url_path(url: str) -> str:
    try:
        return unquote(urlparse(url or "").path).lower()
    except Exception:
        return str(url or "").lower()


def looks_like_pdf(url: str, headers: dict[str, str]) -> bool:
    ctype = (headers.get("content-type") or "").lower()
    dispo = (headers.get("content-disposition") or "").lower()
    path = urlparse(url).path.lower()
    return "application/pdf" in ctype or ".pdf" in path or ".pdf" in dispo


def looks_like_vtt_url(url: str) -> bool:
    """
    Un subtítulo puede llamarse 'video.mp4.vtt'.
    Por eso NO alcanza con preguntar si la URL contiene '.mp4'.
    """
    return media_url_path(url).endswith(".vtt")


def looks_like_mp4_url(url: str) -> bool:
    """
    Sólo considera MP4 si la ruta termina realmente en .mp4.
    'video.mp4.vtt' debe ser VTT, nunca MP4.
    """
    return media_url_path(url).endswith(".mp4")


def looks_like_vtt_response(url: str, headers: dict[str, str]) -> bool:
    ctype = (headers.get("content-type") or "").lower()
    return (
        looks_like_vtt_url(url)
        or "text/vtt" in ctype
        or "webvtt" in ctype
    )


def looks_like_mp4_response(url: str, headers: dict[str, str]) -> bool:
    ctype = (headers.get("content-type") or "").lower()

    if looks_like_vtt_response(url, headers):
        return False

    return (
        looks_like_mp4_url(url)
        or "video/mp4" in ctype
    )


def enable_windows_dpi_awareness():
    """
    Evita que Windows aplique escalado bitmap/virtualización a Tkinter.
    Debe ejecutarse antes de crear la ventana Tk.
    """
    if os.name != "nt":
        return

    try:
        # Windows 10/11: Per Monitor V2.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4)
        )
        return
    except Exception:
        pass

    try:
        # Fallback Windows 8.1+
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass

    try:
        # Fallback clásico
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def windows_scale_factor() -> float:
    """
    Devuelve aproximadamente 1.0, 1.25, 1.5, etc.
    """
    if os.name != "nt":
        return 1.0

    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        if dpi:
            return float(dpi) / 96.0
    except Exception:
        pass

    try:
        hdc = ctypes.windll.user32.GetDC(0)
        LOGPIXELSX = 88
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
        ctypes.windll.user32.ReleaseDC(0, hdc)
        if dpi:
            return float(dpi) / 96.0
    except Exception:
        pass

    return 1.0


def windows_work_area() -> tuple[int, int] | None:
    """
    Devuelve (ancho, alto) del área de trabajo en píxeles físicos
    (pantalla SIN la barra de tareas).
    """
    if os.name != "nt":
        return None

    try:
        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        SPI_GETWORKAREA = 0x0030
        rect = RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        )
        if ok:
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width > 0 and height > 0:
                return int(width), int(height)
    except Exception:
        pass

    return None


def cleanup_profile_lock(profile_dir: Path):
    """
    Verifica y limpia posibles bloqueos del perfil de Chromium si quedaron
    archivos de bloqueo tras un cierre forzado.
    """
    if not profile_dir.exists():
        return

    lock_files = ["SingletonLock", "SingletonCookie", "SingletonSocket"]
    for lock_name in lock_files:
        lock_path = profile_dir / lock_name
        if lock_path.exists():
            try:
                if lock_path.is_file() or lock_path.is_symlink():
                    lock_path.unlink()
            except Exception:
                pass

