from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

APP_NAME = "AWS Academy Material Extractor v3.7"

DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
DRIVE_APP_PROPERTIES = {"aws_academy_extractor": "v3.7"}


def env_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {
        "1", "true", "yes", "si", "sí", "on"
    }


def resolve_project_path(base_dir: Path, raw_value: str, default_relative: str) -> Path:
    raw = (raw_value or "").strip().strip('"')
    path = Path(raw if raw else default_relative).expanduser()

    if not path.is_absolute():
        path = base_dir / path

    return path.resolve()


class Settings:
    """Configuración centralizada de la aplicación."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = Path(base_dir or Path.cwd()).resolve()
        self.env_path = self.base_dir / ".env"
        self.reload()

    def reload(self):
        if self.env_path.exists():
            load_dotenv(dotenv_path=self.env_path, override=True)

        self.output_dir = Path(
            os.getenv(
                "OUTPUT_DIR",
                str(Path.home() / "Documents" / "AWS_Academy_Material"),
            )
        )
        self.profile_dir = Path(
            os.getenv(
                "PROFILE_DIR",
                str(Path.home() / ".aws_academy_extractor_profile"),
            )
        )
        self.home_url = os.getenv(
            "AWS_HOME_URL",
            "https://awsacademy.instructure.com/courses/183094/modules",
        ).strip()

        # Timeouts en segundos
        self.viewer_load_timeout = int(os.getenv("VIEWER_LOAD_TIMEOUT", "240"))
        self.page_render_timeout = int(os.getenv("PAGE_RENDER_TIMEOUT", "90"))
        self.video_load_timeout = int(os.getenv("VIDEO_LOAD_TIMEOUT", "180"))
        self.auto_detect_timeout = int(os.getenv("AUTO_DETECT_TIMEOUT", "120"))

        # Video compression profile
        self.video_max_height = int(os.getenv("VIDEO_MAX_HEIGHT", "720"))
        self.video_crf = os.getenv("VIDEO_CRF", "24").strip() or "24"
        self.video_preset = os.getenv("VIDEO_PRESET", "slow").strip() or "slow"
        self.audio_bitrate = os.getenv("AUDIO_BITRATE", "64k").strip() or "64k"
        self.ffmpeg_path = os.getenv("FFMPEG_PATH", "").strip().strip('"')
        self.burn_subtitles = env_bool(os.getenv("BURN_SUBTITLES"), default=True)

        # Checkpoints & Resume
        self.resume_enabled = env_bool(os.getenv("RESUME_ENABLED"), default=True)
        self.force_redownload = env_bool(os.getenv("FORCE_REDOWNLOAD"), default=False)

        # Google Drive
        self.drive_enabled = env_bool(os.getenv("GOOGLE_DRIVE_ENABLED"), default=False)
        self.drive_folder_id = (
            os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()
            or os.getenv("GOOGLE_DRIVE_FOLDER_URL", "").strip()
        )
        self.drive_credentials = resolve_project_path(
            self.base_dir,
            os.getenv("GOOGLE_DRIVE_CREDENTIALS", ""),
            "private/credentials_drive.json",
        )
        self.drive_token = resolve_project_path(
            self.base_dir,
            os.getenv("GOOGLE_DRIVE_TOKEN", ""),
            "private/token_drive.json",
        )

