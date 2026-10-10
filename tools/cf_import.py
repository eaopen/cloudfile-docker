#!/usr/bin/env python3
"""One-way, operator-run import jobs with a local checkpoint and source adapters."""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import tempfile
from urllib.parse import quote, unquote, urlparse
from uuid import UUID, uuid4

import requests


CHUNK = 1024 * 1024
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
NAME_LIMIT = 255
DEPTH_LIMIT = 128
TIMEOUT = (10, 120)


class ImportErrorSafe(Exception):
    pass


def valid_parts(path, *, absolute):
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ImportErrorSafe("invalid path")
    if absolute != path.startswith("/"):
        raise ImportErrorSafe("path must be absolute" if absolute else "path must be relative")
    if path == "/" and absolute:
        return ()
    value = path[1:] if absolute else path
    parts = tuple(value.split("/"))
    if len(parts) > DEPTH_LIMIT or len(path.encode("utf-8")) > 4096:
        raise ImportErrorSafe("path exceeds the supported limit")
    for part in parts:
        if (part in ("", ".", "..") or ".." in part or "\\" in part or any(ord(c) < 32 for c in part)
                or len(part.encode("utf-8")) > NAME_LIMIT):
            raise ImportErrorSafe("invalid path component")
    return parts


def child_path(parent, name):
    valid_parts(name, absolute=False)
    if "/" in name:
        raise ImportErrorSafe("source entry contains a separator")
    result = (parent + "/" if parent else "") + name
    valid_parts(result, absolute=False)
    return result


def target_path(root, relative):
    return root.rstrip("/") + "/" + relative if relative else root


def token_from(path):
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value or "\n" in value or "\r" in value:
        raise ImportErrorSafe("token file is empty or invalid")
    return value


def request(session, method, url, *, token, bearer=False, expected=(200,), stream=False, **kwargs):
    header = "Bearer" if bearer else "Token"
    try:
        response = session.request(method, url, headers={"Authorization": header + " " + token, **kwargs.pop("headers", {})},
                                   stream=stream, allow_redirects=False, timeout=TIMEOUT, **kwargs)
    except requests.exceptions.RequestException as exc:
        raise ImportErrorSafe("remote request failed") from exc
    if response.status_code not in expected:
        status = response.status_code
        response.close()
        raise ImportErrorSafe(f"{method} remote request failed with HTTP {status}")
    return response


def json_response(response):
    try:
        return response.json()
    except (ValueError, requests.exceptions.RequestException) as exc:
        raise ImportErrorSafe("invalid JSON from remote service") from exc
    finally:
        response.close()


class LocalSource:
    def __init__(self, root):
        self.root = root

    def _root_fd(self):
        return os.open(self.root, DIR_FLAGS)

    def _dir_fd(self, parts):
        current = self._root_fd()
        try:
            for part in parts:
                next_fd = os.open(part, DIR_FLAGS, dir_fd=current)
                os.close(current)
                current = next_fd
            return current
        except BaseException:
            os.close(current)
            raise

    def entries(self):
        root = self._root_fd()
        try:
            yield from self._entries(root, "", 0)
        finally:
            os.close(root)

    def _entries(self, directory, prefix, depth):
        if depth >= DEPTH_LIMIT:
            raise ImportErrorSafe("source exceeds the directory depth limit")
        before = os.fstat(directory)
        names = set()
        with os.scandir(directory) as listing:
            for item in listing:
                folded = item.name.casefold()
                if folded in names:
                    raise ImportErrorSafe("source contains case-insensitive name collisions")
                names.add(folded)
                path = child_path(prefix, item.name)
                info = item.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(item.name, DIR_FLAGS, dir_fd=directory)
                    try:
                        observed = os.fstat(child)
                        if (observed.st_dev, observed.st_ino) != (info.st_dev, info.st_ino):
                            raise ImportErrorSafe("source directory changed during scan")
                        yield (path, "dir", 0, info.st_mtime_ns)
                        yield from self._entries(child, path, depth + 1)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode):
                    yield (path, "file", info.st_size, info.st_mtime_ns)
                else:
                    raise ImportErrorSafe("source contains a link or special file")
        after = os.fstat(directory)
        if (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns):
            raise ImportErrorSafe("source directory changed during scan")

    def copy_file(self, path, expected_size, expected_mtime, output):
        parts = valid_parts(path, absolute=False)
        directory = self._dir_fd(parts[:-1])
        try:
            fd = os.open(parts[-1], FILE_FLAGS, dir_fd=directory)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or (before.st_size, before.st_mtime_ns) != (expected_size, expected_mtime):
                    raise ImportErrorSafe("source file changed since check")
                digest = hashlib.sha256()
                size = 0
                while data := os.read(fd, CHUNK):
                    output.write(data)
                    digest.update(data)
                    size += len(data)
                after = os.fstat(fd)
                if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or size != expected_size:
                    raise ImportErrorSafe("source file changed while reading")
                return digest.hexdigest()
            finally:
                os.close(fd)
        finally:
            os.close(directory)


