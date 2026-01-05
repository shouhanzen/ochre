from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.fs.router import fs_list, fs_move, fs_read, fs_write
from app.agent.tool_errors import ToolStructuredError


ToolFunc = Callable[[dict[str, Any]], Awaitable[Any]]

DEFAULT_EXCLUDE_GLOBS = [
    "**/.git/**",
    "**/node_modules/**",
    "**/dist/**",
    "**/build/**",
    "**/.venv/**",
]


def _glob_match(path: str, glob: str) -> bool:
    # Path.match is anchored; strip leading "/" so "**/x" works naturally.
    try:
        from pathlib import PurePosixPath

        return PurePosixPath(path.lstrip("/")).match(glob)
    except Exception:
        # fallback: very coarse match
        return False


def _any_glob_match(path: str, globs: list[str]) -> bool:
    for g in globs:
        if g and _glob_match(path, g):
            return True
    return False


@dataclass
class _GrepStats:
    dirs_visited: int = 0
    files_considered: int = 0
    files_read: int = 0
    skipped_too_large: int = 0
    skipped_binary_or_decode_failed: int = 0
    skipped_read_error: int = 0
    matches: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "dirs_visited": self.dirs_visited,
            "files_considered": self.files_considered,
            "files_read": self.files_read,
            "files_skipped": {
                "too_large": self.skipped_too_large,
                "binary_or_decode_failed": self.skipped_binary_or_decode_failed,
                "read_error": self.skipped_read_error,
            },
            "matches": self.matches,
        }


def _find_line_col_samples(text: str, needle: str, max_samples: int = 3) -> list[dict[str, Any]]:
    if not needle:
        return []
    out: list[dict[str, Any]] = []
    start = 0
    while len(out) < max_samples:
        idx = text.find(needle, start)
        if idx == -1:
            break
        # compute line/col (1-based col)
        line_no = text.count("\n", 0, idx) + 1
        line_start = text.rfind("\n", 0, idx) + 1
        line_end = text.find("\n", idx)
        if line_end == -1:
            line_end = len(text)
        col = idx - line_start + 1
        out.append({"line": line_no, "col": col, "line_text": text[line_start:line_end]})
        start = idx + len(needle)
    return out


def _truncate_utf8(s: str, cap_bytes: int) -> tuple[str, bool, int]:
    b = s.encode("utf-8", errors="replace")
    if len(b) <= cap_bytes:
        return s, False, len(b)
    cut = b[:cap_bytes]
    # ensure valid utf-8
    while True:
        try:
            return cut.decode("utf-8", errors="strict"), True, cap_bytes
        except UnicodeDecodeError:
            cut = cut[:-1]
            if not cut:
                return "", True, 0


