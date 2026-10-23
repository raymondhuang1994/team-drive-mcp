"""Bounded local indexing with versioned evidence and no model/network calls."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional


DEFAULT_LIMITS = {
    "max_file_bytes": 268435456, "max_uncompressed_bytes": 536870912,
    "max_segments": 100000, "max_segment_chars": 8000,
    "max_columns": 512, "max_pdf_pages": 2000, "parse_timeout_seconds": 30,
}
SUPPORTED_SUFFIXES = {".txt", ".md", ".csv", ".tsv", ".xlsx", ".docx", ".pptx", ".pdf"}
MAX_RESPONSE_BYTES = 65536
MAX_SEGMENT_BYTES = 49152
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
LATIN_RE = re.compile(r"[a-z0-9]+")


class DriveError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False,
                 next_action: str = "Check the request and configuration."):
        super().__init__(message)
        self.code, self.message = code, message
        self.retryable, self.next_action = retryable, next_action


def failure(code: str, message: str, retryable: bool = False,
            next_action: str = "Check the request and configuration.") -> dict:
    return {"ok": False, "error": {"code": code, "message": message,
            "retryable": retryable, "next_action": next_action}}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def tokenize(value: str) -> list:
    """Exact keyword tokens, including one/two-character Chinese terms, not semantics."""
    folded = value.casefold()
    tokens = {"w" + word for word in LATIN_RE.findall(folded)}
    for run in CJK_RE.findall(folded):
        tokens.update("c" + char.encode("utf-8").hex() for char in run)
        tokens.update("b" + run[i:i + 2].encode("utf-8").hex() for i in range(len(run) - 1))
    return sorted(tokens)


def query_tokens(value: str) -> list:
    folded = value.casefold()
    tokens = {"w" + word for word in LATIN_RE.findall(folded)}
    for run in CJK_RE.findall(folded):
        if len(run) == 1:
            tokens.add("c" + run.encode("utf-8").hex())
        else:
            tokens.update("b" + run[i:i + 2].encode("utf-8").hex() for i in range(len(run) - 1))
    return sorted(tokens)


class Engine:
    def __init__(self, config_path: str, autostart: bool = True):
        if os.name != "posix" or os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "fwalk"):
            raise DriveError("UNSUPPORTED_PLATFORM", "This release requires macOS or Linux with safe directory-relative file access.")
        config_file = Path(config_path).expanduser().resolve(strict=True)
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raise DriveError("INVALID_CONFIG", "Configuration must be valid UTF-8 JSON.")
        if not isinstance(config, dict) or config.get("provider", "local") != "local":
            raise DriveError("UNSUPPORTED_PROVIDER", "Only the local provider is implemented.")
        for key in ("root", "state_dir"):
            if not isinstance(config.get(key), str) or not config[key]:
                raise DriveError("INVALID_CONFIG", "root and state_dir must be nonempty paths.")
        raw_root = Path(config["root"]).expanduser()
        raw_root = raw_root if raw_root.is_absolute() else config_file.parent / raw_root
        if raw_root.is_symlink():
            raise DriveError("UNSAFE_ROOT", "The source root cannot be a symbolic link.")
        self.root = raw_root.resolve(strict=True)
        if not self.root.is_dir():
            raise DriveError("INVALID_ROOT", "The source root must be an existing directory.")
        root_info = self.root.stat()
        self._root_identity = (root_info.st_dev, root_info.st_ino)
        self._root_fd = None
        raw_state = Path(config["state_dir"]).expanduser()
        raw_state = raw_state if raw_state.is_absolute() else config_file.parent / raw_state
        if raw_state.is_symlink():
            raise DriveError("UNSAFE_STATE", "The state directory cannot be a symbolic link.")
        self.state = raw_state.resolve()
        if self.state == self.root or self.root in self.state.parents:
            raise DriveError("UNSAFE_STATE", "The state directory must be outside the source root.")
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = self.state / "index.sqlite"
        if self.db_path.is_symlink():
            raise DriveError("UNSAFE_STATE", "The index database cannot be a symbolic link.")
        configured_limits = config.get("limits", {})
        if not isinstance(configured_limits, dict):
            raise DriveError("INVALID_CONFIG", "limits must be an object.")
        self.limits = dict(DEFAULT_LIMITS)
        for key, val in configured_limits.items():
            if key not in DEFAULT_LIMITS or isinstance(val, bool) or not isinstance(val, int) or val < 1:
                raise DriveError("INVALID_CONFIG", "Limits must use known keys and positive integers.")
            self.limits[key] = val
        poll = config.get("poll_seconds", 30)
        if isinstance(poll, bool) or not isinstance(poll, (int, float)) or poll < 1:
            raise DriveError("INVALID_CONFIG", "poll_seconds must be at least one second.")
        self.poll_seconds = poll
        self.aliases = config.get("aliases", {})
        if not isinstance(self.aliases, dict) or any(
                not isinstance(k, str) or not isinstance(v, list) or
                any(not isinstance(a, str) for a in v) for k, v in self.aliases.items()):
            raise DriveError("INVALID_CONFIG", "aliases must map strings to lists of strings.")
        self._secret = secrets.token_bytes(32)
        self._stop = threading.Event()
        self._scan_lock = threading.Lock()
        self._job_lock = threading.Lock()
        self._queue = queue.Queue()
        self._cancelled = set()
        self._pending_job = None
        self._thread = None
        self._process_lock = threading.Lock()
        self._active_process = None
        self._force_jobs = set()
        self._root_binding = hashlib.sha256(str(self.root).encode()).hexdigest()
        parser_signature = hashlib.sha256(Path(__file__).with_name("extract.py").read_bytes()).hexdigest()
        indexer_signature = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self._parse_binding = hashlib.sha256(_json({"parser": parser_signature, "indexer": indexer_signature, "limits": self.limits, "aliases": self.aliases, "schema": 3}).encode()).hexdigest()
        import fcntl
        self._lock_fd = os.open(str(self.state / ".worker.lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self._lock_fd)
            self._lock_fd = None
            raise DriveError("STATE_IN_USE", "Another worker is using this state directory.", True, "Reuse the existing worker or configure a separate state directory.")
        try:
            self._root_fd = os.open(str(self.root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            pinned_info = os.fstat(self._root_fd)
            if (pinned_info.st_dev, pinned_info.st_ino) != self._root_identity:
                raise DriveError("SOURCE_ROOT_CHANGED", "The configured source root changed during initialization.", False, "Restore the approved directory and restart the worker.")
            self._init_db()
        except Exception:
            os.close(self._lock_fd)
            self._lock_fd = None
            if self._root_fd is not None:
                os.close(self._root_fd)
                self._root_fd = None
            raise
        if autostart:
            self._thread = threading.Thread(target=self._run, name="team-drive-index", daemon=True)
            self._thread.start()
            self.refresh()

    def _db(self):
        conn = sqlite3.connect(str(self.db_path), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    def _init_db(self):
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                INSERT OR IGNORE INTO meta VALUES('generation','0');
                INSERT OR IGNORE INTO meta VALUES('inventory_complete','false');
                INSERT OR IGNORE INTO meta VALUES('last_scan_at','null');
                CREATE TABLE IF NOT EXISTS files(
                  id TEXT PRIMARY KEY,path TEXT NOT NULL UNIQUE,suffix TEXT,size INTEGER,
                  mtime_ns INTEGER,ctime_ns INTEGER,source_version TEXT,status TEXT NOT NULL,
                  error_code TEXT,error_message TEXT,segments_count INTEGER NOT NULL DEFAULT 0,
                  seen_scan TEXT,updated_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS files_status ON files(status,path);
                CREATE TABLE IF NOT EXISTS segments(
                  file_id TEXT NOT NULL,ordinal INTEGER NOT NULL,source_version TEXT NOT NULL,
                  payload TEXT NOT NULL,PRIMARY KEY(file_id,ordinal));
                CREATE INDEX IF NOT EXISTS segments_sheet_row ON segments(
                  file_id,source_version,json_extract(payload,'$.locator.sheet'),
                  json_extract(payload,'$.locator.row'),ordinal);
                CREATE INDEX IF NOT EXISTS segments_row ON segments(
                  file_id,source_version,json_extract(payload,'$.locator.row'),ordinal);
                CREATE INDEX IF NOT EXISTS segments_page ON segments(
                  file_id,source_version,json_extract(payload,'$.locator.page'),ordinal);
                CREATE INDEX IF NOT EXISTS segments_slide ON segments(
                  file_id,source_version,json_extract(payload,'$.locator.slide'),ordinal);
                CREATE TABLE IF NOT EXISTS structure(
                  file_id TEXT NOT NULL,position INTEGER NOT NULL,group_key TEXT NOT NULL,
                  start_ordinal INTEGER NOT NULL,end_ordinal INTEGER NOT NULL,
                  PRIMARY KEY(file_id,position));
                CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
                  tokens,file_id UNINDEXED,ordinal UNINDEXED,tokenize='ascii');
                CREATE TABLE IF NOT EXISTS jobs(
                  id TEXT PRIMARY KEY,status TEXT NOT NULL,created_at REAL NOT NULL,
                  started_at REAL,finished_at REAL,discovered INTEGER NOT NULL DEFAULT 0,
                  processed INTEGER NOT NULL DEFAULT 0,error_code TEXT);
            """)
            columns = {r[1] for r in db.execute("PRAGMA table_info(files)")}
            if "format_warnings" not in columns:
                db.execute("ALTER TABLE files ADD COLUMN format_warnings TEXT NOT NULL DEFAULT '[]'")
            root_binding = db.execute("SELECT value FROM meta WHERE key='root_binding'").fetchone()
            if root_binding and root_binding[0] != self._root_binding:
                raise DriveError("STATE_ROOT_MISMATCH", "This state directory belongs to a different source root.", False, "Choose a new empty state directory for the new source root.")
            db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('root_binding',?)", (self._root_binding,))
            old_binding = db.execute("SELECT value FROM meta WHERE key='parse_binding'").fetchone()
            if old_binding and old_binding[0] != self._parse_binding:
                db.execute("UPDATE files SET status='pending',source_version=NULL,segments_count=0,format_warnings='[]' WHERE status!='deleted'")
                db.execute("DELETE FROM segments")
                db.execute("DELETE FROM structure")
                db.execute("DELETE FROM search_index")
                self._bump(db)
            db.execute("INSERT INTO meta(key,value) VALUES('parse_binding',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (self._parse_binding,))
            db.execute("UPDATE jobs SET status='interrupted',finished_at=? WHERE status IN ('queued','running')", (time.time(),))
        # Private parser work directories are disposable and can contain extracted text.
        for child in self.state.glob("job-temp-*"):
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
        for pattern in ("snapshot-*", "parsed-*"):
            for child in self.state.glob(pattern):
                if child.is_file() and not child.is_symlink():
                    child.unlink()

    @staticmethod
    def _bump(db):
        db.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")

    @staticmethod
    def _generation(db):
        return int(db.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0])

    def _coverage(self, db):
        counts = {row["status"]: row["n"] for row in db.execute("SELECT status,COUNT(*) n FROM files GROUP BY status")}
        present = sum(n for s, n in counts.items() if s != "deleted")
        inventory = db.execute("SELECT value FROM meta WHERE key='inventory_complete'").fetchone()[0] == "true"
        return {"inventory_complete": inventory, "present_files": present,
                "indexed_files": counts.get("ready", 0), "states": counts,
                "all_present_files_indexed": inventory and present == counts.get("ready", 0),
                "scope": "Configured local root; content freshness is revalidated before evidence reads.",
                "business_completeness": "not_established"}

    def _file_out(self, row):
        return {"file_id": row["id"], "path": row["path"], "format": row["suffix"].lstrip("."),
                "size_bytes": row["size"], "modified_ns": row["mtime_ns"],
                "source_version": row["source_version"], "status": row["status"],
                "segments_count": row["segments_count"],
                "format_warnings": json.loads(row["format_warnings"]),
                "error": ({"code": row["error_code"], "message": row["error_message"]}
                          if row["error_code"] else None)}

    @staticmethod
    def _prefix(prefix):
        if not isinstance(prefix, str) or len(prefix) > 4096 or "\\" in prefix or "\x00" in prefix:
            raise DriveError("INVALID_PATH", "Use a relative path within the configured root.")
        p = PurePosixPath(prefix)
        if p.is_absolute() or ".." in p.parts:
            raise DriveError("INVALID_PATH", "Absolute paths and parent traversal are forbidden.")
        return "" if str(p) == "." else str(p).rstrip("/")

    @staticmethod
    def _limit(limit):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise DriveError("INVALID_LIMIT", "limit must be an integer between 1 and 100.")
        return limit

    def _cursor(self, binding, offset):
        raw = _json({"binding": binding, "offset": offset}).encode()
        signature = hmac.new(self._secret, raw, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(signature + raw).decode().rstrip("=")

    def _offset(self, cursor, binding):
        if cursor is None:
            return 0
        try:
            if not isinstance(cursor, str) or len(cursor) > 4096:
                raise ValueError()
            decoded = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            sig, raw = decoded[:32], decoded[32:]
            obj = json.loads(raw)
            if not hmac.compare_digest(sig, hmac.new(self._secret, raw, hashlib.sha256).digest()):
                raise ValueError()
            if obj["binding"] != binding:
                raise DriveError("STALE_CURSOR", "The query, index generation, or source version has changed.", True, "Restart pagination without a cursor.")
            offset = obj["offset"]
            if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                raise ValueError()
            return offset
        except DriveError:
            raise
        except (ValueError, TypeError, KeyError):
            raise DriveError("INVALID_CURSOR", "The cursor is invalid or belongs to another server session.", True, "Restart pagination without a cursor.")

    def status(self):
        self._check_root()
        with self._db() as db:
            return {"ok": True, "provider": "local", "index_generation": self._generation(db),
                    "coverage": self._coverage(db), "limits": self.limits,
                    "last_scan_at": json.loads(db.execute("SELECT value FROM meta WHERE key='last_scan_at'").fetchone()[0]),
                    "update_mode": "startup_and_periodic_polling_while_server_runs",
                    "poll_seconds": self.poll_seconds,
                    "search_mode": "keyword_with_configured_aliases_not_semantic",
                    "freshness": "Metadata checked during scans; full digest checked for inspect/read/export.",
                    "network_calls": False, "read_only_sources": True}

    def refresh(self, force=False):
        self._check_root()
        if not isinstance(force, bool):
            raise DriveError("INVALID_PARAMS", "force must be a boolean.")
        with self._job_lock:
            if self._pending_job:
                return {"ok": True, "job_id": self._pending_job, "status": "already_queued_or_running", "force_applied": False}
            job_id = uuid.uuid4().hex
            with self._db() as db:
                db.execute("INSERT INTO jobs(id,status,created_at) VALUES(?,'queued',?)", (job_id, time.time()))
            self._pending_job = job_id
            if force:
                self._force_jobs.add(job_id)
            self._queue.put(job_id)
            return {"ok": True, "job_id": job_id, "status": "queued"}

    def job_status(self, job_id=None):
        with self._db() as db:
            if job_id is None:
                row = db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 1").fetchone()
            else:
                row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise DriveError("JOB_NOT_FOUND", "No matching indexing job exists.")
            return {"ok": True, "job": dict(row), "coverage": self._coverage(db)}

    def cancel(self, job_id):
        result = self.job_status(job_id)
        if result["job"]["status"] in ("queued", "running"):
            self._cancelled.add(job_id)
            return {"ok": True, "job_id": job_id, "status": "cancellation_requested", "boundary": "next_file_boundary"}
        return {"ok": True, "job_id": job_id, "status": result["job"]["status"]}

    def _run(self):
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=self.poll_seconds)
            except queue.Empty:
                if not self._stop.is_set():
                    try:
                        self.refresh()
                    except DriveError:
                        # A missing/rebound root must not terminate the protocol worker.
                        # Public status/read calls return the precise source error.
                        pass
                continue
            if job_id is None:
                break
            try:
                self.scan_once(job_id)
            except Exception as exc:
                with self._db() as db:
                    code = exc.code if isinstance(exc, DriveError) else "SCAN_FAILED"
                    db.execute("UPDATE jobs SET status='failed',error_code=?,finished_at=? WHERE id=?", (code, time.time(), job_id))
            finally:
                with self._job_lock:
                    if self._pending_job == job_id:
                        self._pending_job = None
                self._cancelled.discard(job_id)
                self._force_jobs.discard(job_id)
                self._queue.task_done()
        self._release_state_lock()

    def _release_state_lock(self):
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
        if self._root_fd is not None:
            os.close(self._root_fd)
            self._root_fd = None

    def close(self):
        self._stop.set()
        if self._pending_job:
            self._cancelled.add(self._pending_job)
        self._queue.put(None)
        with self._process_lock:
            if self._active_process is not None and self._active_process.poll() is None:
                self._active_process.kill()
        if self._thread:
            self._thread.join(timeout=2)
        if not self._thread or not self._thread.is_alive():
            self._release_state_lock()

    def _check_root(self):
        try:
            current = os.stat(str(self.root), follow_symlinks=False)
            unchanged = self._root_fd is not None and (current.st_dev, current.st_ino) == self._root_identity and stat.S_ISDIR(current.st_mode)
        except OSError:
            unchanged = False
        if not unchanged:
            raise DriveError("SOURCE_ROOT_CHANGED", "The configured source directory is missing or has been rebound.", False, "Restore the approved directory or configure a new source root with a new state directory.")

    def _open_source(self, rel):
        self._check_root()
        relative = self._prefix(rel)
        if not relative:
            raise DriveError("INVALID_PATH", "A source file path is required.")
        parts = PurePosixPath(relative).parts
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        dir_flags = flags | getattr(os, "O_DIRECTORY", 0)
        fd = os.dup(self._root_fd)
        try:
            for part in parts[:-1]:
                new_fd = os.open(part, dir_flags, dir_fd=fd)
                os.close(fd)
                fd = new_fd
            before_open = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(before_open.st_mode):
                raise DriveError("UNSAFE_FILE", "Only regular local files are supported.")
            if self._online_only(before_open):
                raise DriveError("ONLINE_ONLY", "The file is an online-only placeholder and will not be hydrated automatically.", False, "Download only the approved file using the sync client, then refresh.")
            source_fd = os.open(parts[-1], flags, dir_fd=fd)
        except OSError:
            raise DriveError("SOURCE_UNAVAILABLE", "The source is missing, inaccessible, or traverses a symbolic link.", True, "Refresh the index and check the approved source folder.")
        finally:
            os.close(fd)
        info = os.fstat(source_fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(source_fd)
            raise DriveError("UNSAFE_FILE", "Only regular local files are supported.")
        if info.st_size > self.limits["max_file_bytes"]:
            os.close(source_fd)
            raise DriveError("FILE_TOO_LARGE", "The file exceeds max_file_bytes.", False, "Use a smaller approved source or deliberately adjust the limit.")
        return source_fd, info

    @staticmethod
    def _online_only(info):
        return bool(getattr(info, "st_flags", 0) & getattr(stat, "UF_DATALESS", 0x40000000)) or bool(getattr(info, "st_file_attributes", 0) & (0x1000 | 0x400000))

    @staticmethod
    def _fingerprint(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def _digest(self, rel, snapshot=None):
        fd, before = self._open_source(rel)
        digest = hashlib.sha256()
        total = 0
        with os.fdopen(fd, "rb") as source:
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > self.limits["max_file_bytes"]:
                    raise DriveError("FILE_TOO_LARGE", "The source grew beyond max_file_bytes during reading.")
                digest.update(block)
                if snapshot is not None:
                    snapshot.write(block)
            after = os.fstat(source.fileno())
        if self._fingerprint(before) != self._fingerprint(after):
            raise DriveError("SOURCE_CHANGED", "The source changed during reading.", True, "Wait for writing to finish, then refresh and retry.")
        # Reopen the pathname: a replacement can leave the old open descriptor intact.
        fd2, current = self._open_source(rel)
        os.close(fd2)
        if self._fingerprint(after) != self._fingerprint(current):
            raise DriveError("SOURCE_CHANGED", "The source pathname changed during reading.", True, "Refresh and retry.")
        return digest.hexdigest(), before

    def _invalidate(self, file_id, code, message, status="stale"):
        with self._db() as db:
            db.execute("UPDATE files SET status=?,error_code=?,error_message=?,segments_count=0,updated_at=? WHERE id=?", (status, code, message, time.time(), file_id))
            db.execute("DELETE FROM segments WHERE file_id=?", (file_id,))
            db.execute("DELETE FROM structure WHERE file_id=?", (file_id,))
            db.execute("DELETE FROM search_index WHERE file_id=?", (file_id,))
            self._bump(db)

    def _validated(self, file_id, expected_version=None):
        self._check_root()
        with self._db() as db:
            row = db.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        if row is None or row["status"] == "deleted":
            raise DriveError("FILE_NOT_FOUND", "The file is not present in this index.", True, "Refresh or select a file from list/search.")
        if expected_version is not None and expected_version != row["source_version"]:
            raise DriveError("VERSION_MISMATCH", "The expected source version does not match the indexed version.", True, "Inspect the current source and restart the operation.")
        if row["status"] != "ready":
            raise DriveError(row["error_code"] or "FILE_NOT_READY", row["error_message"] or "The file has not been completely indexed.", True, "Check status, refresh if appropriate, and resolve the stated limitation.")
        try:
            version, _ = self._digest(row["path"])
        except DriveError as exc:
            self._invalidate(file_id, exc.code, exc.message)
            raise
        if version != row["source_version"]:
            self._invalidate(file_id, "STALE_SOURCE", "Source content differs from the indexed version.")
            raise DriveError("STALE_SOURCE", "Source content differs from the indexed version.", True, "Refresh and wait for the file to be indexed again.")
        return row

    def _page(self, base, key, items, limit, offset, total, binding):
        returned = []
        for item in items[:limit]:
            test = dict(base, **{key: returned + [item], "has_more": True, "next_cursor": self._cursor(binding, offset + len(returned) + 1)})
            if len(_json(test).encode()) > MAX_RESPONSE_BYTES - 1024:
                if not returned:
                    raise DriveError("RESPONSE_TOO_LARGE", "One result exceeds the response budget.", False, "Use a controlled export or reduce source segment size.")
                break
            returned.append(item)
        has_more = offset + len(returned) < total
        return dict(base, **{key: returned, "returned": len(returned), "has_more": has_more,
                            "next_cursor": self._cursor(binding, offset + len(returned)) if has_more else None,
                            "truncated": has_more})

    def list(self, prefix="", limit=20, cursor=None):
        self._check_root()
        prefix, limit = self._prefix(prefix), self._limit(limit)
        with self._db() as db:
            db.execute("BEGIN")
            generation = self._generation(db)
            binding = {"method": "list", "prefix": prefix, "generation": generation}
            offset = self._offset(cursor, binding)
            clause, args = "status!='deleted'", []
            if prefix:
                clause += " AND (path=? OR substr(path,1,?)=?)"
                args.extend([prefix, len(prefix) + 1, prefix + "/"])
            total = db.execute("SELECT COUNT(*) FROM files WHERE " + clause, args).fetchone()[0]
            rows = db.execute("SELECT * FROM files WHERE " + clause + " ORDER BY path LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
            base = {"ok": True, "index_generation": generation, "total_matching_files": total,
                    "coverage": self._coverage(db), "freshness": "inventory_metadata"}
        return self._page(base, "files", [self._file_out(row) for row in rows], limit, offset, total, binding)

    def _search_expression(self, query):
        if not isinstance(query, str) or not query.strip() or len(query) > 512:
            raise DriveError("INVALID_QUERY", "query must contain 1 to 512 characters.")
        variants = {query}
        for key, values in self.aliases.items():
            group = [key] + values
            for term in group:
                if term and term in query:
                    variants.update(query.replace(term, alternative) for alternative in group)
        if len(variants) > 32:
            raise DriveError("QUERY_TOO_BROAD", "Too many configured alias expansions.", False, "Use a more specific term.")
        groups = []
        for variant in sorted(variants):
            tokens = query_tokens(variant)
            if tokens:
                groups.append("(" + " AND ".join('"' + token + '"' for token in tokens) + ")")
        if not groups:
            raise DriveError("INVALID_QUERY", "Use Chinese, Latin words, or numeric identifiers.")
        return " OR ".join(groups)

    def search(self, query, prefix="", limit=10, cursor=None):
        self._check_root()
        prefix, limit = self._prefix(prefix), self._limit(limit)
        expression = self._search_expression(query)
        with self._db() as db:
            db.execute("BEGIN")
            generation = self._generation(db)
            binding = {"method": "search", "query": query, "prefix": prefix, "generation": generation}
            offset = self._offset(cursor, binding)
            clause, args = "f.status!='deleted'", [expression]
            if prefix:
                clause += " AND (f.path=? OR substr(f.path,1,?)=?)"
                args.extend([prefix, len(prefix) + 1, prefix + "/"])
            cte = "WITH hits AS (SELECT file_id,MIN(CAST(ordinal AS INTEGER)) ordinal FROM search_index WHERE search_index MATCH ? GROUP BY file_id) "
            join = "FROM files f JOIN hits h ON f.id=h.file_id WHERE " + clause
            total = db.execute(cte + "SELECT COUNT(*) " + join, args).fetchone()[0]
            rows = db.execute(cte + "SELECT f.*,h.ordinal " + join + " ORDER BY f.path LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
            files = []
            for row in rows:
                item = self._file_out(row)
                segment = db.execute("SELECT payload FROM segments WHERE file_id=? AND ordinal=?", (row["id"], row["ordinal"])).fetchone()
                payload = json.loads(segment[0]) if segment else None
                item["match"] = {"kind": "content" if payload else "path", "ordinal": row["ordinal"],
                                 "locator": payload.get("locator") if payload else None,
                                 "snippet": payload.get("text", "")[:600] if payload else row["path"],
                                 "snippet_is_evidence": False}
                files.append(item)
            base = {"ok": True, "index_generation": generation, "query": query,
                    "total_matching_files": total, "coverage": self._coverage(db),
                    "mode": "keyword_candidates", "order": "path",
                    "freshness": "indexed_not_revalidated", "exhaustive_for_business_totals": False,
                    "next_action": "Inspect and read matching sources before answering; keyword matches do not establish a complete business dataset."}
        return self._page(base, "files", files, limit, offset, total, binding)

    def inspect(self, file_id, limit=20, cursor=None):
        limit = self._limit(limit)
        row = self._validated(file_id)
        binding = {"method": "inspect", "file_id": file_id, "version": row["source_version"]}
        offset = self._offset(cursor, binding)
        with self._db() as db:
            db.execute("BEGIN")
            current = db.execute("SELECT source_version,status FROM files WHERE id=?", (file_id,)).fetchone()
            if not current or current["source_version"] != row["source_version"] or current["status"] != "ready":
                raise DriveError("INDEX_CHANGED", "The index changed during inspection.", True, "Restart inspection.")
            total = db.execute("SELECT COUNT(*) FROM structure WHERE file_id=?", (file_id,)).fetchone()[0]
            groups = [{"group": json.loads(r["group_key"]), "start": r["start_ordinal"], "end": r["end_ordinal"],
                       "segments": r["end_ordinal"] - r["start_ordinal"] + 1}
                      for r in db.execute("SELECT * FROM structure WHERE file_id=? ORDER BY position LIMIT ? OFFSET ?", (file_id, limit, offset))]
            coverage = self._coverage(db)
        base = {"ok": True, "file": self._file_out(row), "coverage": coverage,
                "source_version": row["source_version"], "freshness": "digest_verified_at_read_start",
                "total_structure_groups": total, "structure_scope": "Extracted content groups, not visual document layout or business authority. Line bucket boundaries are navigation buckets, not observed file line ranges; start/end are exact segment ordinals.",
                "next_action": "Read at a group's start segment using this expected_version; all groups and their full ranges are needed for exhaustive extraction."}
        return self._page(base, "structure", groups, limit, offset, total, binding)

    @staticmethod
    def _selector(selector, suffix):
        if selector is None:
            return "", [], None
        allowed = {"sheet", "row_start", "row_end", "page", "slide"}
        if not isinstance(selector, dict) or not selector or set(selector) - allowed:
            raise DriveError("INVALID_SELECTOR", "selector must contain supported nonempty location fields.")
        for key, value in selector.items():
            if key == "sheet":
                if not isinstance(value, str) or not value or len(value) > 1024 or "\x00" in value:
                    raise DriveError("INVALID_SELECTOR", "sheet must be a nonempty worksheet name.")
            elif isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 2147483647:
                raise DriveError("INVALID_SELECTOR", "Row, page, and slide numbers must be positive integers.")
        if "row_start" in selector and "row_end" in selector and selector["row_start"] > selector["row_end"]:
            raise DriveError("INVALID_SELECTOR", "row_start cannot exceed row_end.")
        keys = set(selector)
        valid = ((suffix in (".csv", ".tsv") and keys <= {"row_start", "row_end"}) or
                 (suffix == ".xlsx" and "sheet" in keys and keys <= {"sheet", "row_start", "row_end"}) or
                 (suffix == ".pdf" and keys == {"page"}) or
                 (suffix == ".pptx" and keys == {"slide"}))
        if not valid:
            raise DriveError("UNSUPPORTED_SELECTOR", "Use rows for CSV/TSV, sheet with optional rows for XLSX, page for PDF, or slide for PPTX.", False, "Inspect the source and choose a selector compatible with its format.")
        clauses, values = [], []
        for field in ("sheet", "page", "slide"):
            if field in selector:
                clauses.append("json_extract(payload,'$.locator." + field + "')=?")
                values.append(selector[field])
        for field, operator in (("row_start", ">="), ("row_end", "<=")):
            if field in selector:
                clauses.append("json_extract(payload,'$.locator.row')" + operator + "?")
                values.append(selector[field])
        return " AND " + " AND ".join(clauses), values, dict(selector)

    def read(self, file_id, start=0, limit=10, expected_version=None, cursor=None, selector=None):
        limit = self._limit(limit)
        if isinstance(start, bool) or not isinstance(start, int) or start < 0:
            raise DriveError("INVALID_RANGE", "start must be a nonnegative segment offset.")
        row = self._validated(file_id, expected_version)
        selector_sql, selector_values, selector = self._selector(selector, row["suffix"])
        binding = {"method": "read", "file_id": file_id, "version": row["source_version"], "selector": selector}
        offset = self._offset(cursor, binding) if cursor else start
        with self._db() as db:
            db.execute("BEGIN")
            where = "file_id=? AND source_version=?" + selector_sql
            values = [file_id, row["source_version"]] + selector_values
            rows = db.execute("SELECT ordinal,payload FROM segments WHERE " + where + " ORDER BY ordinal LIMIT ? OFFSET ?", values + [limit, offset]).fetchall()
            items = [dict(json.loads(r["payload"]), ordinal=r["ordinal"]) for r in rows]
            total = db.execute("SELECT COUNT(*) FROM segments WHERE file_id=? AND source_version=?", (file_id, row["source_version"])).fetchone()[0]
            matched = db.execute("SELECT COUNT(*) FROM segments WHERE " + where, values).fetchone()[0]
        if total != row["segments_count"]:
            raise DriveError("INDEX_CHANGED", "The index changed during this read.", True, "Inspect and restart the read.")
        base = {"ok": True, "file_id": file_id, "path": row["path"], "source_version": row["source_version"],
                "total_segments": total, "start": offset, "freshness": "digest_verified_at_read_start",
                "extraction_complete": True, "format_warnings": json.loads(row["format_warnings"]),
                "extraction_scope": "Supported extracted content; see format_warnings for omitted content.",
                "selector": selector, "selection_scope": "filtered_segments" if selector else "whole_file_segments",
                "total_matching_segments": matched,
                "business_completeness": "not_established"}
        result = self._page(base, "segments", items, limit, offset, matched, binding)
        result["whole_file_in_response"] = selector is None and offset == 0 and result["returned"] == total
        result["selection_complete_in_response"] = offset == 0 and result["returned"] == matched
        return result

    def export(self, file_id, expected_version, format="jsonl"):
        if format != "jsonl":
            raise DriveError("UNSUPPORTED_EXPORT", "Only JSONL exports are supported.")
        if not isinstance(expected_version, str) or not expected_version:
            raise DriveError("EXPECTED_VERSION_REQUIRED", "Export requires an expected source version.")
        row = self._validated(file_id, expected_version)
        folder = self.state / "exports"
        if folder.is_symlink():
            raise DriveError("UNSAFE_STATE", "The export directory cannot be a symbolic link.")
        folder.mkdir(mode=0o700, exist_ok=True)
        artifact_id = "exports/" + uuid.uuid4().hex + ".jsonl"
        path = self.state / artifact_id
        count = 0
        try:
            with path.open("x", encoding="utf-8") as output, self._db() as db:
                db.execute("BEGIN")
                for item in db.execute("SELECT ordinal,payload FROM segments WHERE file_id=? AND source_version=? ORDER BY ordinal", (file_id, expected_version)):
                    output.write(_json({"file_id": file_id, "path": row["path"], "source_version": expected_version,
                                        "ordinal": item["ordinal"], "segment": json.loads(item["payload"])}) + "\n")
                    count += 1
            if count != row["segments_count"]:
                raise DriveError("INDEX_CHANGED", "The index changed during export.", True, "Inspect and retry.")
            self._validated(file_id, expected_version)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return {"ok": True, "artifact_id": artifact_id, "artifact_path": str(path),
                "artifact_path_scope": "Local runtime path for analysis tools; do not publish runtime traces or exports.",
                "format": "jsonl", "row_count": count,
                "source_version": expected_version, "extraction_complete": True,
                "format_warnings": json.loads(row["format_warnings"]),
                "business_completeness": "not_established", "includes_original_binary": False}

    def call(self, method, params=None):
        methods = {name: getattr(self, name) for name in ("status", "refresh", "job_status", "cancel", "list", "search", "inspect", "read", "export")}
        if method not in methods:
            return failure("UNKNOWN_METHOD", "The requested method is not supported.")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return failure("INVALID_PARAMS", "params must be an object.")
        try:
            result = methods[method](**params)
            if len(_json(result).encode()) > MAX_RESPONSE_BYTES:
                return failure("RESPONSE_TOO_LARGE", "The response exceeds the bounded output size.", False, "Narrow the query or reduce the page size.")
            return result
        except DriveError as exc:
            return failure(exc.code, exc.message, exc.retryable, exc.next_action)
        except TypeError:
            return failure("INVALID_PARAMS", "Parameters do not match this tool's input schema.")
        except Exception:
            return failure("INTERNAL_ERROR", "The operation could not complete.", True, "Check local service health; no source content was modified.")

    def scan_once(self, job_id=None, force=False):
        """Synchronous scan used by the worker thread and deterministic tests."""
        self._check_root()
        with self._scan_lock:
            scan_id = uuid.uuid4().hex
            force = force or job_id in self._force_jobs
            if job_id is None:
                job_id = uuid.uuid4().hex
                with self._db() as db:
                    db.execute("INSERT INTO jobs(id,status,created_at) VALUES(?,'queued',?)", (job_id, time.time()))
            with self._db() as db:
                db.execute("UPDATE jobs SET status='running',started_at=? WHERE id=?", (time.time(), job_id))
                db.execute("UPDATE meta SET value='false' WHERE key='inventory_complete'")
            complete = True
            discovered = 0
            walk_errors = []
            for folder, dirs, files, folder_fd in os.fwalk(".", dir_fd=self._root_fd, follow_symlinks=False, onerror=lambda _: walk_errors.append(True)):
                if job_id in self._cancelled or self._stop.is_set():
                    complete = False
                    break
                symlink_dirs = []
                for directory in dirs:
                    try:
                        if stat.S_ISLNK(os.stat(directory, dir_fd=folder_fd, follow_symlinks=False).st_mode):
                            symlink_dirs.append(directory)
                    except OSError:
                        walk_errors.append(True)
                dirs[:] = [d for d in dirs if d not in symlink_dirs]
                for name in files + symlink_dirs:
                    relative = (PurePosixPath(folder) / name).as_posix()
                    file_id = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:32]
                    suffix = PurePosixPath(relative).suffix.lower()
                    try:
                        info = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
                    except OSError:
                        complete = False
                        continue
                    blocked = stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode)
                    online_only = self._online_only(info)
                    initial = "blocked" if blocked else "online_only" if online_only else "oversized" if info.st_size > self.limits["max_file_bytes"] else "unsupported" if suffix not in SUPPORTED_SUFFIXES else "pending"
                    reason = {"blocked": ("UNSAFE_FILE", "Symbolic links and nonregular files are not read."),
                              "online_only": ("ONLINE_ONLY", "The file is an online-only placeholder and will not be hydrated automatically."),
                              "oversized": ("FILE_TOO_LARGE", "The file exceeds max_file_bytes."),
                              "unsupported": ("UNSUPPORTED_FORMAT", "This file format is not supported.")}.get(initial, (None, None))
                    with self._db() as db:
                        old = db.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
                        unchanged = (old is not None and old["size"] == info.st_size and
                                     old["mtime_ns"] == info.st_mtime_ns and old["ctime_ns"] == info.st_ctime_ns and
                                     old["status"] in ("ready", "failed") and initial == "pending" and not force)
                        if unchanged:
                            db.execute("UPDATE files SET seen_scan=? WHERE id=?", (scan_id, file_id))
                        else:
                            db.execute("INSERT INTO files(id,path,suffix,size,mtime_ns,ctime_ns,status,error_code,error_message,seen_scan,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET path=excluded.path,suffix=excluded.suffix,size=excluded.size,mtime_ns=excluded.mtime_ns,ctime_ns=excluded.ctime_ns,status=excluded.status,error_code=excluded.error_code,error_message=excluded.error_message,source_version=NULL,segments_count=0,seen_scan=excluded.seen_scan,updated_at=excluded.updated_at", (file_id, relative, suffix, info.st_size, info.st_mtime_ns, info.st_ctime_ns, initial, reason[0], reason[1], scan_id, time.time()))
                            db.execute("DELETE FROM segments WHERE file_id=?", (file_id,))
                            db.execute("DELETE FROM structure WHERE file_id=?", (file_id,))
                            db.execute("DELETE FROM search_index WHERE file_id=?", (file_id,))
                            db.execute("INSERT INTO search_index(tokens,file_id,ordinal) VALUES(?,?,-1)", (" ".join(tokenize(relative)), file_id))
                            self._bump(db)
                    discovered += 1
            complete = complete and not walk_errors
            self._check_root()
            with self._db() as db:
                if complete:
                    removed = [r[0] for r in db.execute("SELECT id FROM files WHERE seen_scan!=? AND status!='deleted'", (scan_id,))]
                    for file_id in removed:
                        db.execute("UPDATE files SET status='deleted',source_version=NULL,segments_count=0,error_code=NULL,error_message=NULL WHERE id=?", (file_id,))
                        db.execute("DELETE FROM segments WHERE file_id=?", (file_id,))
                        db.execute("DELETE FROM structure WHERE file_id=?", (file_id,))
                        db.execute("DELETE FROM search_index WHERE file_id=?", (file_id,))
                    if removed:
                        self._bump(db)
                db.execute("UPDATE meta SET value=? WHERE key='inventory_complete'", ("true" if complete else "false",))
                db.execute("UPDATE jobs SET discovered=? WHERE id=?", (discovered, job_id))
            processed = 0
            last_path = ""
            while complete and job_id not in self._cancelled and not self._stop.is_set():
                with self._db() as db:
                    row = db.execute("SELECT * FROM files WHERE status='pending' AND path>? ORDER BY path LIMIT 1", (last_path,)).fetchone()
                if row is None:
                    break
                last_path = row["path"]
                self._parse_file(row)
                processed += 1
                with self._db() as db:
                    db.execute("UPDATE jobs SET processed=? WHERE id=?", (processed, job_id))
            cancelled = job_id in self._cancelled or self._stop.is_set()
            with self._db() as db:
                db.execute("UPDATE jobs SET status=?,finished_at=?,error_code=? WHERE id=?", ("cancelled" if cancelled else "complete" if complete else "failed", time.time(), None if complete else "INVENTORY_INCOMPLETE", job_id))
                db.execute("UPDATE meta SET value=? WHERE key='last_scan_at'", (_json(time.time()),))
            return self.job_status(job_id)

    def _parse_file(self, row):
        snapshot_path = None
        parsed_path = None
        work_dir = Path(tempfile.mkdtemp(dir=self.state, prefix="job-temp-"))
        try:
            with tempfile.NamedTemporaryFile(dir=work_dir, prefix="snapshot-", suffix=row["suffix"], delete=False) as snapshot:
                snapshot_path = Path(snapshot.name)
                version, info = self._digest(row["path"], snapshot)
            with tempfile.NamedTemporaryFile(dir=work_dir, prefix="parsed-", suffix=".jsonl", delete=False) as parsed:
                parsed_path = Path(parsed.name)
            count, warnings = self._extract(snapshot_path, parsed_path)
            current_version, current_info = self._digest(row["path"])
            if current_version != version:
                raise DriveError("SOURCE_CHANGED", "The source changed during parsing.", True, "Wait for writing to finish, then refresh.")
            with self._db() as db, parsed_path.open(encoding="utf-8") as parsed:
                db.execute("DELETE FROM segments WHERE file_id=?", (row["id"],))
                db.execute("DELETE FROM structure WHERE file_id=?", (row["id"],))
                db.execute("DELETE FROM search_index WHERE file_id=?", (row["id"],))
                db.execute("INSERT INTO search_index(tokens,file_id,ordinal) VALUES(?,?,-1)", (" ".join(tokenize(row["path"])), row["id"]))
                group_position, group_start, group_key, group_end = 0, 0, None, 0
                for ordinal, line in enumerate(parsed):
                    payload = json.loads(line)
                    db.execute("INSERT INTO segments VALUES(?,?,?,?)", (row["id"], ordinal, version, line.strip()))
                    db.execute("INSERT INTO search_index(tokens,file_id,ordinal) VALUES(?,?,?)", (" ".join(tokenize(payload.get("text", ""))), row["id"], ordinal))
                    key = self._structure_group(payload.get("locator", {}))
                    if group_key is not None and key != group_key:
                        db.execute("INSERT INTO structure VALUES(?,?,?,?,?)", (row["id"], group_position, group_key, group_start, ordinal - 1))
                        group_position, group_start = group_position + 1, ordinal
                    group_key, group_end = key, ordinal
                if group_key is not None:
                    db.execute("INSERT INTO structure VALUES(?,?,?,?,?)", (row["id"], group_position, group_key, group_start, group_end))
                db.execute("UPDATE files SET source_version=?,status='ready',error_code=NULL,error_message=NULL,segments_count=?,size=?,mtime_ns=?,ctime_ns=?,format_warnings=?,updated_at=? WHERE id=?", (version, count, current_info.st_size, current_info.st_mtime_ns, current_info.st_ctime_ns, _json(warnings), time.time(), row["id"]))
                self._bump(db)
        except DriveError as exc:
            self._invalidate(row["id"], exc.code, exc.message, "failed")
        except Exception:
            self._invalidate(row["id"], "PARSE_FAILED", "The file could not be parsed safely.", "failed")
        finally:
            if snapshot_path:
                snapshot_path.unlink(missing_ok=True)
            if parsed_path:
                parsed_path.unlink(missing_ok=True)
            shutil.rmtree(work_dir, ignore_errors=True)

    @staticmethod
    def _structure_group(locator):
        if not isinstance(locator, dict):
            return _json({"kind": "document"})
        for key in ("sheet", "page", "slide", "heading", "table"):
            if locator.get(key) is not None:
                return _json({key: locator[key]})
        # Long plain text is navigable in 200-line blocks.
        if "line_start" in locator:
            start = ((locator["line_start"] - 1) // 200) * 200 + 1
            return _json({"kind": "line_bucket", "bucket_line_start": start, "bucket_line_end": start + 199})
        return _json({"kind": locator.get("kind", "document")})

    def _extract(self, snapshot_path, parsed_path):
        environment = os.environ.copy()
        environment.update({"TMPDIR": str(snapshot_path.parent), "TMP": str(snapshot_path.parent), "TEMP": str(snapshot_path.parent)})
        package_parent = str(Path(__file__).resolve().parent.parent)
        inherited_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = package_parent + (os.pathsep + inherited_pythonpath if inherited_pythonpath else "")
        process = subprocess.Popen([sys.executable, "-m", "team_drive.extract", str(snapshot_path), _json(self.limits)],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment)
        with self._process_lock:
            self._active_process = process
        timed_out = threading.Event()
        def stop_parser():
            timed_out.set()
            process.kill()
        timer = threading.Timer(self.limits["parse_timeout_seconds"], stop_parser)
        timer.daemon = True
        timer.start()
        count, total_bytes, done = 0, 0, False
        warnings = set()
        try:
            with parsed_path.open("w", encoding="utf-8") as output:
                while True:
                    line = process.stdout.readline(MAX_SEGMENT_BYTES + 2048)
                    if not line:
                        break
                    total_bytes += len(line)
                    if len(line) >= MAX_SEGMENT_BYTES + 2048 or total_bytes > self.limits["max_uncompressed_bytes"]:
                        raise DriveError("PARSE_OUTPUT_LIMIT", "Extracted content exceeds the configured output budget.", False, "Use smaller source files or deliberately adjust limits.")
                    try:
                        item = json.loads(line)
                    except ValueError:
                        raise DriveError("PARSER_PROTOCOL_ERROR", "The parser returned an invalid result.")
                    if item.get("error"):
                        err = item["error"]
                        # Only controlled parser codes/messages; parser does not expose local paths.
                        raise DriveError(str(err.get("code", "PARSE_FAILED"))[:80], str(err.get("message", "Parsing failed."))[:600])
                    if item.get("done") is True:
                        done = True
                        continue
                    segment = item.get("segment")
                    if done or not isinstance(segment, dict) or not isinstance(segment.get("text"), str) or "locator" not in segment:
                        raise DriveError("PARSER_PROTOCOL_ERROR", "The parser returned an invalid segment.")
                    if len(segment["text"]) > self.limits["max_segment_chars"] or len(_json(segment).encode()) > MAX_SEGMENT_BYTES:
                        raise DriveError("SEGMENT_TOO_LARGE", "An extracted segment exceeds the response budget.", False, "Reduce source column widths or adjust segmentation.")
                    count += 1
                    warnings.update(str(value)[:200] for value in segment.get("warnings", []))
                    if count > self.limits["max_segments"]:
                        raise DriveError("SEGMENT_LIMIT", "The file exceeds max_segments.")
                    output.write(_json(segment) + "\n")
            code = process.wait()
            if timed_out.is_set():
                raise DriveError("PARSE_TIMEOUT", "Parsing exceeded parse_timeout_seconds.", True, "Use a smaller source or deliberately adjust the timeout.")
            if code != 0 or not done:
                raise DriveError("PARSE_FAILED", "The parser did not complete successfully.")
            return count, sorted(warnings)
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdout:
                process.stdout.close()
            with self._process_lock:
                if self._active_process is process:
                    self._active_process = None