class FilestashSource:
    def __init__(self, config, session):
        self.root = config["source_path"].rstrip("/")
        self.base = config["filestash_url"].rstrip("/")
        self.token = token_from(config["filestash_token_file"])
        self.session = session

    def _url(self, operation, path):
        return self.base + "/api/files/" + operation + "?path=" + quote(path, safe="/")

    def _list(self, path):
        value = json_response(request(self.session, "GET", self._url("ls", path), token=self.token, bearer=True))
        if not isinstance(value, dict) or value.get("status") != "ok" or not isinstance(value.get("results"), list):
            raise ImportErrorSafe("Filestash returned an invalid directory listing")
        if len(value["results"]) >= 10000 or value.get("has_more") or value.get("next"):
            raise ImportErrorSafe("Filestash directory listing reached the safety limit; completeness is unknown")
        return value["results"]

    def entries(self):
        yield from self._entries(self.root or "/", "", 0)

    def _entries(self, full_path, prefix, depth):
        if depth >= DEPTH_LIMIT:
            raise ImportErrorSafe("source exceeds the directory depth limit")
        seen = set()
        for item in self._list(full_path):
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ImportErrorSafe("Filestash returned an invalid entry")
            name = item["name"].rstrip("/")
            path = child_path(prefix, name)
            if name.casefold() in seen:
                raise ImportErrorSafe("Filestash returned duplicate or case-colliding entries")
            seen.add(name.casefold())
            source_path = full_path.rstrip("/") + "/" + name
            kind = item.get("type")
            if kind in ("directory", "dir", "folder"):
                stamp = item.get("time", 0)
                if type(stamp) is not int:
                    raise ImportErrorSafe("Filestash directory timestamp is invalid")
                yield (path, "dir", 0, stamp * 1000000)
                yield from self._entries(source_path + "/", path, depth + 1)
            elif kind == "file" and type(item.get("size")) is int and item["size"] >= 0 and type(item.get("time")) is int:
                yield (path, "file", item["size"], item["time"] * 1000000)
            else:
                raise ImportErrorSafe("Filestash returned an unsupported entry")

    def copy_file(self, path, expected_size, expected_mtime, output):
        parts = valid_parts(path, absolute=False)
        parent = self.root or "/"
        for component in parts[:-1]:
            parent = parent.rstrip("/") + "/" + component
        current = next((item for item in self._list(parent.rstrip("/") + "/")
                        if isinstance(item, dict) and isinstance(item.get("name"), str)
                        and item["name"].rstrip("/") == parts[-1]), None)
        if not current or current.get("size") != expected_size or current.get("time") != expected_mtime // 1000000:
            raise ImportErrorSafe("Filestash source changed since check")
        full_path = parent.rstrip("/") + "/" + parts[-1]
        response = request(self.session, "GET", self._url("cat", full_path), token=self.token, bearer=True, stream=True)
        digest = hashlib.sha256()
        size = 0
        try:
            for data in response.iter_content(CHUNK):
                if data:
                    output.write(data)
                    digest.update(data)
                    size += len(data)
        finally:
            response.close()
        if size != expected_size:
            raise ImportErrorSafe("Filestash source size changed while reading")
        current = next((item for item in self._list(parent.rstrip("/") + "/")
                        if isinstance(item, dict) and isinstance(item.get("name"), str)
                        and item["name"].rstrip("/") == parts[-1]), None)
        if not current or current.get("size") != expected_size or current.get("time") != expected_mtime // 1000000:
            raise ImportErrorSafe("Filestash source changed while reading")
        return digest.hexdigest()