async def _fs_grep(args: dict[str, Any]) -> Any:
    dir_path = str(args.get("dir") or "").strip()
    query = str(args.get("query") or "")
    regex = bool(args.get("regex", False))
    case_sensitive = bool(args.get("case_sensitive", False))
    include_globs = args.get("include_globs") or []
    exclude_globs = args.get("exclude_globs", None)
    max_files = int(args.get("max_files", 2000))
    max_matches = int(args.get("max_matches", 200))
    max_file_bytes = int(args.get("max_file_bytes", 512_000))
    context_before = int(args.get("context_before", 0))
    context_after = int(args.get("context_after", 0))

    if not dir_path.startswith("/fs"):
        raise ToolStructuredError(
            {
                "ok": False,
                "error": {"code": "invalid_dir", "message": "dir must start with /fs", "details": {"dir": dir_path}},
                "stats": _GrepStats().as_dict(),
            }
        )
    if not query:
        raise ToolStructuredError(
            {
                "ok": False,
                "error": {"code": "invalid_query", "message": "query must be non-empty", "details": {"query": query}},
                "stats": _GrepStats().as_dict(),
            }
        )

    if not isinstance(include_globs, list):
        include_globs = []
    if exclude_globs is None:
        exclude_globs = DEFAULT_EXCLUDE_GLOBS
    if not isinstance(exclude_globs, list):
        exclude_globs = DEFAULT_EXCLUDE_GLOBS

    flags = 0 if case_sensitive else re.IGNORECASE
    rx = None
    if regex:
        try:
            rx = re.compile(query, flags=flags)
        except Exception as e:  # noqa: BLE001
            raise ToolStructuredError(
                {
                    "ok": False,
                    "error": {"code": "invalid_query", "message": f"invalid regex: {e}", "details": {"query": query}},
                    "stats": _GrepStats().as_dict(),
                }
            ) from e

    stats = _GrepStats()
    matches_out: list[dict[str, Any]] = []
    truncated = False
    stop_reason: str | None = None

    # Ensure root is a directory.
    try:
        root_list = fs_list(dir_path)
        if not isinstance(root_list, dict) or "entries" not in root_list:
            raise RuntimeError("fs_list did not return entries")
    except Exception as e:  # noqa: BLE001
        raise ToolStructuredError(
            {
                "ok": False,
                "error": {"code": "not_a_dir", "message": str(e), "details": {"dir": dir_path}},
                "stats": stats.as_dict(),
            }
        ) from e

    to_visit: list[str] = [dir_path.rstrip("/") or "/fs"]
    visited_dirs: set[str] = set()
    max_dirs = max(5000, max_files * 4)

    while to_visit:
        if stats.dirs_visited >= max_dirs:
            truncated = True
            stop_reason = "max_dirs"
            break
        if stats.files_read >= max_files:
            truncated = True
            stop_reason = "max_files"
            break
        if stats.matches >= max_matches:
            truncated = True
            stop_reason = "max_matches"
            break

        d = to_visit.pop()
        if d in visited_dirs:
            continue
        if _any_glob_match(d, exclude_globs):
            continue
        visited_dirs.add(d)
        stats.dirs_visited += 1

        try:
            listed = fs_list(d)
            entries = listed.get("entries") or []
        except Exception:
            stats.skipped_read_error += 1
            continue

        for ent in entries:
            if stats.files_read >= max_files:
                truncated = True
                stop_reason = "max_files"
                break
            if stats.matches >= max_matches:
                truncated = True
                stop_reason = "max_matches"
                break
            if not isinstance(ent, dict):
                continue
            p = str(ent.get("path") or "")
            kind = str(ent.get("kind") or "")
            if not p:
                continue
            if _any_glob_match(p, exclude_globs):
                continue
            if kind == "dir":
                to_visit.append(p)
                continue
            if kind != "file":
                continue

            stats.files_considered += 1
            if include_globs and not _any_glob_match(p, include_globs):
                continue

            try:
                r = fs_read(p, max_bytes=max_file_bytes)
                content = r.get("content")
                if not isinstance(content, str):
                    stats.skipped_binary_or_decode_failed += 1
                    continue
                if len(content.encode("utf-8", errors="replace")) > max_file_bytes:
                    stats.skipped_too_large += 1
                    continue
                stats.files_read += 1
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "too large" in msg.lower():
                    stats.skipped_too_large += 1
                elif isinstance(e, UnicodeDecodeError) or "decode" in msg.lower():
                    stats.skipped_binary_or_decode_failed += 1
                else:
                    stats.skipped_read_error += 1
                continue

            lines = content.splitlines()
            if not lines:
                continue

            if regex and rx is not None:
                for i, line in enumerate(lines):
                    for m in rx.finditer(line):
                        stats.matches += 1
                        matches_out.append(
                            {
                                "path": p,
                                "line": i + 1,
                                "col": m.start() + 1,
                                "line_text": line,
                                "before": lines[max(0, i - context_before) : i],
                                "after": lines[i + 1 : i + 1 + context_after],
                            }
                        )
                        if stats.matches >= max_matches:
                            truncated = True
                            stop_reason = "max_matches"
                            break
                    if truncated and stop_reason == "max_matches":
                        break
            else:
                q = query if case_sensitive else query.lower()
                for i, line in enumerate(lines):
                    hay = line if case_sensitive else line.lower()
                    start = 0
                    while True:
                        idx = hay.find(q, start)
                        if idx == -1:
                            break
                        stats.matches += 1
                        matches_out.append(
                            {
                                "path": p,
                                "line": i + 1,
                                "col": idx + 1,
                                "line_text": line,
                                "before": lines[max(0, i - context_before) : i],
                                "after": lines[i + 1 : i + 1 + context_after],
                            }
                        )
                        if stats.matches >= max_matches:
                            truncated = True
                            stop_reason = "max_matches"
                            break
                        start = idx + max(1, len(q))
                    if truncated and stop_reason == "max_matches":
                        break

        if truncated:
            break

    return {
        "ok": True,
        "dir": dir_path,
        "query": query,
        "regex": regex,
        "case_sensitive": case_sensitive,
        "truncated": truncated,
        "stop_reason": stop_reason,
        "stats": stats.as_dict(),
        "matches": matches_out,
    }


