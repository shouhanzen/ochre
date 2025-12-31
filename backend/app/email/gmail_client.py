from __future__ import annotations

import base64
import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.email.gmail_config import GmailAccount


class GmailError(RuntimeError):
    pass


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _b64url_decode(s: str) -> bytes:
    if not s:
        return b""
    # Gmail uses base64url without padding.
    pad = "=" * ((4 - (len(s) % 4)) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


def _header_map(headers: list[dict[str, Any]] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in headers or []:
        try:
            k = str(h.get("name") or "").strip()
            v = str(h.get("value") or "").strip()
        except Exception:
            continue
        if k:
            out[k] = v
    return out


def _walk_parts(payload: dict[str, Any] | None) -> Iterable[dict[str, Any]]:
    if not payload:
        return
    stack = [payload]
    while stack:
        p = stack.pop()
        yield p
        for child in reversed(p.get("parts") or []):
            if isinstance(child, dict):
                stack.append(child)


def _pick_body_text(payload: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """
    Return (text_plain, text_html) decoded from the Gmail payload.
    """
    text_plain: list[str] = []
    text_html: list[str] = []
    for part in _walk_parts(payload):
        mime = str(part.get("mimeType") or "")
        body = part.get("body") or {}
        data = body.get("data")
        if not isinstance(data, str) or not data:
            continue
        try:
            decoded = _b64url_decode(data).decode("utf-8", errors="replace")
        except Exception:
            decoded = ""
        if not decoded:
            continue
        if mime == "text/plain":
            text_plain.append(decoded)
        elif mime == "text/html":
            text_html.append(decoded)
    return ("\n\n".join(text_plain) if text_plain else None, "\n\n".join(text_html) if text_html else None)


def build_gmail_service(acct: GmailAccount):
    if not acct.credentials_path.exists():
        raise GmailError(f"Gmail credentials file not found: {acct.credentials_path}")
    if not acct.token_path.exists():
        raise GmailError(f"Gmail token file not found: {acct.token_path}")

    creds = Credentials.from_authorized_user_file(str(acct.token_path), scopes=SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:  # noqa: BLE001
                raise GmailError(f"Failed to refresh Gmail token: {e}") from e
            try:
                acct.token_path.parent.mkdir(parents=True, exist_ok=True)
                acct.token_path.write_text(creds.to_json(), encoding="utf-8")
            except Exception:
                # best-effort; token still usable in-memory
                pass
        else:
            raise GmailError("Gmail credentials are invalid/expired; re-run gmail auth to create a token.")

    # cache discovery to disk by default; disable to avoid writing inside containers unexpectedly
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def gmail_modify_message_labels(
    service,
    *,
    user_id: str,
    message_id: str,
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
) -> dict[str, Any]:
    try:
        body = {}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels
        
        if not body:
            return {}

        return (
            service.users()
            .messages()
            .modify(userId=user_id, id=message_id, body=body)
            .execute()
        )
    except Exception as e:
        raise GmailError(f"Failed to modify message labels: {e}") from e


def gmail_list_labels(service, *, user_id: str) -> list[dict[str, Any]]:
    try:
        resp = service.users().labels().list(userId=user_id).execute()
        labels = resp.get("labels") or []
        return [label for label in labels if isinstance(label, dict)]
    except Exception as e:  # noqa: BLE001
        raise GmailError(f"Failed to list labels: {e}") from e


def gmail_list_message_ids(
    service,
    *,
    user_id: str,
    label_ids: list[str] | None = None,
    query: str | None = None,
    max_results: int = 50,
) -> list[str]:
    try:
        kwargs: dict[str, Any] = {"userId": user_id, "maxResults": max_results}
        if label_ids:
            kwargs["labelIds"] = label_ids
        if query:
            kwargs["q"] = query

        resp = service.users().messages().list(**kwargs).execute()
        msgs = resp.get("messages") or []
        out: list[str] = []
        for m in msgs:
            if isinstance(m, dict) and m.get("id"):
                out.append(str(m["id"]))
        return out
    except Exception as e:  # noqa: BLE001
        raise GmailError(f"Failed to list messages: {e}") from e


def gmail_fetch_metadata_batch(
    service,
    *,
    user_id: str,
    message_ids: list[str],
    metadata_headers: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Fetch per-message metadata (Subject/From/Date/etc) using a batch request.
    Returns {messageId: messageResource}.
    """
    headers = metadata_headers or ["Subject", "From", "To", "Date"]
    out: dict[str, dict[str, Any]] = {}

    def _cb(req_id: str, resp: Any, exc: Exception | None) -> None:
        _ = req_id
        if exc is not None:
            return
        if isinstance(resp, dict) and resp.get("id"):
            out[str(resp["id"])] = resp

    try:
        batch = service.new_batch_http_request(callback=_cb)
        for mid in message_ids:
            batch.add(
                service.users()
                .messages()
                .get(
                    userId=user_id,
                    id=mid,
                    format="metadata",
                    metadataHeaders=headers,
                )
            )
        batch.execute()
    except Exception as e:  # noqa: BLE001
        raise GmailError(f"Failed to fetch message metadata batch: {e}") from e

    return out


@dataclass(frozen=True)
class GmailMessageView:
    message_id: str
    subject: str
    from_: str
    to: str
    date: str
    internal_date: str | None
    snippet: str


def _format_internal_date(ms: str | int | None) -> str | None:
    try:
        if ms is None:
            return None
        ts_ms = int(ms)
        d = dt.datetime.fromtimestamp(ts_ms / 1000.0, tz=dt.timezone.utc)
        return d.isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def summarize_metadata(msg: dict[str, Any]) -> GmailMessageView:
    payload = msg.get("payload") or {}
    headers = _header_map(payload.get("headers"))
    return GmailMessageView(
        message_id=str(msg.get("id") or ""),
        subject=headers.get("Subject", ""),
        from_=headers.get("From", ""),
        to=headers.get("To", ""),
        date=headers.get("Date", ""),
        internal_date=_format_internal_date(msg.get("internalDate")),
        snippet=str(msg.get("snippet") or ""),
    )


def gmail_get_message_full(service, *, user_id: str, message_id: str) -> dict[str, Any]:
    try:
        return (
            service.users()
            .messages()
            .get(userId=user_id, id=message_id, format="full")
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        raise GmailError(f"Failed to fetch message: {e}") from e


def render_message_markdown(msg: dict[str, Any]) -> str:
    """
    Render a Gmail message resource (format=full) into a readable Markdown document.
    """
    payload = msg.get("payload") or {}
    headers = _header_map(payload.get("headers"))
    subject = headers.get("Subject", "") or "(no subject)"
    from_ = headers.get("From", "")
    to = headers.get("To", "")
    date = headers.get("Date", "")
    snippet = str(msg.get("snippet") or "")
    internal_date = _format_internal_date(msg.get("internalDate"))
    label_ids = msg.get("labelIds") or []
    if not isinstance(label_ids, list):
        label_ids = []

    text_plain, text_html = _pick_body_text(payload)

    out: list[str] = []
    out.append(f"# {subject}")
    out.append("")
    out.append("## Headers")
    out.append(f"- **From**: {from_}" if from_ else "- **From**: (missing)")
    out.append(f"- **To**: {to}" if to else "- **To**: (missing)")
    out.append(f"- **Date**: {date}" if date else "- **Date**: (missing)")
    if internal_date:
        out.append(f"- **InternalDate (UTC)**: {internal_date}")
    out.append(f"- **Message-ID**: {headers.get('Message-ID', '')}" if headers.get("Message-ID") else "- **Message-ID**: (missing)")
    if label_ids:
        out.append(f"- **Labels**: {', '.join(str(x) for x in label_ids)}")
    out.append("")

    if snippet:
        out.append("## Snippet")
        out.append("")
        out.append(snippet)
        out.append("")

    if text_plain:
        out.append("## Body (text/plain)")
        out.append("")
        out.append(text_plain.strip() + "\n")
    elif text_html:
        out.append("## Body (text/html)")
        out.append("")
        out.append("```html")
        out.append(text_html.strip())
        out.append("```")
        out.append("")
    else:
        out.append("## Body")
        out.append("")
        out.append("(No body text parts found.)")
        out.append("")

    return "\n".join(out).rstrip() + "\n"

