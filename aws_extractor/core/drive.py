from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path

from aws_extractor.config import (
    DRIVE_APP_PROPERTIES,
    DRIVE_FOLDER_MIME,
    DRIVE_SCOPE,
    env_bool,
    resolve_project_path,
)
from aws_extractor.utils import safe_name


def extract_drive_folder_id(value: str) -> str:
    """
    Acepta:
      - ID puro de carpeta
      - https://drive.google.com/drive/folders/<ID>
      - URLs con ?id=<ID>
    """
    value = (value or "").strip()
    if not value:
        return ""

    match = re.search(r"/folders/([A-Za-z0-9_-]+)", value)
    if match:
        return match.group(1)

    match = re.search(r"[?&]id=([A-Za-z0-9_-]+)", value)
    if match:
        return match.group(1)

    if "://" not in value and re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value

    return ""


class GoogleDriveUploader:
    """
    Subida conservadora a Google Drive.
    - Reutiliza credenciales OAuth (private/credentials_drive.json, private/token_drive.json).
    - Crea/reutiliza subcarpeta con el nombre del módulo.
    - Si un archivo con el mismo nombre ya existe, actualiza su contenido.
    - NO elimina archivos remotos.
    - Los errores de Drive no invalidan descargas locales.
    """

    def __init__(self, base_dir: Path, log_callback=None):
        self.base_dir = Path(base_dir).resolve()
        self.log = log_callback or (lambda msg: None)
        self.service = None

        self.enabled = env_bool(
            os.getenv("GOOGLE_DRIVE_ENABLED"),
            default=False,
        )

        configured_folder = (
            os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()
            or os.getenv("GOOGLE_DRIVE_FOLDER_URL", "").strip()
        )
        self.parent_folder_id = extract_drive_folder_id(configured_folder)

        self.credentials_path = resolve_project_path(
            self.base_dir,
            os.getenv("GOOGLE_DRIVE_CREDENTIALS", ""),
            "private/credentials_drive.json",
        )
        self.token_path = resolve_project_path(
            self.base_dir,
            os.getenv("GOOGLE_DRIVE_TOKEN", ""),
            "private/token_drive.json",
        )

    def _load_google_libraries(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:
            raise RuntimeError(
                "Faltan librerías de Google Drive. Instalá: "
                "py -m pip install google-api-python-client "
                "google-auth-httplib2 google-auth-oauthlib"
            ) from exc

        return (
            Request,
            Credentials,
            InstalledAppFlow,
            build,
            MediaFileUpload,
        )

    def _authenticate(self):
        (
            Request,
            Credentials,
            InstalledAppFlow,
            build,
            _,
        ) = self._load_google_libraries()

        if not self.credentials_path.exists():
            raise FileNotFoundError(
                "No encontré las credenciales OAuth de Google Drive: "
                f"{self.credentials_path}"
            )

        creds = None

        if self.token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self.token_path),
                    [DRIVE_SCOPE],
                )
            except Exception as exc:
                self.log(
                    "Drive: no pude reutilizar el token existente "
                    f"({exc}). Se solicitará autorización nuevamente."
                )
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as exc:
                    self.log(
                        "Drive: no pude refrescar el token "
                        f"({exc}). Se abrirá autorización OAuth."
                    )
                    creds = None

            if not creds or not creds.valid:
                self.log(
                    "Drive: se abrirá el navegador para autorizar "
                    "el acceso por única vez."
                )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path),
                    [DRIVE_SCOPE],
                )
                creds = flow.run_local_server(port=0)

            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json(), encoding="utf-8")

        self.service = build(
            "drive",
            "v3",
            credentials=creds,
            cache_discovery=False,
        )
        return self.service

    def _get_folder(self, folder_id: str) -> dict:
        if self.service is None:
            raise RuntimeError("Google Drive no está autenticado.")

        try:
            item = self.service.files().get(
                fileId=folder_id,
                fields="id,name,mimeType,trashed",
                supportsAllDrives=True,
            ).execute()
        except TypeError:
            item = self.service.files().get(
                fileId=folder_id,
                fields="id,name,mimeType,trashed",
            ).execute()

        if item.get("trashed"):
            raise RuntimeError("La carpeta configurada de Google Drive está en la papelera.")

        if item.get("mimeType") != DRIVE_FOLDER_MIME:
            raise RuntimeError("GOOGLE_DRIVE_FOLDER_ID no apunta a una carpeta de Google Drive.")

        return item

    def _list_children(self, parent_id: str) -> list[dict]:
        if self.service is None:
            raise RuntimeError("Google Drive no está autenticado.")

        safe_parent = str(parent_id).replace("\\", "\\\\").replace("'", "\\'")
        query = f"'{safe_parent}' in parents and trashed = false"

        result = []
        token = None

        while True:
            kwargs = {
                "q": query,
                "spaces": "drive",
                "pageSize": 1000,
                "fields": "nextPageToken,files(id,name,mimeType,appProperties,trashed)",
                "pageToken": token,
            }

            try:
                response = self.service.files().list(
                    **kwargs,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute()
            except TypeError:
                response = self.service.files().list(**kwargs).execute()

            result.extend(response.get("files", []) or [])
            token = response.get("nextPageToken")
            if not token:
                break

        return result

    @staticmethod
    def _same_name(children: list[dict], name: str, mime_type: str | None = None) -> list[dict]:
        matches = [item for item in children if item.get("name") == name]
        if mime_type is not None:
            matches = [item for item in matches if item.get("mimeType") == mime_type]
        return matches

    def _ensure_folder(self, parent_id: str, name: str) -> tuple[str, bool]:
        children = self._list_children(parent_id)
        matches = self._same_name(children, name, DRIVE_FOLDER_MIME)

        if matches:
            return str(matches[0]["id"]), False

        metadata = {
            "name": name,
            "mimeType": DRIVE_FOLDER_MIME,
            "parents": [parent_id],
            "appProperties": DRIVE_APP_PROPERTIES,
        }

        try:
            folder = self.service.files().create(
                body=metadata,
                fields="id,name",
                supportsAllDrives=True,
            ).execute()
        except TypeError:
            folder = self.service.files().create(
                body=metadata,
                fields="id,name",
            ).execute()

        return str(folder["id"]), True

    def _upload_or_update_file(
        self,
        local_path: Path,
        parent_id: str,
        children: list[dict],
    ) -> str:
        if not local_path.exists() or not local_path.is_file():
            raise FileNotFoundError(f"No existe el archivo local: {local_path}")

        _, _, _, _, MediaFileUpload = self._load_google_libraries()

        mime = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        media = MediaFileUpload(str(local_path), mimetype=mime, resumable=True)

        matches = self._same_name(children, local_path.name)
        body = {
            "name": local_path.name,
            "appProperties": DRIVE_APP_PROPERTIES,
        }

        if matches:
            target = matches[0]
            try:
                self.service.files().update(
                    fileId=target["id"],
                    body=body,
                    media_body=media,
                    fields="id,name",
                    supportsAllDrives=True,
                ).execute()
            except TypeError:
                self.service.files().update(
                    fileId=target["id"],
                    body=body,
                    media_body=media,
                    fields="id,name",
                ).execute()

            return "updated"

        metadata = {
            **body,
            "parents": [parent_id],
        }

        try:
            self.service.files().create(
                body=metadata,
                media_body=media,
                fields="id,name",
                supportsAllDrives=True,
            ).execute()
        except TypeError:
            self.service.files().create(
                body=metadata,
                media_body=media,
                fields="id,name",
            ).execute()

        return "uploaded"

    def upload_results(
        self,
        module_name: str,
        local_paths: list[Path],
    ) -> dict:
        result = {
            "enabled": self.enabled,
            "attempted": False,
            "ok": False,
            "skipped": False,
            "message": "",
            "remote_folder_name": "",
            "uploaded": 0,
            "updated": 0,
        }

        if not self.enabled:
            result["skipped"] = True
            result["message"] = "Google Drive está deshabilitado."
            return result

        if not self.parent_folder_id:
            result["skipped"] = True
            result["message"] = "No se configuró GOOGLE_DRIVE_FOLDER_ID."
            self.log(
                "Drive: omitido. Falta GOOGLE_DRIVE_FOLDER_ID "
                "o GOOGLE_DRIVE_FOLDER_URL en .env."
            )
            return result

        files = []
        seen = set()

        for path in local_paths:
            p = Path(path)
            if not p.exists() or not p.is_file():
                continue
            if p.suffix.lower() not in {".pdf", ".mp4", ".txt"}:
                continue

            key = str(p.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            files.append(p)

        if not files:
            result["skipped"] = True
            result["message"] = "No hay archivos finales nuevos para subir."
            self.log("Drive: no hay archivos finales de esta ejecución para subir.")
            return result

        result["attempted"] = True

        try:
            self.log("Drive: autenticando...")
            self._authenticate()

            parent = self._get_folder(self.parent_folder_id)
            remote_module_name = safe_name(module_name, "Sin_modulo")

            module_folder_id, created = self._ensure_folder(
                self.parent_folder_id,
                remote_module_name,
            )

            result["remote_folder_name"] = (
                f"{parent.get('name', 'Drive')} / {remote_module_name}"
            )

            if created:
                self.log(f"Drive: carpeta del módulo creada: {remote_module_name}")
            else:
                self.log(f"Drive: reutilizando carpeta del módulo: {remote_module_name}")

            children = self._list_children(module_folder_id)

            for index, local_file in enumerate(files, start=1):
                size_mb = local_file.stat().st_size / (1024 * 1024)
                self.log(
                    f"Drive ({index}/{len(files)}): {local_file.name} ({size_mb:.1f} MB)"
                )

                action = self._upload_or_update_file(
                    local_file,
                    module_folder_id,
                    children,
                )

                if action == "updated":
                    result["updated"] += 1
                    self.log(f"Drive: actualizado: {local_file.name}")
                else:
                    result["uploaded"] += 1
                    self.log(f"Drive: subido: {local_file.name}")
                    children.append({
                        "name": local_file.name,
                        "mimeType": mimetypes.guess_type(local_file.name)[0]
                        or "application/octet-stream",
                    })

            result["ok"] = True
            result["message"] = "Subida a Google Drive completada."
            self.log(
                "Drive: OK | "
                f"nuevos={result['uploaded']} | "
                f"actualizados={result['updated']} | "
                f"carpeta={result['remote_folder_name']}"
            )

        except Exception as exc:
            result["ok"] = False
            result["message"] = str(exc)
            self.log(
                "Drive: ERROR. Los archivos locales quedaron "
                f"guardados correctamente. Detalle: {exc}"
            )

        return result