def _count_non_overlapping(hay: str, needle: str) -> list[int]:
    if not needle:
        return []
    out: list[int] = []
    i = 0
    while True:
        idx = hay.find(needle, i)
        if idx == -1:
            break
        out.append(idx)
        i = idx + len(needle)
    return out


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()


async def _fs_patch(args: dict[str, Any]) -> Any:
    path = str(args.get("path") or "").strip()
    edits = args.get("edits") or []
    max_file_bytes = int(args.get("max_file_bytes", 512_000))
    max_total_delta_bytes = int(args.get("max_total_delta_bytes", 20_000))
    diff_cap_bytes = int(args.get("diff_cap_bytes", 200_000))

    if not path.startswith("/fs/"):
        raise ToolStructuredError(
            {"ok": False, "path": path, "error": {"code": "invalid_edit", "message": "path must start with /fs/", "details": {"path": path}}}
        )
    if not isinstance(edits, list) or not edits:
        raise ToolStructuredError(
            {"ok": False, "path": path, "error": {"code": "invalid_edit", "message": "edits must be a non-empty list", "details": {}}}
        )

    try:
        r = fs_read(path, max_bytes=max_file_bytes)
        before = r.get("content")
        if not isinstance(before, str):
            raise RuntimeError("fs_read did not return text content")
    except Exception as e:  # noqa: BLE001
        raise ToolStructuredError(
            {"ok": False, "path": path, "error": {"code": "read_failed", "message": str(e), "details": {"path": path}}}
        ) from e

    before_bytes = len(before.encode("utf-8", errors="replace"))
    if before_bytes > max_file_bytes:
        raise ToolStructuredError(
            {
                "ok": False,
                "path": path,
                "before_sha256": _sha256_text(before),
                "error": {
                    "code": "too_large",
                    "message": f"file exceeds max_file_bytes ({before_bytes} > {max_file_bytes})",
                    "details": {"before_bytes": before_bytes, "max_file_bytes": max_file_bytes},
                },
            }
        )

    cur = before
    edit_results: list[dict[str, Any]] = []
    total_delta = 0

    def fail(*, code: str, message: str, details: dict[str, Any]) -> ToolStructuredError:
        payload = {
            "ok": False,
            "path": path,
            "before_sha256": _sha256_text(before),
            "error": {"code": code, "message": message, "details": details},
            "edit_results": edit_results,
            "diff_unified": "",
            "diff_truncated": False,
            "diff_bytes": 0,
            "diff_cap_bytes": diff_cap_bytes,
        }
        return ToolStructuredError(payload)

    for idx, raw in enumerate(edits):
        if not isinstance(raw, dict):
            raise fail(code="invalid_edit", message="edit must be an object", details={"edit_index": idx})
        op = str(raw.get("op") or "")
        edit_id = raw.get("id")
        expected = int(raw.get("expected_matches", 1))
        if expected < 0:
            expected = 0

        base_res = {
            "index": idx,
            "id": edit_id,
            "op": op,
            "expected_matches": expected,
        }

        if op == "replace":
            old = str(raw.get("old") or "")
            new = str(raw.get("new") or "")
            if not old:
                edit_results.append({**base_res, "matches_found": 0, "status": "failed"})
                raise fail(code="invalid_edit", message="replace.old must be non-empty", details={"edit_index": idx, "op": op})
            hits = _count_non_overlapping(cur, old)
            found = len(hits)
            if found != expected:
                edit_results.append({**base_res, "matches_found": found, "status": "failed"})
                samples = _find_line_col_samples(cur, old, max_samples=3)
                raise fail(
                    code="ambiguous_edit" if found > 1 else "no_match",
                    message=f"replace matched {found} times; expected {expected}.",
                    details={"edit_index": idx, "edit_id": edit_id, "op": op, "expected_matches": expected, "matches_found": found, "samples": samples},
                )
            if found == 0:
                edit_results.append({**base_res, "matches_found": 0, "status": "ok"})
                continue
            total_delta += len(old.encode("utf-8", errors="replace")) * found
            total_delta += len(new.encode("utf-8", errors="replace")) * found
            if total_delta > max_total_delta_bytes:
                edit_results.append({**base_res, "matches_found": found, "status": "failed"})
                raise fail(
                    code="delta_too_large",
                    message=f"total edit delta exceeds cap ({total_delta} > {max_total_delta_bytes})",
                    details={"total_delta_bytes": total_delta, "max_total_delta_bytes": max_total_delta_bytes},
                )
            # Apply replacements from end to start for stable slicing.
            pieces: list[str] = []
            last = 0
            for pos in hits:
                pieces.append(cur[last:pos])
                pieces.append(new)
                last = pos + len(old)
            pieces.append(cur[last:])
            cur = "".join(pieces)
            edit_results.append({**base_res, "matches_found": found, "status": "ok"})

        elif op == "delete":
            old = str(raw.get("old") or "")
            if not old:
                edit_results.append({**base_res, "matches_found": 0, "status": "failed"})
                raise fail(code="invalid_edit", message="delete.old must be non-empty", details={"edit_index": idx, "op": op})
            hits = _count_non_overlapping(cur, old)
            found = len(hits)
            if found != expected:
                edit_results.append({**base_res, "matches_found": found, "status": "failed"})
                samples = _find_line_col_samples(cur, old, max_samples=3)
                raise fail(
                    code="ambiguous_edit" if found > 1 else "no_match",
                    message=f"delete matched {found} times; expected {expected}.",
                    details={"edit_index": idx, "edit_id": edit_id, "op": op, "expected_matches": expected, "matches_found": found, "samples": samples},
                )
            if found == 0:
                edit_results.append({**base_res, "matches_found": 0, "status": "ok"})
                continue
            total_delta += len(old.encode("utf-8", errors="replace")) * found
            if total_delta > max_total_delta_bytes:
                edit_results.append({**base_res, "matches_found": found, "status": "failed"})
                raise fail(
                    code="delta_too_large",
                    message=f"total edit delta exceeds cap ({total_delta} > {max_total_delta_bytes})",
                    details={"total_delta_bytes": total_delta, "max_total_delta_bytes": max_total_delta_bytes},
                )
            cur = cur.replace(old, "")
            edit_results.append({**base_res, "matches_found": found, "status": "ok"})

        elif op in ("insert_before", "insert_after"):
            anchor = str(raw.get("anchor") or "")
            insert = str(raw.get("insert") or "")
            if not anchor:
                edit_results.append({**base_res, "matches_found": 0, "status": "failed"})
                raise fail(code="invalid_edit", message="insert.anchor must be non-empty", details={"edit_index": idx, "op": op})
            hits = _count_non_overlapping(cur, anchor)
            found = len(hits)
            if found != expected:
                edit_results.append({**base_res, "matches_found": found, "status": "failed"})
                samples = _find_line_col_samples(cur, anchor, max_samples=3)
                raise fail(
                    code="ambiguous_edit" if found > 1 else "no_match",
                    message=f"{op} anchor matched {found} times; expected {expected}.",
                    details={"edit_index": idx, "edit_id": edit_id, "op": op, "expected_matches": expected, "matches_found": found, "samples": samples},
                )
            if found == 0:
                edit_results.append({**base_res, "matches_found": 0, "status": "ok"})
                continue
            total_delta += len(insert.encode("utf-8", errors="replace")) * found
            if total_delta > max_total_delta_bytes:
                edit_results.append({**base_res, "matches_found": found, "status": "failed"})
                raise fail(
                    code="delta_too_large",
                    message=f"total edit delta exceeds cap ({total_delta} > {max_total_delta_bytes})",
                    details={"total_delta_bytes": total_delta, "max_total_delta_bytes": max_total_delta_bytes},
                )
            # Apply from end to start.
            for pos in reversed(hits):
                if op == "insert_before":
                    cur = cur[:pos] + insert + cur[pos:]
                else:
                    cur = cur[: pos + len(anchor)] + insert + cur[pos + len(anchor) :]
            edit_results.append({**base_res, "matches_found": found, "status": "ok"})

        else:
            edit_results.append({**base_res, "matches_found": 0, "status": "failed"})
            raise fail(code="invalid_edit", message=f"unknown op: {op}", details={"edit_index": idx, "op": op})

    after = cur
    after_bytes = len(after.encode("utf-8", errors="replace"))
    if after_bytes > max_file_bytes:
        raise ToolStructuredError(
            {
                "ok": False,
                "path": path,
                "before_sha256": _sha256_text(before),
                "error": {
                    "code": "too_large",
                    "message": f"result exceeds max_file_bytes ({after_bytes} > {max_file_bytes})",
                    "details": {"after_bytes": after_bytes, "max_file_bytes": max_file_bytes},
                },
                "edit_results": edit_results,
                "diff_unified": "",
                "diff_truncated": False,
                "diff_bytes": 0,
                "diff_cap_bytes": diff_cap_bytes,
            }
        )

    diff = "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a{path}",
            tofile=f"b{path}",
            lineterm="",
        )
    )
    diff, diff_truncated, diff_bytes = _truncate_utf8(diff, diff_cap_bytes)

    if before != after:
        try:
            fs_write(path, content=after)
        except Exception as e:  # noqa: BLE001
            raise ToolStructuredError(
                {
                    "ok": False,
                    "path": path,
                    "before_sha256": _sha256_text(before),
                    "error": {"code": "write_failed", "message": str(e), "details": {"path": path}},
                    "edit_results": edit_results,
                    "diff_unified": diff,
                    "diff_truncated": diff_truncated,
                    "diff_bytes": diff_bytes,
                    "diff_cap_bytes": diff_cap_bytes,
                }
            ) from e

    return {
        "ok": True,
        "path": path,
        "changed": before != after,
        "before_sha256": _sha256_text(before),
        "after_sha256": _sha256_text(after),
        "diagnostics": {"before_bytes": before_bytes, "after_bytes": after_bytes, "total_delta_bytes": total_delta},
        "edit_results": edit_results,
        "diff_unified": diff,
        "diff_truncated": diff_truncated,
        "diff_bytes": diff_bytes,
        "diff_cap_bytes": diff_cap_bytes,
    }

