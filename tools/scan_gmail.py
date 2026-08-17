import base64
import json
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.address_validators import filter_valid_addresses
from config.analysis import CRYPTO_PATTERNS
from config.search import WALLET_EXTENSIONS, WALLET_KEYWORDS
from web.vault import add_vault_entry, list_vault_entries, resolve_vault_entries_with_values, revoke_vault_entry

# Read-only scope -- this tool never modifies, labels, or deletes anything
# in Gmail.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# The OAuth client id/secret AND the resulting refresh token all live in
# the vault (Portunus) -- never as a plaintext credentials.json/token.json
# on disk, unlike the older scan_google_drive.py adapter. Same pattern
# web/rclone_wizard.py's create_remote() already uses for the Drive-mount
# OAuth flow: add_vault_entry()/resolve_vault_entries_with_values(), a
# temp file only for the instant add_vault_entry needs one, never a CLI
# argument, never logged.
CLIENT_ID_VAULT_NAME = "gmail-oauth-client-id"
CLIENT_SECRET_VAULT_NAME = "gmail-oauth-client-secret"
TOKEN_VAULT_NAME = "gmail-oauth-token"

DEFAULT_PAGE_DELAY_SECONDS = 1  # gentle on API quota, not a race

# Categories that tend to surface exchange signup/withdrawal emails, an
# old web-wallet mention, or a wallet.dat/backup attachment someone
# emailed themselves years ago. Broad on purpose -- a human reviews the
# results, this is a net, not a filter.
DEFAULT_QUERIES = [
    'blockchain OR "bitcoin address" OR wallet.dat OR "private key" OR "seed phrase" OR "recovery phrase"',
    "from:(coinbase.com OR bitstamp.net OR blockchain.com OR blockchain.info OR kraken.com OR bittrex.com OR mtgox.com OR cryptsy.com OR btc-e.com)",
    "subject:(withdrawal OR payout OR deposit OR confirmation) (bitcoin OR btc OR crypto OR wallet)",
    'has:attachment (wallet OR backup OR "private key" OR wallet.dat)',
]


def _looks_like_google_client_id(client_id):
    """Same check as web/rclone_wizard.py's -- a real Google OAuth client ID always ends in this suffix."""
    return client_id.endswith(".apps.googleusercontent.com")


def _store_secret(vault_name, value, description):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(value)
        path = f.name
    try:
        add_vault_entry(vault_name, path, description=description)
    finally:
        Path(path).unlink(missing_ok=True)


def is_gmail_bound():
    return TOKEN_VAULT_NAME in {e["name"] for e in list_vault_entries()}


def unbind_gmail_account():
    """Revokes the vault entries this adapter created -- Portunus's own soft-delete, consistent with every other vault entry in this project."""
    for name in (CLIENT_ID_VAULT_NAME, CLIENT_SECRET_VAULT_NAME, TOKEN_VAULT_NAME):
        revoke_vault_entry(name)


def bind_gmail_account(client_id, client_secret, progress_callback=None):
    """
    One-time setup: stores the Google OAuth client id/secret in the vault,
    runs the real OAuth consent flow (opens a browser -- same
    "installed app" flow scan_google_drive.py uses), and stores the
    resulting refresh token in the vault too. Nothing here ever writes a
    plaintext credentials.json/token.json to disk.

    :param client_id: from Google Cloud Console -- must look like a real
        OAuth client id (ends in .apps.googleusercontent.com).
    :param client_secret: paired with client_id.
    :param progress_callback: optional callable(current, total, message).
    :return: {"ok": bool, "report": str}
    """
    if progress_callback is None:
        progress_callback = lambda current, total, message="": None

    if not _looks_like_google_client_id(client_id):
        return {
            "ok": False,
            "report": (
                f"'{client_id}' doesn't look like a real Google OAuth client ID -- those always end in "
                '".apps.googleusercontent.com" (get the real value from Google Cloud Console).'
            ),
        }

    from google_auth_oauthlib.flow import InstalledAppFlow

    progress_callback(1, 3, "Storing your Google OAuth client credentials in the vault")
    _store_secret(CLIENT_ID_VAULT_NAME, client_id, "Gmail OAuth client id")
    _store_secret(CLIENT_SECRET_VAULT_NAME, client_secret, "Gmail OAuth client secret")

    progress_callback(2, 3, "Opening your browser to sign in to Google -- approve read-only Gmail access there, this will finish automatically")
    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
        SCOPES,
    )
    try:
        creds = flow.run_local_server(port=0)
    except Exception as e:
        unbind_gmail_account()
        return {"ok": False, "report": f"Google sign-in did not complete: {e}. Nothing was saved -- try again."}

    progress_callback(3, 3, "Saving your Gmail access token in the vault")
    _store_secret(TOKEN_VAULT_NAME, creds.to_json(), "Gmail OAuth refresh token")

    return {"ok": True, "report": "Connected -- Gmail is ready to search."}


def get_gmail_service():
    """
    Resolves the bound OAuth credentials from the vault and builds an
    authenticated, read-only Gmail API client. Refreshes (and re-stores)
    the token if it's expired -- same as scan_google_drive.py's
    get_drive_service() does for its file-based token.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not is_gmail_bound():
        raise RuntimeError("Gmail isn't connected yet -- connect it first.")

    [(_, token_json)] = resolve_vault_entries_with_values([TOKEN_VAULT_NAME])
    creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)

    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _store_secret(TOKEN_VAULT_NAME, creds.to_json(), "Gmail OAuth refresh token")

    return build("gmail", "v1", credentials=creds)


def search_message_ids(service, query, max_results=200, page_delay_seconds=DEFAULT_PAGE_DELAY_SECONDS):
    """Paginated message-ID search for one Gmail search query. IDs only -- no content, same as Drive's file listing."""
    ids = []
    page_token = None
    while True:
        response = (
            service.users()
            .messages()
            .list(userId="me", q=query, pageToken=page_token, maxResults=min(100, max_results - len(ids)))
            .execute()
        )
        ids.extend(m["id"] for m in response.get("messages", []))
        page_token = response.get("nextPageToken")
        if not page_token or len(ids) >= max_results:
            break
        time.sleep(page_delay_seconds)
    return ids[:max_results]


