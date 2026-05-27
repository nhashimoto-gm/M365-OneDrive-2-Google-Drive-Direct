import io
import logging
import time

import msal
import requests

from config import (
    CLIENT_ID, CLIENT_SECRET, DOWNLOAD_CHUNK_BYTES,
    GRAPH_BASE_URL, GRAPH_SCOPES, TENANT_ID,
)

log = logging.getLogger(__name__)


class M365Client:
    def __init__(self):
        self._app = msal.ConfidentialClientApplication(
            CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{TENANT_ID}",
            client_credential=CLIENT_SECRET,
        )
        self._token: str | None = None

    def _refresh_token(self) -> str:
        result = self._app.acquire_token_for_client(scopes=GRAPH_SCOPES)
        if "access_token" not in result:
            raise RuntimeError(f"M365 token failed: {result.get('error_description', result)}")
        return result["access_token"]

    def _headers(self) -> dict:
        if not self._token:
            self._token = self._refresh_token()
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, url: str, **kwargs) -> requests.Response:
        for attempt in range(5):
            try:
                resp = requests.get(url, headers=self._headers(), timeout=120, **kwargs)
                if resp.status_code == 401:
                    self._token = self._refresh_token()
                    resp = requests.get(url, headers=self._headers(), timeout=120, **kwargs)
                resp.raise_for_status()
                return resp
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                if attempt == 4:
                    raise
                wait = min(2 ** (attempt + 1), 60)
                log.warning("M365 API error (%s), retry %d/5 in %ds...", e, attempt + 1, wait)
                time.sleep(wait)

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def list_users(self, target_emails: list[str] | None = None) -> list[dict]:
        url = f"{GRAPH_BASE_URL}/users?$select=id,displayName,userPrincipalName&$top=999"
        users: list[dict] = []
        while url:
            data = self._get(url).json()
            users.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        if target_emails:
            target_set = {e.lower() for e in target_emails}
            users = [u for u in users if u["userPrincipalName"].lower() in target_set]
        log.info("Listed %d users from M365", len(users))
        return users

    # ------------------------------------------------------------------
    # OneDrive enumeration
    # ------------------------------------------------------------------

    def list_drive_items(self, user_id: str) -> list[dict]:
        return self._walk_folder(user_id, "root", "")

    def _walk_folder(self, user_id: str, item_id: str, path_prefix: str) -> list[dict]:
        url = (
            f"{GRAPH_BASE_URL}/users/{user_id}/drive/items/{item_id}/children"
            "?$select=id,name,size,file,folder,parentReference,file"
            "&$top=200"
        )
        files: list[dict] = []
        while url:
            data = self._get(url).json()
            for item in data.get("value", []):
                rel_path = f"{path_prefix}/{item['name']}" if path_prefix else item["name"]
                if "folder" in item:
                    files.extend(self._walk_folder(user_id, item["id"], rel_path))
                else:
                    item["_rel_path"] = rel_path
                    item["_folder_path"] = path_prefix
                    files.append(item)
            url = data.get("@odata.nextLink")
        return files

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download(self, user_id: str, item_id: str) -> bytes:
        """Download file into memory with retry. Use for files < LARGE_FILE_THRESHOLD."""
        url = f"{GRAPH_BASE_URL}/users/{user_id}/drive/items/{item_id}/content"
        for attempt in range(5):
            try:
                resp = requests.get(
                    url, headers=self._headers(), stream=True,
                    timeout=(30, 120), allow_redirects=True,
                )
                if resp.status_code == 401:
                    self._token = self._refresh_token()
                    resp = requests.get(
                        url, headers=self._headers(), stream=True,
                        timeout=(30, 120), allow_redirects=True,
                    )
                resp.raise_for_status()
                buf = io.BytesIO()
                for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                    buf.write(chunk)
                return buf.getvalue()
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.HTTPError,
            ) as e:
                if attempt == 4:
                    raise
                wait = min(2 ** (attempt + 1), 60)
                log.warning("Download error (%s), retry %d/5 in %ds...", e, attempt + 1, wait)
                time.sleep(wait)

    def download_to_file(self, user_id: str, item_id: str, dest_path) -> int:
        """Stream download to a file path. Use for large files."""
        url = f"{GRAPH_BASE_URL}/users/{user_id}/drive/items/{item_id}/content"
        for attempt in range(5):
            try:
                resp = requests.get(
                    url, headers=self._headers(), stream=True,
                    timeout=(30, 120), allow_redirects=True,
                )
                if resp.status_code == 401:
                    self._token = self._refresh_token()
                    resp = requests.get(
                        url, headers=self._headers(), stream=True,
                        timeout=(30, 120), allow_redirects=True,
                    )
                resp.raise_for_status()
                total = 0
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                        f.write(chunk)
                        total += len(chunk)
                return total
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.HTTPError,
            ) as e:
                if attempt == 4:
                    raise
                wait = min(2 ** (attempt + 1), 60)
                log.warning("Download error (%s), retry %d/5 in %ds...", e, attempt + 1, wait)
                time.sleep(wait)