async def _fs_list(args: dict[str, Any]) -> Any:
    return fs_list(str(args.get("path", "")))


async def _fs_read(args: dict[str, Any]) -> Any:
    # 'path' can be str or list[str]
    path_arg = args.get("path")
    if not path_arg:
        raise ValueError("Missing path argument")
    return fs_read(path_arg, max_bytes=int(args.get("max_bytes", 512_000)))


async def _fs_write(args: dict[str, Any]) -> Any:
    return fs_write(str(args.get("path", "")), content=str(args.get("content", "")))

async def _fs_move(args: dict[str, Any]) -> Any:
    # 'fromPath' and 'toPath' can be str or list[str]
    from_arg = args.get("fromPath") or args.get("from_path")
    to_arg = args.get("toPath") or args.get("to_path")
    if not from_arg or not to_arg:
         raise ValueError("Missing fromPath or toPath argument")
    if not from_arg or not to_arg:
         raise ValueError("Missing fromPath or toPath argument")
    return fs_move(from_arg, to_arg)


def tool_handlers() -> dict[str, ToolFunc]:
    return {
        "fs_list": _fs_list,
        "fs_read": _fs_read,
        "fs_write": _fs_write,
        "fs_move": _fs_move,
        "fs_grep": _fs_grep,
        "fs_patch": _fs_patch,
    }


