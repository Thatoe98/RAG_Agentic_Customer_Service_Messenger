import io
import json
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from config import GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_DRIVE_FOLDER_ID

_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_MAX_TEXT_BYTES = 8000


def _get_service():
    if os.path.isfile(GOOGLE_SERVICE_ACCOUNT_JSON):
        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_JSON, scopes=_SCOPES
        )
    else:
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=_SCOPES
        )
    return build("drive", "v3", credentials=creds)


def search_and_read(query: str, max_results: int = 3) -> str:
    """Search Google Drive for documents matching query and return their text."""
    service = _get_service()

    safe_query = query.replace("'", "\\'")
    q_parts = [f"fullText contains '{safe_query}'", "trashed = false"]
    if GOOGLE_DRIVE_FOLDER_ID:
        q_parts.append(f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents")

    results = (
        service.files()
        .list(
            q=" and ".join(q_parts),
            pageSize=max_results,
            fields="files(id, name, mimeType)",
        )
        .execute()
    )

    files = results.get("files", [])
    if not files:
        return "No relevant documents found in company Drive."

    chunks = []
    for f in files:
        content = _read_file(service, f["id"], f["mimeType"], f["name"])
        if content:
            chunks.append(f"[{f['name']}]\n{content}")

    return "\n\n".join(chunks) if chunks else "Documents found but could not be read."


def _read_file(service, file_id: str, mime_type: str, name: str) -> str:
    try:
        if mime_type == "application/vnd.google-apps.document":
            data = service.files().export(fileId=file_id, mimeType="text/plain").execute()
            text = data.decode("utf-8") if isinstance(data, bytes) else str(data)
            return text[:_MAX_TEXT_BYTES]

        if mime_type == "application/vnd.google-apps.spreadsheet":
            data = service.files().export(fileId=file_id, mimeType="text/csv").execute()
            text = data.decode("utf-8") if isinstance(data, bytes) else str(data)
            return text[:_MAX_TEXT_BYTES]

        if mime_type == "text/plain":
            request = service.files().get_media(fileId=file_id)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return buf.getvalue().decode("utf-8", errors="ignore")[:_MAX_TEXT_BYTES]

    except Exception as e:
        return f"[Could not read {name}: {e}]"

    return ""
