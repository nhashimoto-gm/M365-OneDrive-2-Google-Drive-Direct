import io
import logging
import mimetypes
import socket
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

from config import (
    GDRIVE_CREDENTIALS_FILE,
    GDRIVE_TOKEN_FILE,
    GDRIVE_UPLOAD_CHUNK_BYTES,
)

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]


class GDriveClient:
    def __init__(self):
        self.service = self._build_service()
        self._folder_cache: dict[tuple, str] = {}

    def _build_service(self):
        creds: Credentials | None = None
        if GDRIVE_TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(str(GDRIVE_TOKEN_FILE), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(GDRIVE_CREDENTIALS_FILE), SCOPES
                )
                creds = flow.run_local_server(port=0)
            GDRIVE_TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    # ------------------------------------------------------------------
    # Folder management
    # ------------------------------------------------------------------

    def get_or_create_folder(self, name: str, parent_id: str | None = None) -> str:
        key = (name, parent_id or "")
        if key in self._folder_cache:
            return self._folder_cache[key]

        query = (
            f"name='{name}'"
            " and mimeType='application/vnd.google-apps.folder'"
            " and trashed=false"
        )
        if parent_id:
            query += f" and '{parent_id}' in parents"

        results = self.service.files().list(q=query, fields="files(id)", pageSize=1).execute()
        existing = results.get("files", [])
        if existing:
            folder_id = existing[0]["id"]
        else:
            meta: dict = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
            if parent_id:
                meta["parents"] = [parent_id]
            folder_id = self.service.files().create(body=meta, fields="id").execute()["id"]
            log.debug("Created folder '%s' (%s)", name, folder_id)

        self._folder_cache[key] = folder_id
        return folder_id

    def get_or_create_folder_path(self, folder_path: str, root_id: str | None = None) -> str:
        """Create nested folders and return the leaf folder ID."""
        parts = [p for p in folder_path.replace("\\", "/").split("/") if p]
        current_id = root_id
        for part in parts:
            current_id = self.get_or_create_folder(part, current_id)
        return current_id

    # ------------------------------------------------------------------
    # File existence check
    # ------------------------------------------------------------------

    def file_exists(self, name: str, parent_id: str) -> bool:
        safe_name = name.replace("'", "\\'")
        query = f"name='{safe_name}' and '{parent_id}' in parents and trashed=false"
        results = self.service.files().list(q=query, fields="files(id)", pageSize=1).execute()
        return bool(results.get("files"))

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload_bytes(
        self, data: bytes, filename: str, parent_id: str, mime_type: str = "application/octet-stream"
    ) -> str:
        """Upload in-memory bytes to Google Drive."""
        buf = io.BytesIO(data)
        media = MediaIoBaseUpload(
            buf, mimetype=mime_type, chunksize=GDRIVE_UPLOAD_CHUNK_BYTES, resumable=True
        )
        return self._do_upload(filename, parent_id, media)

    def upload_file(
        self, local_path: Path, filename: str, parent_id: str, mime_type: str = "application/octet-stream"
    ) -> str:
        """Upload a local file to Google Drive."""
        media = MediaFileUpload(
            str(local_path), mimetype=mime_type,
            chunksize=GDRIVE_UPLOAD_CHUNK_BYTES, resumable=True,
        )
        return self._do_upload(filename, parent_id, media)

    def _do_upload(self, filename: str, parent_id: str, media) -> str:
        meta = {"name": filename, "parents": [parent_id]}
        request = self.service.files().create(body=meta, media_body=media, fields="id")
        response = None
        max_retries = 10
        retry = 0
        while response is None:
            try:
                _, response = request.next_chunk()
                retry = 0
            except (ConnectionResetError, ConnectionError, socket.error, OSError) as e:
                retry += 1
                if retry > max_retries:
                    raise
                wait = min(2 ** retry, 120)
                log.warning("Upload error (%s), retry %d/%d in %ds...", e, retry, max_retries, wait)
                time.sleep(wait)
        return response["id"]

    # ------------------------------------------------------------------
    # MIME type helper
    # ------------------------------------------------------------------

    @staticmethod
    def guess_mime(filename: str) -> str:
        mime, _ = mimetypes.guess_type(filename)
        return mime or "application/octet-stream"
