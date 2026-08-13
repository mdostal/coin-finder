import os
import sys
import time
from pathlib import Path

from googleapiclient.http import MediaIoBaseDownload

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.search import COIN_NAMES, MAX_FILE_SIZE, MIN_FILE_SIZE, WALLET_EXTENSIONS, WALLET_KEYWORDS

# Read-only scope -- this tool never modifies or deletes anything in Drive.
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DEFAULT_CREDENTIALS_PATH = "credentials.json"  # user-provided OAuth client secret (gitignored)
DEFAULT_TOKEN_PATH = "token.json"  # cached OAuth token, written after first consent (gitignored)
DEFAULT_PAGE_DELAY_SECONDS = 1  # "slow crawl" -- gentle on API quota, not a race


def is_wallet_like_filename(filename):
    """Same extension/keyword/coin-name heuristic as tools/search_wallets.py, applied to a Drive filename."""
    lower = filename.lower()
    if any(lower.endswith(ext) for ext in WALLET_EXTENSIONS):
        return True
    if any(coin_name in lower for coin_name in COIN_NAMES):
        return True
    if any(keyword in lower for keyword in WALLET_KEYWORDS):
        return True
    return False


def get_drive_service(credentials_path=DEFAULT_CREDENTIALS_PATH, token_path=DEFAULT_TOKEN_PATH):
    """
    OAuth "installed app" flow (standard for a local script, not a web
    server): opens a browser for consent the first time, caches the token
    locally afterward. Requires the user's own Google Cloud OAuth client
    credentials -- see README.md for setup (this project cannot create
    those on the user's behalf).
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                raise RuntimeError(
                    f"No OAuth credentials found at {credentials_path}. "
                    "See README.md's Google Drive Scanner section for setup instructions."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def list_wallet_like_files(service, query=None, page_size=100, page_delay_seconds=DEFAULT_PAGE_DELAY_SECONDS):
    """
    Paginated, rate-limited ("slow crawl") listing of Drive files, filtered
    to wallet-like filenames and a plausible size range -- metadata only, no
    file content is read here. Native Google Docs/Sheets/Slides are skipped
    (they aren't downloadable "files" in the same sense -- a doc containing
    wallet notes should be reviewed by the user directly in Drive, not
    auto-downloaded).
    """
    results = []
    page_token = None
    base_query = query or "trashed = false"

    while True:
        response = (
            service.files()
            .list(
                q=base_query,
                pageSize=page_size,
                fields="nextPageToken, files(id, name, size, mimeType, modifiedTime)",
                pageToken=page_token,
            )
            .execute()
        )

        for file in response.get("files", []):
            if file.get("mimeType", "").startswith("application/vnd.google-apps"):
                continue
            size = int(file.get("size", 0) or 0)
            if size > MAX_FILE_SIZE or size < MIN_FILE_SIZE:
                continue
            if is_wallet_like_filename(file.get("name", "")):
                results.append(file)

        page_token = response.get("nextPageToken")
        if not page_token:
            break
        time.sleep(page_delay_seconds)

    return results


def download_file(service, file_id, destination_path):
    """
    Downloads a Drive file's content directly to local disk via the Drive
    API's media download. Content flows from Google's servers into this
    local file -- never through any AI-model context or chat transcript.
    """
    request = service.files().get_media(fileId=file_id)
    with open(destination_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def scan_drive_for_wallets(service, output_dir, query=None):
    """
    "Slow crawl": lists wallet-like files (metadata only), downloads each
    directly to output_dir. Does NOT read or interpret file content itself
    -- run the existing local tools (search_wallets.py, find_seed_phrases.py,
    scan_wallet_dat.py, etc.) against output_dir afterward, exactly as you
    would for a local drive.

    :return: [{"drive_file_id", "name", "local_path"}, ...]
    """
    os.makedirs(output_dir, exist_ok=True)
    candidates = list_wallet_like_files(service, query=query)

    manifest = []
    for file in candidates:
        local_path = os.path.join(output_dir, f"{file['id']}_{file['name']}")
        download_file(service, file["id"], local_path)
        manifest.append({"drive_file_id": file["id"], "name": file["name"], "local_path": local_path})

    return manifest


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Slow-crawl Google Drive for wallet-like files and download them locally "
        "(run the other tools in this project against the output directory afterward)."
    )
    parser.add_argument("output_dir", help="Local directory to download candidate files into.")
    parser.add_argument("--query", help="Optional Drive API query to narrow the search (default: all non-trashed files).")
    parser.add_argument("--credentials", default=DEFAULT_CREDENTIALS_PATH, help=f"Path to OAuth client credentials (default: {DEFAULT_CREDENTIALS_PATH}).")
    parser.add_argument("--token", default=DEFAULT_TOKEN_PATH, help=f"Path to cache the OAuth token (default: {DEFAULT_TOKEN_PATH}).")
    args = parser.parse_args()

    service = get_drive_service(credentials_path=args.credentials, token_path=args.token)
    manifest = scan_drive_for_wallets(service, args.output_dir, query=args.query)

    manifest_path = os.path.join(args.output_dir, "_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=4)

    print(f"Downloaded {len(manifest)} candidate file(s) to {args.output_dir}. Manifest: {manifest_path}.")
    print("Run search_wallets.py / find_seed_phrases.py / scan_wallet_dat.py against this directory next.")