class Target:
    def __init__(self, config, session):
        self.config = config
        self.session = session
        self.base = config["server"].rstrip("/")
        self.repo = config["repo"]
        self.token = token_from(config["token_file"])
        self.allowed_origin = config.get("fileserver_origin") or origin(self.base)
        self.known_dirs = {"/"}

    def api(self, method, path, *, expected=(200,), **kwargs):
        return request(self.session, method, self.base + path, token=self.token, expected=expected, **kwargs)

    def remote_url(self, value):
        if not isinstance(value, str) or origin(value) != self.allowed_origin:
            raise ImportErrorSafe("fileserver URL is outside the configured origin")
        return value

    def head(self):
        info = json_response(self.api("GET", f"/api2/repos/{self.repo}/"))
        head = info.get("head_commit_id") if isinstance(info, dict) else None
        if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
            raise ImportErrorSafe("repository HEAD is unavailable")
        return head

    def dir_entries(self, path):
        url = f"/api/v2.1/repos/{self.repo}/dir/?p={quote(path, safe='/')}&start=0&limit=1"
        response = self.api("GET", url, expected=(200, 404))
        if response.status_code == 404:
            response.close()
            return None
        result = json_response(response)
        if not isinstance(result, dict) or not isinstance(result.get("dirent_list"), list):
            raise ImportErrorSafe("repository directory listing is invalid")
        return result["dirent_list"]

    def ensure_dir(self, path, expected_head):
        built = ""
        for part in valid_parts(path, absolute=True):
            built += "/" + part
            if built in self.known_dirs:
                continue
            if self.dir_entries(built) is not None:
                self.known_dirs.add(built)
                continue
            if self.file_exists(built):
                raise ImportErrorSafe("target path is occupied by a file")
            if self.head() != expected_head:
                raise ImportErrorSafe("repository changed outside this import job")
            try:
                response = self.api("POST", f"/api2/repos/{self.repo}/dir/?p={quote(built, safe='/')}",
                                    data={"operation": "mkdir"}, expected=(200, 201))
            except ImportErrorSafe as exc:
                raise ImportErrorSafe("target directory creation failed: " + str(exc)) from exc
            response.close()
            if self.dir_entries(built) is None:
                raise ImportErrorSafe("created directory is not visible")
            self.known_dirs.add(built)
            expected_head = self.head()
        return expected_head

    def link(self, operation, parent):
        value = json_response(self.api("GET", f"/api2/repos/{self.repo}/{operation}-link/?p={quote(parent, safe='/')}"))
        return self.remote_url(value)

    def file_exists(self, path):
        response = self.api("GET", f"/api2/repos/{self.repo}/file/?p={quote(path, safe='/')}", expected=(200, 404))
        exists = response.status_code == 200
        response.close()
        return exists

    def upload(self, path, stream, size, *, replace):
        parent, name = path.rsplit("/", 1)
        parent = parent or "/"
        url = self.link("update" if replace else "upload", parent)
        boundary = "cfimport" + uuid4().hex
        fields = {"target_file": path} if replace else {"parent_dir": parent, "replace": "0"}
        prefix = b"".join((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n").encode() for key, value in fields.items())
        quoted_name = name.replace('"', '\\"')
        prefix += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                   f"filename=\"{quoted_name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
        suffix = f"\r\n--{boundary}--\r\n".encode()

        class MultipartBody:
            def __len__(self):
                return len(prefix) + size + len(suffix)

            def __iter__(self):
                yield prefix
                while data := stream.read(CHUNK):
                    yield data
                yield suffix

        try:
            response = request(self.session, "POST", url, token=self.token, expected=(200, 201),
                               data=MultipartBody(), headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                                             "Content-Length": str(len(prefix) + size + len(suffix))})
        except ImportErrorSafe as exc:
            raise ImportErrorSafe("target file upload failed: " + str(exc)) from exc
        response.close()

    def verify_file(self, path, expected_size, expected_hash):
        value = json_response(self.api("GET", f"/api2/repos/{self.repo}/file/?p={quote(path, safe='/')}"))
        url = self.remote_url(value)
        response = request(self.session, "GET", url, token=self.token, stream=True)
        digest = hashlib.sha256()
        size = 0
        try:
            for data in response.iter_content(CHUNK):
                if data:
                    size += len(data)
                    digest.update(data)
        finally:
            response.close()
        if size != expected_size or digest.hexdigest() != expected_hash:
            raise ImportErrorSafe("target file content does not match source")


def origin(url):
    parsed = urlparse(url)
    if (parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ImportErrorSafe("invalid service URL")
    return parsed.scheme + "://" + parsed.netloc


def connect(job):
    db = sqlite3.connect(job / "state.sqlite")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS items (path TEXT PRIMARY KEY, kind TEXT NOT NULL, size INTEGER NOT NULL, mtime INTEGER NOT NULL, sha256 TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS plan (path TEXT PRIMARY KEY, kind TEXT NOT NULL, size INTEGER NOT NULL, mtime INTEGER NOT NULL, action TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)")
    db.commit()
    return db


def get_meta(db, key):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(db, key, value):
    db.execute("INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


@contextlib.contextmanager
def opened_job(directory):
    job = Path(directory).resolve(strict=True)
    if not job.is_dir():
        raise ImportErrorSafe("job directory is unavailable")
    with (job / "lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = json.loads((job / "config.json").read_text(encoding="utf-8"))
        db = connect(job)
        try:
            yield job, config, db
        finally:
            db.close()


@contextlib.contextmanager
def read_job(directory):
    job = Path(directory).resolve(strict=True)
    database = job / "state.sqlite"
    if not database.is_file():
        raise ImportErrorSafe("job state is unavailable")
    config = json.loads((job / "config.json").read_text(encoding="utf-8"))
    db = sqlite3.connect("file:" + quote(str(database), safe="/") + "?mode=ro", uri=True)
    try:
        yield config, db
    finally:
        db.close()


def create(args):
    job = Path(args.job_dir)
    if not job.is_absolute() or job.exists():
        raise ImportErrorSafe("job directory must be an unused absolute path")
    valid_parts(args.target, absolute=True)
    UUID(args.repo)
    origin(args.server)
    if args.source.startswith("local://"):
        parsed = urlparse(args.source)
        if parsed.netloc or parsed.query or parsed.fragment or not parsed.path.startswith("/"):
            raise ImportErrorSafe("local source must be local:///absolute/path")
        source_type, source_path = "local", unquote(parsed.path)
        os.close(os.open(source_path, DIR_FLAGS))
        real_source = Path(source_path).resolve(strict=True)
        real_job = job.parent.resolve(strict=True) / job.name
        if real_source == real_job or real_source in real_job.parents or real_job in real_source.parents:
            raise ImportErrorSafe("job and local source directories must not overlap")
        if real_source in Path(args.token_file).resolve(strict=True).parents:
            raise ImportErrorSafe("CloudFile token file must be outside the source tree")
    elif args.source.startswith("filestash://"):
        parsed = urlparse(args.source)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", parsed.netloc) or parsed.query or parsed.fragment:
            raise ImportErrorSafe("Filestash source must name a stable mount alias")
        source_path = unquote(parsed.path)
        valid_parts(source_path, absolute=True)
        if not args.filestash_url or not args.filestash_token_file:
            raise ImportErrorSafe("Filestash URL and token file are required")
        origin(args.filestash_url)
        source_type = "filestash"
    else:
        raise ImportErrorSafe("source must use local:/// or filestash://")
    token_from(args.token_file)
    if source_type == "filestash":
        token_from(args.filestash_token_file)
    config = {"version": 1, "source_type": source_type, "source_path": source_path,
              "source_alias": parsed.netloc if source_type == "filestash" else None,
              "repo": str(UUID(args.repo)), "target": args.target, "server": args.server.rstrip("/"),
              "token_file": str(Path(args.token_file).resolve()),
              "fileserver_origin": origin(args.fileserver_origin) if args.fileserver_origin else None,
              "filestash_url": args.filestash_url.rstrip("/") if source_type == "filestash" else None,
              "filestash_token_file": str(Path(args.filestash_token_file).resolve()) if source_type == "filestash" else None}
    job.mkdir(mode=0o700)
    try:
        descriptor = os.open(job / "config.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(config, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        with connect(job):
            pass
    except Exception:
        raise
    print(json.dumps({"job_dir": str(job), "source": args.source, "repo": config["repo"], "target": args.target}, ensure_ascii=False))


def source_for(config, session):
    return LocalSource(config["source_path"]) if config["source_type"] == "local" else FilestashSource(config, session)


def check(args):
    with opened_job(args.job_dir) as (_, config, db), requests.Session() as session:
        if get_meta(db, "plan_status") == "running":
            raise ImportErrorSafe("unfinished apply must be resumed before a new check")
        target = Target(config, session)
        head = target.head()
        baseline = get_meta(db, "applied_head")
        if baseline and head != baseline:
            raise ImportErrorSafe("repository changed since the last completed import")
        if not baseline:
            listing = target.dir_entries(config["target"])
            if listing:
                raise ImportErrorSafe("initial target directory is not empty")
            if listing is None and config["target"] != "/" and target.file_exists(config["target"]):
                raise ImportErrorSafe("initial target path is occupied by a file")
        db.execute("DROP TABLE IF EXISTS scan")
        db.execute("CREATE TABLE scan (path TEXT PRIMARY KEY, kind TEXT NOT NULL, size INTEGER NOT NULL, mtime INTEGER NOT NULL)")
        db.commit()
        try:
            for path, kind, size, mtime in source_for(config, session).entries():
                db.execute("INSERT INTO scan VALUES (?,?,?,?)", (path, kind, size, mtime))
            db.commit()
            db.execute("DELETE FROM plan")
            db.execute("INSERT INTO plan(path,kind,size,mtime,action) SELECT s.path,s.kind,s.size,s.mtime, "
                       "CASE WHEN i.path IS NULL THEN 'add' WHEN i.kind!=s.kind THEN 'conflict' ELSE 'modify' END "
                       "FROM scan s LEFT JOIN items i ON i.path=s.path "
                       "WHERE i.path IS NULL OR i.kind!=s.kind OR i.size!=s.size OR i.mtime!=s.mtime")
            db.execute("INSERT INTO plan(path,kind,size,mtime,action) SELECT i.path,i.kind,i.size,i.mtime,'delete_candidate' "
                       "FROM items i LEFT JOIN scan s ON s.path=i.path WHERE s.path IS NULL")
            set_meta(db, "plan_head", head)
            set_meta(db, "plan_status", "ready")
            db.execute("DROP TABLE scan")
            db.commit()
        except Exception:
            db.rollback()
            db.execute("DROP TABLE IF EXISTS scan")
            db.commit()
            raise
        print(json.dumps(plan_summary(db), ensure_ascii=False))


def plan_summary(db):
    counts = {row[0]: {"entries": row[1], "bytes": row[2], "done": row[3]} for row in db.execute(
        "SELECT action,COUNT(*),COALESCE(SUM(size),0),COALESCE(SUM(done),0) FROM plan GROUP BY action")}
    return {"status": get_meta(db, "plan_status"), "head": get_meta(db, "plan_head"), "actions": counts}


def plan(args):
    with read_job(args.job_dir) as (_, db):
        result = plan_summary(db)
        if args.limit:
            if not 1 <= args.limit <= 1000:
                raise ImportErrorSafe("plan limit must be between 1 and 1000")
            result["entries"] = [dict(path=row[0], action=row[1], kind=row[2], done=bool(row[3])) for row in db.execute(
                "SELECT path,action,kind,done FROM plan ORDER BY path LIMIT ?", (args.limit,))]
        print(json.dumps(result, ensure_ascii=False))


def status(args):
    with read_job(args.job_dir) as (config, db):
        print(json.dumps({"source_type": config["source_type"], "source_alias": config["source_alias"],
                          "source_path": config["source_path"],
                          "repo": config["repo"], "target": config["target"], "applied_head": get_meta(db, "applied_head"),
                          "plan": plan_summary(db)}, ensure_ascii=False))



def report(args):
    """Read-only operator handoff: never pretend that an unknown write is safe."""
    from datetime import datetime, timezone
    with read_job(args.job_dir) as (config, db):
        summary = plan_summary(db)
        actions = {}
        for name, info in summary["actions"].items():
            actions[name] = {
                "entries": info["entries"], "bytes": info["bytes"],
                "completed": info["done"], "remaining": info["entries"] - info["done"],
            }
        plan_state = summary["status"]
        pending = sum(item["remaining"] for name, item in actions.items()
                      if name != "delete_candidate")
        result = {
            "schema": "cloudfile.import-report.v1",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "source_type": config["source_type"],
            "repo": config["repo"], "target": config["target"],
            "plan_status": plan_state,
            "last_applied_head": get_meta(db, "applied_head"),
            "plan_head": summary["head"],
            "actions": actions, "pending_operations": pending,
            "delete_candidates_retained": actions.get("delete_candidate", {}).get("entries", 0),
            "has_conflicts": actions.get("conflict", {}).get("entries", 0) > 0,
            "operator_attention": plan_state == "running" or bool(
                actions.get("conflict", {}).get("entries", 0)),
            "note": ("Running state might include a remote upload with an unknown "
                     "result. A HEAD mismatch must be reviewed, never blindly retried.")
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def apply(args):
    if not args.exclusive:
        raise ImportErrorSafe("apply requires --exclusive: reserve the target library against other writers")
    with opened_job(args.job_dir) as (job, config, db), requests.Session() as session:
        if get_meta(db, "plan_status") not in ("ready", "running"):
            raise ImportErrorSafe("run check before apply")
        if db.execute("SELECT 1 FROM plan WHERE action='conflict' LIMIT 1").fetchone():
            raise ImportErrorSafe("source path type changed; resolve plan conflict before apply")
        target = Target(config, session)
        source = source_for(config, session)
        expected_head = get_meta(db, "plan_head")
        if target.head() != expected_head:
            raise ImportErrorSafe("repository changed outside this import job; no writes were made")
        if get_meta(db, "plan_status") == "ready" and not get_meta(db, "applied_head"):
            if target.dir_entries(config["target"]):
                raise ImportErrorSafe("initial target directory is no longer empty")
        set_meta(db, "plan_status", "running")
        db.commit()

        def save_head(value):
            nonlocal expected_head
            expected_head = value
            set_meta(db, "plan_head", value)
            db.commit()

        save_head(target.ensure_dir(config["target"], expected_head))
        rows = db.execute("SELECT path,kind,size,mtime,action FROM plan WHERE done=0 AND action!='delete_candidate' "
                          "ORDER BY CASE kind WHEN 'dir' THEN 0 ELSE 1 END, LENGTH(path), path").fetchall()
        for path, kind, size, mtime, action in rows:
            if target.head() != expected_head:
                raise ImportErrorSafe("repository changed outside this import job")
            remote = target_path(config["target"], path)
            if kind == "dir":
                save_head(target.ensure_dir(remote, expected_head))
                digest = None
            else:
                parent = remote.rsplit("/", 1)[0] or "/"
                save_head(target.ensure_dir(parent, expected_head))
                exists = target.file_exists(remote)
                if exists != (action == "modify"):
                    raise ImportErrorSafe("target file existence differs from the saved import plan")
                with tempfile.TemporaryFile(dir=job) as spool:
                    digest = source.copy_file(path, size, mtime, spool)
                    spool.seek(0)
                    if target.head() != expected_head:
                        raise ImportErrorSafe("repository changed outside this import job")
                    target.upload(remote, spool, size, replace=action == "modify")
                target.verify_file(remote, size, digest)
                expected_head = target.head()
            db.execute("INSERT INTO items(path,kind,size,mtime,sha256) VALUES (?,?,?,?,?) "
                       "ON CONFLICT(path) DO UPDATE SET kind=excluded.kind,size=excluded.size,mtime=excluded.mtime,sha256=excluded.sha256",
                       (path, kind, size, mtime, digest))
            db.execute("UPDATE plan SET done=1 WHERE path=?", (path,))
            set_meta(db, "plan_head", expected_head)
            db.commit()
        if target.head() != expected_head:
            raise ImportErrorSafe("repository changed before import completion")
        set_meta(db, "applied_head", expected_head)
        set_meta(db, "plan_status", "complete")
        db.commit()
        print(json.dumps(plan_summary(db), ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Controlled one-way import to a CloudFile library")
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("create")
    new.add_argument("--job-dir", required=True)
    new.add_argument("--source", required=True, help="local:///absolute/path or filestash://alias/absolute/path")
    new.add_argument("--repo", required=True)
    new.add_argument("--target", required=True)
    new.add_argument("--server", required=True)
    new.add_argument("--token-file", required=True)
    new.add_argument("--fileserver-origin")
    new.add_argument("--filestash-url")
    new.add_argument("--filestash-token-file")
    new.set_defaults(func=create)
    for name, callback in (("check", check), ("plan", plan), ("apply", apply), ("status", status), ("report", report)):
        command = commands.add_parser(name)
        command.add_argument("job_dir")
        if name == "plan":
            command.add_argument("--limit", type=int, default=0)
        if name == "apply":
            command.add_argument("--exclusive", action="store_true")
        command.set_defaults(func=callback)
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except requests.exceptions.RequestException:
        print("cf-import: remote transfer failed", file=sys.stderr)
        return 2
    except (ImportErrorSafe, OSError, sqlite3.Error, ValueError) as error:
        print("cf-import: " + str(error), file=sys.stderr)
        return 2
