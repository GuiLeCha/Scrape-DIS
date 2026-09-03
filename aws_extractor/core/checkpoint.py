from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from aws_extractor.config import APP_NAME
from aws_extractor.utils import safe_name


class CheckpointManager:
    """
    Gestiona el estado persistente y atómico de descargas por módulo.
    Los checkpoints residen en el directorio de perfil para no alterar
    las carpetas de materiales ni sincronizarse accidentalmente con Drive.
    """

    def __init__(self, profile_dir: Path, log_fn=None):
        self.profile_dir = Path(profile_dir).resolve()
        self.log = log_fn or (lambda msg: None)

    def checkpoint_paths(self, module_dir: Path) -> tuple[Path, Path]:
        identity = str(module_dir.resolve())
        if os.name == "nt":
            identity = identity.casefold()

        digest = hashlib.sha256(
            identity.encode("utf-8", errors="replace")
        ).hexdigest()[:20]

        state_dir = self.profile_dir / "checkpoints"
        state_dir.mkdir(parents=True, exist_ok=True)

        return (
            state_dir / f"{digest}.json",
            state_dir / f"{digest}.log",
        )

    @staticmethod
    def utc_timestamp() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def load_checkpoint(self, module_dir: Path) -> tuple[dict, Path, Path]:
        state_path, history_path = self.checkpoint_paths(module_dir)

        state = {
            "schema": 1,
            "module_dir": str(module_dir.resolve()),
            "items": {},
        }

        if state_path.exists():
            try:
                loaded = json.loads(state_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    state.update(loaded)
                if not isinstance(state.get("items"), dict):
                    state["items"] = {}
            except Exception as exc:
                self.log(
                    "Checkpoint: no pude leer el estado anterior; "
                    f"crearé uno nuevo. Detalle: {exc}"
                )

        state["module_dir"] = str(module_dir.resolve())
        return state, state_path, history_path

    def save_checkpoint(self, state: dict, state_path: Path):
        """Escritura atómica de checkpoint."""
        state["updated_at"] = self.utc_timestamp()
        state["app_name"] = APP_NAME

        temp_path = state_path.with_suffix(state_path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_path, state_path)

    def append_history(self, history_path: Path, message: str):
        history_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with history_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")

    @staticmethod
    def valid_pdf_file(path: Path) -> bool:
        try:
            if not path.is_file() or path.stat().st_size < 100:
                return False
            with path.open("rb") as fh:
                return fh.read(5) == b"%PDF-"
        except Exception:
            return False

    @staticmethod
    def valid_mp4_file(path: Path) -> bool:
        try:
            if not path.is_file() or path.stat().st_size < 1024:
                return False
            with path.open("rb") as fh:
                head = fh.read(64)
            return b"ftyp" in head
        except Exception:
            return False

    @staticmethod
    def valid_subtitle_txt(path: Path) -> bool:
        try:
            if not path.is_file() or path.stat().st_size < 20:
                return False
            sample = path.read_text(encoding="utf-8-sig", errors="ignore")[:10000]
            return "WEBVTT" in sample.upper() and "-->" in sample
        except Exception:
            return False

    def validate_output_set(
        self,
        module_dir: Path,
        output_names: list[str],
    ) -> tuple[bool, list[Path]]:
        if not output_names:
            return False, []

        paths = [module_dir / name for name in output_names]

        for path in paths:
            suffix = path.suffix.lower()
            if suffix == ".pdf":
                if not self.valid_pdf_file(path):
                    return False, []
            elif suffix == ".mp4":
                if not self.valid_mp4_file(path):
                    return False, []
            elif suffix == ".txt":
                if not self.valid_subtitle_txt(path):
                    return False, []
            else:
                return False, []

        return True, paths

    def checkpoint_resume_item(
        self,
        state: dict,
        module_dir: Path,
        url: str,
    ) -> list[Path] | None:
        entry = state.get("items", {}).get(url)
        if not isinstance(entry, dict) or entry.get("status") != "ok":
            return None

        output_names = entry.get("outputs", [])
        if not isinstance(output_names, list):
            return None

        valid, paths = self.validate_output_set(module_dir, output_names)
        return paths if valid else None

    def bootstrap_existing_item(
        self,
        module_dir: Path,
        row_number: int,
        item_title: str,
    ) -> tuple[list[Path] | None, str]:
        title = (item_title or "").strip()
        if not title:
            return None, ""

        base_name = safe_name(
            f"{row_number}_{title}",
            f"{row_number}_Material",
        )

        mp4 = module_dir / f"{base_name}.mp4"
        txt = module_dir / f"{base_name}.txt"
        pdf = module_dir / f"{base_name}.pdf"

        if self.valid_mp4_file(mp4) and self.valid_subtitle_txt(txt):
            return [mp4, txt], "video_subtitulado"

        if self.valid_pdf_file(pdf):
            return [pdf], "pdf"

        return None, ""

    def mark_success(
        self,
        state: dict,
        state_path: Path,
        history_path: Path,
        url: str,
        row_number: int,
        item_title: str,
        item_results: list[Path],
        source: str = "download",
    ) -> str:
        names = [Path(p).name for p in item_results]
        suffixes = {Path(n).suffix.lower() for n in names}

        status = "partial"
        final_kind = "incompleto"

        if suffixes == {".pdf"} and len(names) == 1:
            valid, _ = self.validate_output_set(Path(state["module_dir"]), names)
            if valid:
                status = "ok"
                final_kind = "pdf"

        elif ".mp4" in suffixes and ".txt" in suffixes:
            valid, _ = self.validate_output_set(Path(state["module_dir"]), names)
            if valid:
                status = "ok"
                final_kind = "video_subtitulado"

        entry = {
            "status": status,
            "row_number": row_number,
            "title": item_title,
            "outputs": names,
            "kind": final_kind,
            "source": source,
            "completed_at": self.utc_timestamp() if status == "ok" else None,
            "last_attempt_at": self.utc_timestamp(),
            "app_name": APP_NAME,
        }

        state.setdefault("items", {})[url] = entry
        self.save_checkpoint(state, state_path)

        self.append_history(
            history_path,
            (
                f"{status.upper()} | fila={row_number} | "
                f"{item_title or url} | "
                f"archivos={', '.join(names) or '-'} | "
                f"fuente={source}"
            ),
        )

        return status

    def mark_error(
        self,
        state: dict,
        state_path: Path,
        history_path: Path,
        url: str,
        row_number: int,
        item_title: str,
        error: str,
    ):
        previous = state.setdefault("items", {}).get(url)
        if isinstance(previous, dict) and previous.get("status") == "ok":
            valid, _ = self.validate_output_set(
                Path(state["module_dir"]),
                previous.get("outputs", []),
            )
            if valid:
                return

        state["items"][url] = {
            "status": "error",
            "row_number": row_number,
            "title": item_title,
            "outputs": [],
            "last_error": str(error),
            "last_attempt_at": self.utc_timestamp(),
            "app_name": APP_NAME,
        }

        self.save_checkpoint(state, state_path)
        self.append_history(
            history_path,
            f"ERROR | fila={row_number} | {item_title or url} | {error}",
        )

