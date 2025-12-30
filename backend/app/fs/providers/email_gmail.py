from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any
import threading

from app.email.gmail_client import (
    GmailError,
    build_gmail_service,
    gmail_fetch_metadata_batch,
    gmail_get_message_full,
    gmail_list_labels,
    gmail_list_message_ids,
    render_message_markdown,
    summarize_metadata,
)
from app.email.gmail_config import GmailAccount, load_gmail_accounts


def _snake_slug(s: str, *, cap: int = 64) -> str:
    s = (s or "").strip()
    if not s:
        return "message"
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    out = []
    prev_us = False
    for ch in s:
        ok = ("a" <= ch <= "z") or ("0" <= ch <= "9")
        if ok:
            out.append(ch)
            prev_us = False
        else:
            if not prev_us:
                out.append("_")
                prev_us = True
    slug = "".join(out).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    if not slug:
        slug = "message"
    if cap and len(slug) > cap:
        slug = slug[:cap].rstrip("_")
    return slug or "message"


def _truncate_utf8(s: str, cap_bytes: int) -> str:
    b = s.encode("utf-8", errors="replace")
    if len(b) <= cap_bytes:
        return s
    cut = b[:cap_bytes]
    while cut:
        try:
            return cut.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            cut = cut[:-1]
    return ""


def _split(path: str) -> list[str]:
    # Keep empty out, remove leading slash.
    return [p for p in path.strip("/").split("/") if p]


def _email_rel_parts(path: str) -> list[str]:
    """
    Return path segments relative to /fs/email.
    Examples:
      /fs/email            -> []
      /fs/email/gmail      -> ["gmail"]
      /fs/email/gmail/labels -> ["gmail","labels"]
    """
    parts = _split(path)
    if len(parts) >= 2 and parts[0] == "fs" and parts[1] == "email":
        return parts[2:]
    return parts


@dataclass
class _AcctState:
    acct: GmailAccount
    service: Any


