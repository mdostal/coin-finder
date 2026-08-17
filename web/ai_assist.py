import tempfile
from pathlib import Path

import requests

from web.vault import add_vault_entry, list_vault_entries, resolve_vault_entries_with_values, revoke_vault_entry

# Bring-your-own-key, deliberately: this project ships no API key of its
# own and never will (see coin-finder's whole reason for existing -- a
# personal recovery tool, not a hosted service). The key is only ever used
# for this one wizard's "explain this step" panel; it is stored in the
# same vault (Portunus, or its local fallback) as every other secret this
# project touches, never in plaintext in this project's own state.
VAULT_KEY_NAME = "ai-assist-api-key"

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-sonnet-5"
MAX_TOKENS = 1024
# LLM calls can genuinely take longer than this project's usual 15s
# balance-check timeout (services/__init__.py's REQUEST_TIMEOUT_SECONDS) --
# a real model response, not a lookup against a cheap public API.
LLM_REQUEST_TIMEOUT_SECONDS = 60

SYSTEM_PROMPT = (
    "You are helping a non-technical user set up an rclone remote for "
    "Google Drive (or Google Cloud Storage) inside a desktop app called "
    "coin-finder, which mounts the drive read-only to scan it for old "
    "cryptocurrency wallet files. Answer only questions about this setup "
    "step: rclone remotes, OAuth scopes, and Google Cloud client "
    "id/secret creation (https://rclone.org/drive/#making-your-own-client-id). "
    "Keep answers short and concrete -- a couple of sentences or a short "
    "numbered list, never a wall of text. Never ask for or refer to a "
    "wallet password, private key, or seed phrase; that is a wholly "
    "separate, deliberately offline part of this app and out of scope "
    "for this wizard."
)


def has_api_key():
    return any(e["name"] == VAULT_KEY_NAME and e.get("state") != "revoked" for e in list_vault_entries())


def set_api_key(value):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(value)
        key_path = f.name
    try:
        add_vault_entry(VAULT_KEY_NAME, key_path, description="Anthropic API key for the setup wizard's AI assist panel (bring-your-own-key)")
    finally:
        Path(key_path).unlink(missing_ok=True)


def clear_api_key():
    revoke_vault_entry(VAULT_KEY_NAME)


def ask(question):
    """
    One-shot, stateless: no chat history, no memory across calls -- this
    is a "explain this one thing" panel, not a persistent assistant.

    :raises RuntimeError: no key stored, or the API call itself failed --
        callers show this message directly, it's written to be user-facing.
    """
    if not has_api_key():
        raise RuntimeError("No API key saved yet -- add one below first.")

    [(_, api_key)] = resolve_vault_entries_with_values([VAULT_KEY_NAME])

    response = requests.post(ANTHROPIC_API_URL, timeout=LLM_REQUEST_TIMEOUT_SECONDS,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": question}],
        },
    )
    if response.status_code != 200:
        raise RuntimeError(f"AI assist request failed ({response.status_code}): {response.text[:300]}")

    data = response.json()
    parts = [block["text"] for block in data.get("content", []) if block.get("type") == "text"]
    return "\n".join(parts).strip() or "(empty response)"
