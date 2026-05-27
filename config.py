import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TENANT_ID = os.environ["M365_TENANT_ID"]
CLIENT_ID = os.environ["M365_CLIENT_ID"]
CLIENT_SECRET = os.environ["M365_CLIENT_SECRET"]

TARGET_USERS: list[str] = [
    u.strip() for u in os.getenv("TARGET_USERS", "").split(",") if u.strip()
]

GDRIVE_ROOT_FOLDER_ID: str = os.getenv("GDRIVE_ROOT_FOLDER_ID", "")
GDRIVE_CREDENTIALS_FILE = Path("gdrive_credentials.json")
GDRIVE_TOKEN_FILE = Path("gdrive_token.json")

TEMP_DIR = Path(os.getenv("TEMP_DIR", "./tmp"))
STATE_FILE = Path("migration_state.json")

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]

DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024    # 8MB per HTTP read
GDRIVE_UPLOAD_CHUNK_BYTES = 50 * 1024 * 1024  # 50MB per GDrive resumable chunk
LARGE_FILE_THRESHOLD = 50 * 1024 * 1024   # 50MB以上はtempファイル経由
