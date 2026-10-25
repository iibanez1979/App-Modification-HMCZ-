"""Pruebas del almacenamiento en GitHub con respuestas simuladas (sin red)."""

import io
import tarfile

import pytest

from storage.base import StorageError
from storage.github_store import GitHubStore


class Resp:
    def __init__(self, status, content=b"", payload=None):
        self.status_code, self.content, self._payload = status, content, payload or {}
        self.ok = 200 <= status < 300
        self.text = str(payload or "")

    def json(self):
        return self._payload


def _tarball(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, data in files.items():
            info = tarfile.TarInfo(f"owner-repo-abc123/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_read_all_strips_root_folder(monkeypatch):
    store = GitHubStore("tok", "owner/repo", "data")
    tb = _tarball({"plan/baseline.csv": b"a,b", "plan/.gitkeep": b"", "README.md": b"x"})
    monkeypatch.setattr(store.session, "get", lambda *a, **k: Resp(200, tb))
    files = store.read_all()
    assert files == {"plan/baseline.csv": b"a,b", "README.md": b"x"}


def test_write_retries_with_sha_when_file_exists(monkeypatch):
    store = GitHubStore("tok", "owner/repo", "data")
    calls = []

    def put(url, json, timeout):
        calls.append(dict(json))
        return Resp(422) if "sha" not in json else Resp(200)

    monkeypatch.setattr(store.session, "put", put)
    monkeypatch.setattr(store.session, "get", lambda *a, **k: Resp(200, payload={"sha": "abc"}))
    store.write("users/users.json", b"{}", "msg")
    assert len(calls) == 2 and calls[1]["sha"] == "abc" and calls[1]["branch"] == "data"
    assert store.version == 1
    assert store.snapshot.__self__ is store


def test_expired_token_gives_clear_error(monkeypatch):
    store = GitHubStore("tok", "owner/repo", "data")
    monkeypatch.setattr(store.session, "put", lambda *a, **k: Resp(401))
    with pytest.raises(StorageError, match="venció"):
        store.write("log/x.json", b"{}", "msg")


def test_recent_writes_are_visible_before_github_catches_up(monkeypatch):
    store = GitHubStore("tok", "owner/repo", "data")
    monkeypatch.setattr(store.session, "put", lambda *a, **k: Resp(201))
    monkeypatch.setattr(store.session, "get", lambda *a, **k: Resp(200, _tarball({})))
    store.write("log/task/new.json", b"{}", "msg")
    assert "log/task/new.json" in store.snapshot()
