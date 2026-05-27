import logging
from pathlib import Path

from tqdm import tqdm

import state as st
from config import (
    GDRIVE_ROOT_FOLDER_ID,
    LARGE_FILE_THRESHOLD,
    STATE_FILE,
    TARGET_USERS,
    TEMP_DIR,
)
from gdrive_client import GDriveClient
from m365_client import M365Client

log = logging.getLogger(__name__)


class Migrator:
    def __init__(self):
        log.info("Authenticating with Microsoft 365...")
        self.m365 = M365Client()
        log.info("Authenticating with Google Drive...")
        self.gdrive = GDriveClient()
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        self.state = st.load(STATE_FILE)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self):
        target = TARGET_USERS if TARGET_USERS else None
        users = self.m365.list_users(target)
        if not users:
            log.error("No users found. Check TARGET_USERS or M365 permissions.")
            return

        log.info("Starting migration for %d user(s)", len(users))
        for user in users:
            upn = user["userPrincipalName"]
            if st.is_user_done(self.state, upn):
                log.info("Skipping %s (already completed)", upn)
                continue
            try:
                self._migrate_user(user)
                st.mark_user_done(self.state, upn)
                st.save(STATE_FILE, self.state)
            except Exception:
                log.exception("Migration failed for %s — will retry next run", upn)
                st.save(STATE_FILE, self.state)

        log.info("Migration finished.")

    # ------------------------------------------------------------------
    # Per-user migration
    # ------------------------------------------------------------------

    def _migrate_user(self, user: dict):
        user_id = user["id"]
        upn = user["userPrincipalName"]
        display = user["displayName"]

        log.info("[%s] Listing OneDrive files...", upn)
        items = self.m365.list_drive_items(user_id)
        log.info("[%s] %d files found", upn, len(items))

        # ユーザーのルートフォルダを作成
        root_id = GDRIVE_ROOT_FOLDER_ID or None
        user_folder_id = self.gdrive.get_or_create_folder(upn, root_id)

        done = 0
        skipped = 0
        errors = 0

        for item in tqdm(items, desc=display, unit="file"):
            item_id = item["id"]
            filename = item["name"]
            folder_path = item.get("_folder_path", "")
            file_size = item.get("size", 0)

            if st.is_done(self.state, upn, item_id):
                skipped += 1
                continue

            try:
                # フォルダパスに対応するGDriveフォルダIDを取得
                if folder_path:
                    parent_id = self.gdrive.get_or_create_folder_path(folder_path, user_folder_id)
                else:
                    parent_id = user_folder_id

                # 同名ファイルが既にあればスキップ
                if self.gdrive.file_exists(filename, parent_id):
                    log.debug("[%s] Already exists: %s", upn, item.get("_rel_path"))
                    st.mark_done(self.state, upn, item_id)
                    skipped += 1
                    continue

                mime_type = self.gdrive.guess_mime(filename)
                self._upload_item(user_id, item_id, filename, file_size, parent_id, mime_type)

                st.mark_done(self.state, upn, item_id)
                done += 1

                if done % 50 == 0:
                    st.save(STATE_FILE, self.state)

            except Exception:
                log.exception("[%s] Failed: %s — skipping", upn, item.get("_rel_path"))
                errors += 1

        st.save(STATE_FILE, self.state)
        log.info("[%s] Done: %d uploaded, %d skipped, %d errors", upn, done, skipped, errors)

    # ------------------------------------------------------------------
    # Upload dispatcher
    # ------------------------------------------------------------------

    def _upload_item(
        self,
        user_id: str,
        item_id: str,
        filename: str,
        file_size: int,
        parent_id: str,
        mime_type: str,
    ):
        if file_size == 0:
            self.gdrive.upload_bytes(b"", filename, parent_id, mime_type)
            return

        if file_size < LARGE_FILE_THRESHOLD:
            data = self.m365.download(user_id, item_id)
            self.gdrive.upload_bytes(data, filename, parent_id, mime_type)
        else:
            tmp = TEMP_DIR / f"_tmp_{item_id}"
            try:
                self.m365.download_to_file(user_id, item_id, tmp)
                self.gdrive.upload_file(tmp, filename, parent_id, mime_type)
            finally:
                tmp.unlink(missing_ok=True)