def _decode_part_body(data):
    if not data:
        return ""
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(errors="ignore")


def _extract_plain_text(payload):
    """
    Walks a Gmail API message payload for its text content -- entirely
    local. The decoded text is never returned as-is to a caller outside
    this module; only regex-matched addresses (find_addresses_in_payload)
    ever leave this function's scope.
    """
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    if mime_type == "text/plain" and body_data:
        return _decode_part_body(body_data)

    plain_parts, html_parts = [], []
    for part in payload.get("parts") or []:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            plain_parts.append(_decode_part_body(part["body"]["data"]))
        elif part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            html_parts.append(_decode_part_body(part["body"]["data"]))
        elif part.get("parts"):
            nested = _extract_plain_text(part)
            if nested:
                plain_parts.append(nested)

    if plain_parts:
        return "\n".join(plain_parts)
    if html_parts:
        return re.sub(r"<[^>]+>", " ", "\n".join(html_parts))
    return ""


def _headers_dict(payload):
    return {h["name"]: h["value"] for h in payload.get("headers", [])}


def find_addresses_in_payload(payload):
    """
    Regex-matches known cryptocurrency address patterns (the same
    CRYPTO_PATTERNS every other tool here uses) against the message body.
    Every raw match is filtered through that coin's offline checksum
    validator (config/address_validators.py) before it's included below
    -- the same filter tools/analyze_wallets.py's analyze_wallet_file()
    applies, so a shape-only false positive can't slip through this
    independent, Gmail-sourced path either. Returns only the matched
    addresses -- public identifiers, safe to display same as everywhere
    else in this project -- never the surrounding email text.
    """
    body_text = _extract_plain_text(payload)
    found = {}
    for crypto, pattern in CRYPTO_PATTERNS.items():
        matches = filter_valid_addresses(crypto, re.findall(pattern, body_text))
        if matches:
            found[crypto] = sorted(set(matches))
    return found


def _is_wallet_like_attachment(filename):
    lower = filename.lower()
    if any(lower.endswith(ext) for ext in WALLET_EXTENSIONS):
        return True
    if any(keyword in lower for keyword in WALLET_KEYWORDS):
        return True
    return False


def save_wallet_like_attachments(service, msg_id, payload, output_dir):
    """Downloads any attachment whose filename looks wallet-like straight to local disk -- attachment bytes never pass through this function's return value."""
    saved = []

    def _walk(parts):
        for part in parts:
            filename = part.get("filename") or ""
            body = part.get("body", {})
            if filename and _is_wallet_like_attachment(filename):
                attachment_id = body.get("attachmentId")
                if attachment_id:
                    attachment = (
                        service.users().messages().attachments().get(userId="me", messageId=msg_id, id=attachment_id).execute()
                    )
                    data = base64.urlsafe_b64decode(attachment["data"] + "=" * (-len(attachment["data"]) % 4))
                    dest = Path(output_dir) / f"{msg_id}_{filename}"
                    dest.write_bytes(data)
                    saved.append(str(dest))
            if part.get("parts"):
                _walk(part["parts"])

    _walk(payload.get("parts") or [])
    return saved


def scan_gmail_for_wallet_clues(output_dir, queries=None, max_results_per_query=200, progress_callback=None):
    """
    Full pass: search every query, and for each distinct matching message
    -- one API fetch, format=full -- pull From/Subject/Date, regex-matched
    addresses, and any wallet-like attachment (saved under output_dir).
    Writes one summary JSON to output_dir/gmail_scan_results.json. This is
    the only function most callers need.

    :param progress_callback: optional callable(current, total, message).
    """
    queries = queries or DEFAULT_QUERIES
    service = get_gmail_service()

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    attachments_dir = Path(output_dir) / "attachments"
    attachments_dir.mkdir(exist_ok=True)

    if progress_callback is None:
        progress_callback = lambda current, total, message="": None

    message_ids = set()
    for query in queries:
        message_ids.update(search_message_ids(service, query, max_results=max_results_per_query))

    results = []
    total = len(message_ids)
    for i, msg_id in enumerate(sorted(message_ids), start=1):
        message = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        payload = message.get("payload", {})
        headers = _headers_dict(payload)

        summary = {
            "id": msg_id,
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "addresses": find_addresses_in_payload(payload),
            "attachments_saved": save_wallet_like_attachments(service, msg_id, payload, attachments_dir),
        }
        results.append(summary)
        progress_callback(i, total, summary["subject"])

    output_file = Path(output_dir) / "gmail_scan_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Gmail scan complete. {total} matching message(s) found. Results saved to {output_file}.")
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Search Gmail (bound via the vault) for wallet/exchange-related emails and attachments.")
    parser.add_argument("output_dir", help="Directory to write results (and any downloaded attachments) to.")
    parser.add_argument("--query", action="append", dest="queries", help="Gmail search query -- may be given multiple times. Defaults to a built-in set covering exchanges, wallet mentions, and wallet-like attachments.")
    parser.add_argument("--max-results", type=int, default=200, help="Max messages to fetch per query.")
    args = parser.parse_args()

    scan_gmail_for_wallet_clues(args.output_dir, queries=args.queries, max_results_per_query=args.max_results)