class EmailGmailProvider:
    """
    Read-only Gmail provider mounted at /fs/email.
    """

    def __init__(self) -> None:
        self._services: dict[str, _AcctState] = {}
        # Map virtual error file path -> content (for transient Gmail/network errors).
        self._error_files: dict[str, str] = {}
        # Gmail client objects are not guaranteed thread-safe; serialize per-account usage.
        self._acct_locks: dict[str, threading.Lock] = {}

    def can_handle(self, path: str) -> bool:
        return path == "/fs/email" or path == "/fs/email/" or path.startswith("/fs/email/")

    def _accounts(self) -> dict[str, GmailAccount]:
        return load_gmail_accounts()

    def _readme(self) -> str:
        return (
            "# /fs/email (Gmail, read-only)\n\n"
            "Ochre can expose Gmail mailboxes as a virtual filesystem.\n\n"
            "## Configure\n\n"
            "Set either a single account:\n\n"
            "- `OCHRE_GMAIL_CREDENTIALS_PATH`: OAuth client JSON path\n"
            "- `OCHRE_GMAIL_TOKEN_PATH`: token JSON path (created by auth script)\n"
            "- `OCHRE_GMAIL_ACCOUNT_NAME` (optional, default `gmail`)\n"
            "- `OCHRE_GMAIL_USER_ID` (optional, default `me`)\n\n"
            "Or multiple accounts:\n\n"
            "- `OCHRE_GMAIL_ACCOUNTS`: JSON list like:\n"
            "  `[{\"name\":\"gmail\",\"userId\":\"me\",\"credentialsPath\":\"...\",\"tokenPath\":\"...\"}]`\n\n"
            "## Create token\n\n"
            "1) Create an OAuth client (Desktop app) in Google Cloud Console and download the JSON.\n"
            "2) Run:\n\n"
            "```bash\n"
            "cd backend\n"
            "uv run python scripts/gmail_auth.py \\\n"
            "  --credentials data/gmail/client.json \\\n"
            "  --token data/gmail/token.json\n"
            "```\n\n"
            "Then restart the backend and browse `/fs/email`.\n"
        )

    def _state(self, name: str) -> _AcctState:
        if name in self._services:
            return self._services[name]
        accts = self._accounts()
        acct = accts.get(name)
        if acct is None:
            raise RuntimeError(f"Unknown email account: {name}")
        try:
            svc = build_gmail_service(acct)
        except GmailError as e:
            raise RuntimeError(str(e)) from e
        st = _AcctState(acct=acct, service=svc)
        self._services[name] = st
        return st

    def _reset_state(self, name: str, *, reason: str) -> None:
        self._services.pop(name, None)

    def _lock_for(self, acct: str) -> threading.Lock:
        # Best-effort; tiny race on creation is acceptable (locks are interchangeable here).
        if acct in self._acct_locks:
            return self._acct_locks[acct]
        self._acct_locks[acct] = threading.Lock()
        return self._acct_locks[acct]

    def _set_error_file(self, path: str, *, content: str) -> None:
        self._error_files[path] = content

    def _error_listing(self, dir_path: str, *, error: str) -> dict[str, Any]:
        p = dir_path.rstrip("/")
        err_path = f"{p}/ERROR.txt"
        self._set_error_file(err_path, content=error)
        return {
            "path": p,
            "entries": [{"name": "ERROR.txt", "path": err_path, "kind": "file", "size": None}],
        }

    def list(self, path: str) -> dict[str, Any]:
        p = path.rstrip("/") or "/fs/email"
        rel = _email_rel_parts(p)

        # /fs/email
        if p == "/fs/email":
            accts = self._accounts()
            entries = [{"name": "README.md", "path": "/fs/email/README.md", "kind": "file", "size": None}]
            for name in sorted(accts.keys()):
                entries.append({"name": name, "path": f"/fs/email/{name}", "kind": "dir", "size": None})
            return {"path": "/fs/email", "entries": entries}

        # /fs/email/<acct>
        if len(rel) == 1:
            acct = rel[0]
            _ = self._state(acct)  # validates config
            return {
                "path": p,
                "entries": [{"name": "labels", "path": f"/fs/email/{acct}/labels", "kind": "dir", "size": None}],
            }

        # /fs/email/<acct>/labels
        if len(rel) == 2 and rel[1] == "labels":
            acct = rel[0]
            lock = self._lock_for(acct)
            contended = lock.locked()
            if contended:
                pass
            with lock:
                st = self._state(acct)
                try:
                    labels = gmail_list_labels(st.service, user_id=st.acct.user_id)
                except GmailError as e:
                    # Transient TLS / connection corruption can happen; rebuild service once and retry.
                    self._reset_state(acct, reason=f"gmail_list_labels failed: {str(e)[:200]}")
                    st = self._state(acct)
                    try:
                        labels = gmail_list_labels(st.service, user_id=st.acct.user_id)
                    except GmailError as e2:
                        return self._error_listing(
                            p,
                            error=(
                                "Gmail labels are temporarily unavailable.\n\n"
                                f"Error: {str(e2)[:600]}\n"
                            ),
                        )
            entries = []
            for label in labels:
                lid = str(label.get("id") or "").strip()
                lname = str(label.get("name") or "").strip() or lid
                if not lid:
                    continue
                entries.append(
                    {"name": lname, "path": f"/fs/email/{acct}/labels/{lid}", "kind": "dir", "size": None}
                )
            entries.sort(key=lambda e: str(e.get("name") or "").lower())
            return {"path": p, "entries": entries}

        # /fs/email/<acct>/labels/<labelId>
        if len(rel) == 3 and rel[1] == "labels":
            acct = rel[0]
            label_id = rel[2]
            lock = self._lock_for(acct)
            contended = lock.locked()
            if contended:
                pass
            with lock:
                st = self._state(acct)
                try:
                    msg_ids = gmail_list_message_ids(
                        st.service, user_id=st.acct.user_id, label_id=label_id, max_results=50
                    )
                    meta = gmail_fetch_metadata_batch(st.service, user_id=st.acct.user_id, message_ids=msg_ids)
                except GmailError as e:
                    self._reset_state(acct, reason=f"gmail_list_messages/metadata failed: {str(e)[:200]}")
                    st = self._state(acct)
                    try:
                        msg_ids = gmail_list_message_ids(
                            st.service, user_id=st.acct.user_id, label_id=label_id, max_results=50
                        )
                        meta = gmail_fetch_metadata_batch(st.service, user_id=st.acct.user_id, message_ids=msg_ids)
                    except GmailError as e2:
                        return self._error_listing(
                            p,
                            error=(
                                "Gmail messages are temporarily unavailable.\n\n"
                                f"Label: {label_id}\n"
                                f"Error: {str(e2)[:600]}\n"
                            ),
                        )
            entries = []
            for mid in msg_ids:
                m = meta.get(mid) or {"id": mid}
                view = summarize_metadata(m)
                date_part = "unknown-date"
                if view.internal_date and len(view.internal_date) >= 10:
                    date_part = view.internal_date[:10]
                subj = view.subject.strip() if view.subject else ""
                subj_slug = _snake_slug(subj or "message")
                fname = f"{date_part}--{subj_slug}--{mid}.email.md"
                entries.append(
                    {
                        "name": fname,
                        "path": f"/fs/email/{acct}/labels/{label_id}/{fname}",
                        "kind": "file",
                        "size": None,
                    }
                )
            return {"path": p, "entries": entries}

        raise RuntimeError("Unknown /fs/email path")

    def read(self, path: str, *, max_bytes: int = 512_000) -> dict[str, Any]:
        p = path.rstrip("/") or path
        rel = _email_rel_parts(p)

        # Virtual error files created during list() failures.
        if p in self._error_files:
            return {"path": p, "content": _truncate_utf8(self._error_files[p], max_bytes)}

        if p == "/fs/email/README.md":
            return {"path": p, "content": _truncate_utf8(self._readme(), max_bytes)}

        # /fs/email/<acct>/labels/<labelId>/<file>
        if len(rel) == 4 and rel[1] == "labels" and rel[3].endswith(".email.md"):
            acct = rel[0]
            message_id = rel[3].removesuffix(".email.md").split("--")[-1]
            if not message_id:
                raise RuntimeError("Invalid email filename (missing message id)")

            lock = self._lock_for(acct)
            contended = lock.locked()
            if contended:
                pass
            with lock:
                st = self._state(acct)
                try:
                    msg = gmail_get_message_full(st.service, user_id=st.acct.user_id, message_id=message_id)
                except GmailError as e:
                    self._reset_state(acct, reason=f"gmail_get_message_full failed: {str(e)[:200]}")
                    st = self._state(acct)
                    try:
                        msg = gmail_get_message_full(st.service, user_id=st.acct.user_id, message_id=message_id)
                    except GmailError as e2:
                        return {
                            "path": p,
                            "content": _truncate_utf8(
                                "Gmail message is temporarily unavailable.\n\n"
                                f"Error: {str(e2)[:600]}\n",
                                max_bytes,
                            ),
                        }
            md = render_message_markdown(msg)
            return {"path": p, "content": _truncate_utf8(md, max_bytes)}
        raise RuntimeError("Unknown /fs/email file")

    def write(self, path: str, *, content: str) -> dict[str, Any]:
        _ = (path, content)
        raise RuntimeError("Email provider is read-only")

    def move(self, from_path: str, to_path: str) -> dict[str, Any]:
        _ = (from_path, to_path)
        raise RuntimeError("Email provider is read-only")

