from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


class GmailConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class GmailAccount:
    name: str
    user_id: str
    credentials_path: Path
    token_path: Path


def _backend_dir() -> Path:
    # backend/app/email/gmail_config.py -> backend/
    return Path(__file__).resolve().parents[2]


def _resolve_path(p: str) -> Path:
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = (_backend_dir() / path).resolve()
    else:
        path = path.resolve()
    return path


def load_gmail_accounts() -> dict[str, GmailAccount]:
    """
    Load Gmail account configs from environment.

    Supported env vars:
    - OCHRE_GMAIL_ACCOUNTS: JSON list of objects:
        [{"name":"gmail","userId":"me","credentialsPath":"...","tokenPath":"..."}]
    - OR single-account fallback:
        OCHRE_GMAIL_ACCOUNT_NAME (default "gmail")
        OCHRE_GMAIL_USER_ID (default "me")
        OCHRE_GMAIL_CREDENTIALS_PATH
        OCHRE_GMAIL_TOKEN_PATH
    """
    raw = os.environ.get("OCHRE_GMAIL_ACCOUNTS")
    if raw:
        try:
            data = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            raise GmailConfigError(f"OCHRE_GMAIL_ACCOUNTS is not valid JSON: {e}") from e
        if not isinstance(data, list):
            raise GmailConfigError("OCHRE_GMAIL_ACCOUNTS must be a JSON list")
        out: dict[str, GmailAccount] = {}
        for idx, item in enumerate(data):
            if not isinstance(item, dict):
                raise GmailConfigError(f"OCHRE_GMAIL_ACCOUNTS[{idx}] must be an object")
            name = str(item.get("name") or "").strip()
            if not name:
                raise GmailConfigError(f"OCHRE_GMAIL_ACCOUNTS[{idx}].name is required")
            user_id = str(item.get("userId") or "me").strip() or "me"
            cred = str(item.get("credentialsPath") or "").strip()
            tok = str(item.get("tokenPath") or "").strip()
            if not cred or not tok:
                raise GmailConfigError(
                    f"OCHRE_GMAIL_ACCOUNTS[{idx}] requires credentialsPath and tokenPath"
                )
            out[name] = GmailAccount(
                name=name,
                user_id=user_id,
                credentials_path=_resolve_path(cred),
                token_path=_resolve_path(tok),
            )
        return out

    # single-account fallback
    name = os.environ.get("OCHRE_GMAIL_ACCOUNT_NAME", "gmail").strip() or "gmail"
    user_id = os.environ.get("OCHRE_GMAIL_USER_ID", "me").strip() or "me"
    cred = (os.environ.get("OCHRE_GMAIL_CREDENTIALS_PATH") or "").strip()
    tok = (os.environ.get("OCHRE_GMAIL_TOKEN_PATH") or "").strip()
    if not cred or not tok:
        return {}
    acct = GmailAccount(
        name=name,
        user_id=user_id,
        credentials_path=_resolve_path(cred),
        token_path=_resolve_path(tok),
    )
    return {acct.name: acct}

