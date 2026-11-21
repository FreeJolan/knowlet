"""Regression tests for the web server's request-level security findings.

Covers: Host / Origin guard (CSRF + DNS rebinding), SPA fallback path
traversal, saved-LLM-key exfiltration through draft base_url, dev-only
sync endpoints in production builds, upload / import size caps and the
mkstemp fd leak on export.
"""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.vault import Vault
from knowlet.web import server as server_mod
from knowlet.web.server import create_app


def _vault(tmp_path: Path, *, api_key: str = "saved-secret-key") -> tuple[Vault, KnowletConfig]:
    v = Vault(tmp_path / "vault")
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = api_key
    cfg.llm.base_url = "https://saved.example/v1"
    save_config(v.root, cfg)
    return v, cfg


def _client(tmp_path: Path, **kw) -> tuple[TestClient, Vault, KnowletConfig]:
    v, cfg = _vault(tmp_path, **kw)
    app = create_app(v, cfg)
    app.state.web_state.runtime_or_init()
    return TestClient(app), v, cfg


# ------------------------------------------------------------ Host / Origin


def test_cross_site_post_is_refused_without_side_effect(tmp_path: Path) -> None:
    client, v, _ = _client(tmp_path)
    r = client.post(
        "/api/folders",
        json={"path": "pwned"},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    assert not (v.notes_dir / "pwned").exists()


def test_null_origin_post_is_refused(tmp_path: Path) -> None:
    client, v, _ = _client(tmp_path)
    r = client.post("/api/folders", json={"path": "x"}, headers={"Origin": "null"})
    assert r.status_code == 403
    assert not (v.notes_dir / "x").exists()


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:5173",  # vite dev server
        "http://localhost:8765",
        "http://[::1]:8765",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "http://testserver",  # same-origin
    ],
)
def test_local_and_same_origin_posts_are_allowed(tmp_path: Path, origin: str) -> None:
    client, v, _ = _client(tmp_path)
    r = client.post("/api/folders", json={"path": "ok"}, headers={"Origin": origin})
    assert r.status_code == 200, r.text
    assert (v.notes_dir / "ok").is_dir()


def test_post_without_origin_is_allowed(tmp_path: Path) -> None:
    """CLI / curl / the e2e fixture's Node fetch send no Origin."""
    client, v, _ = _client(tmp_path)
    r = client.post("/api/folders", json={"path": "cli"})
    assert r.status_code == 200
    assert (v.notes_dir / "cli").is_dir()


def test_dns_rebinding_host_is_refused_even_for_reads(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    r = client.get("/api/tree", headers={"Host": "evil.example:8765"})
    assert r.status_code == 403
    r = client.get("/api/health", headers={"Host": "127.0.0.1:8765"})
    assert r.status_code == 200
    r = client.get("/api/health", headers={"Host": "localhost"})
    assert r.status_code == 200
    r = client.get("/api/health", headers={"Host": "[::1]:8765"})
    assert r.status_code == 200


def test_extra_allowed_hosts_env_supports_lan_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KNOWLET_ALLOWED_HOSTS", "knowlet.lan, 192.168.1.5")
    client, _v, _ = _client(tmp_path)
    r = client.post(
        "/api/folders",
        json={"path": "lan"},
        headers={"Host": "192.168.1.5:8765", "Origin": "http://192.168.1.5:8765"},
    )
    assert r.status_code == 200, r.text
    r = client.get("/api/health", headers={"Host": "knowlet.lan"})
    assert r.status_code == 200
    # A foreign origin is still refused on the LAN host.
    r = client.post(
        "/api/folders",
        json={"path": "lan2"},
        headers={"Host": "192.168.1.5:8765", "Origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_oversized_request_body_is_rejected_before_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_mod, "MAX_REQUEST_BODY_BYTES", 1024)
    client, _, _ = _client(tmp_path)
    r = client.post("/api/folders", content=b"{" + b" " * 4096 + b"}")
    assert r.status_code == 413


# ------------------------------------------------------------ SPA fallback


def _dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>INDEX</html>", encoding="utf-8")
    (dist / "favicon.ico").write_bytes(b"ICO")
    monkeypatch.setenv("KNOWLET_FRONTEND_DIST", str(dist))
    return dist


def test_spa_fallback_serves_dist_files_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dist(tmp_path, monkeypatch)
    client, _, _ = _client(tmp_path)
    assert client.get("/favicon.ico").content == b"ICO"
    assert b"INDEX" in client.get("/some/deep/route").content


def test_spa_fallback_refuses_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dist(tmp_path, monkeypatch)
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    client, _, _ = _client(tmp_path)
    r = client.get("http://testserver/" + str(secret))  # → "//abs/path"
    assert b"TOP-SECRET" not in r.content


def test_spa_fallback_refuses_dotdot_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dist(tmp_path, monkeypatch)
    (tmp_path / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")
    client, _, _ = _client(tmp_path)
    r = client.get("/..%2Fsecret.txt")
    assert b"TOP-SECRET" not in r.content


# ------------------------------------------------------------ LLM key


class _FakeModels:
    def __init__(self, sink: dict) -> None:
        self.sink = sink

    def list(self):
        class _R:
            data: ClassVar[list] = []

        return _R()


def _capture_openai(monkeypatch: pytest.MonkeyPatch) -> dict:
    sink: dict = {}

    class _FakeOpenAI:
        def __init__(self, *, base_url: str, api_key: str, **_kw) -> None:
            sink["base_url"] = base_url
            sink["api_key"] = api_key
            self.models = _FakeModels(sink)

    import openai

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    return sink


def test_provider_models_never_sends_saved_key_to_a_different_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _capture_openai(monkeypatch)
    client, _, _ = _client(tmp_path)
    client.post("/api/llm/provider-models", json={"base_url": "https://attacker.example/v1"})
    assert sink.get("base_url") == "https://attacker.example/v1"
    assert sink.get("api_key") != "saved-secret-key"


def test_provider_models_reuses_saved_key_for_saved_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _capture_openai(monkeypatch)
    client, _, _ = _client(tmp_path)
    client.post("/api/llm/provider-models", json={"base_url": "https://saved.example/v1/"})
    assert sink["api_key"] == "saved-secret-key"
    sink.clear()
    client.post("/api/llm/provider-models", json={})
    assert sink["api_key"] == "saved-secret-key"
    sink.clear()
    client.post(
        "/api/llm/provider-models",
        json={"base_url": "https://other.example/v1", "api_key": "typed-key"},
    )
    assert sink["api_key"] == "typed-key"


def test_llm_test_never_sends_saved_key_to_a_different_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list = []

    class _FakeClient:
        def __init__(self, cfg) -> None:
            seen.append(cfg)

        def chat(self, **_kw):
            raise RuntimeError("offline")

    import knowlet.core.llm as llm_mod

    monkeypatch.setattr(llm_mod, "LLMClient", _FakeClient)
    client, _, _ = _client(tmp_path)
    r = client.post("/api/llm/test", json={"base_url": "https://attacker.example/v1"})
    assert r.json()["ok"] is False
    assert all(cfg.api_key != "saved-secret-key" for cfg in seen)

    seen.clear()
    client.post("/api/llm/test", json={"model": "other-model"})
    assert seen and seen[0].api_key == "saved-secret-key"


# ------------------------------------------------------------ dev endpoints


DEV_ROUTES = [
    ("post", "/api/sync/dev-seed-conflict/abc"),
    ("delete", "/api/sync/dev-seed-conflict/abc"),
    ("post", "/api/sync/dev-simulate-remote-edit/abc"),
    ("post", "/api/sync/dev-cleanup-orphan-sync-rows"),
    ("post", "/api/sync/dev-fake-other-device-heartbeat"),
]


@pytest.mark.parametrize(("method", "path"), DEV_ROUTES)
def test_dev_sync_endpoints_absent_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    monkeypatch.delenv("KNOWLET_DEV", raising=False)
    client, _, _ = _client(tmp_path)
    r = getattr(client, method)(path)
    assert r.status_code in (404, 405)


def test_dev_sync_endpoints_registered_with_env_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KNOWLET_DEV", "1")
    client, _, _ = _client(tmp_path)
    r = client.delete("/api/sync/dev-seed-conflict/abc")
    assert r.status_code == 200


# ------------------------------------------------------------ upload caps


def test_attachment_upload_over_limit_is_413_and_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_mod, "MAX_ATTACHMENT_BYTES", 1024)
    client, v, _ = _client(tmp_path)
    r = client.post(
        "/api/attachments",
        files={"file": ("a.png", b"\x89PNG" + b"0" * 4096, "image/png")},
    )
    assert r.status_code == 413
    assert not any(v.attachments_dir.glob("*.png"))


def test_capture_file_over_limit_is_413(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_mod, "MAX_CAPTURE_FILE_BYTES", 1024)
    client, _, _ = _client(tmp_path)
    r = client.post("/api/capture/file", files={"file": ("big.md", b"x" * 4096, "text/markdown")})
    assert r.status_code == 413


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.mark.parametrize("endpoint", ["/api/vault/import", "/api/vault/import-preview"])
def test_import_upload_over_limit_is_413(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    monkeypatch.setattr(server_mod, "MAX_IMPORT_UPLOAD_BYTES", 512)
    client, _, _ = _client(tmp_path)
    payload = _zip_bytes({f"notes/n{i}.md": os.urandom(256) for i in range(8)})
    r = client.post(endpoint, files={"file": ("v.zip", payload, "application/zip")})
    assert r.status_code == 413


@pytest.mark.parametrize("endpoint", ["/api/vault/import", "/api/vault/import-preview"])
def test_import_zip_bomb_is_413_before_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    monkeypatch.setattr(server_mod, "MAX_IMPORT_UNCOMPRESSED_BYTES", 64 * 1024)
    client, v, _ = _client(tmp_path)
    bomb = _zip_bytes({"notes/bomb.md": b"0" * (1024 * 1024)})
    assert len(bomb) < 64 * 1024
    r = client.post(endpoint, files={"file": ("v.zip", bomb, "application/zip")})
    assert r.status_code == 413
    assert not list(v.notes_dir.rglob("bomb*.md"))


def test_import_too_many_entries_is_413(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_mod, "MAX_IMPORT_ENTRIES", 3)
    client, _, _ = _client(tmp_path)
    payload = _zip_bytes({f"notes/n{i}.md": b"x" for i in range(5)})
    r = client.post("/api/vault/import", files={"file": ("v.zip", payload, "application/zip")})
    assert r.status_code == 413


def test_import_rejects_non_zip_with_400(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    r = client.post(
        "/api/vault/import-preview", files={"file": ("v.zip", b"not a zip", "application/zip")}
    )
    assert r.status_code == 400


# ------------------------------------------------------------ fd leak


def _open_fd_count() -> int:
    for candidate in ("/dev/fd", "/proc/self/fd"):
        if os.path.isdir(candidate):
            return len(os.listdir(candidate))
    pytest.skip("no fd listing on this platform")


def test_export_and_import_do_not_leak_file_descriptors(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)
    archive = client.get("/api/vault/export").content
    before = _open_fd_count()
    for _ in range(15):
        assert client.get("/api/vault/export").status_code == 200
        client.post(
            "/api/vault/import-preview",
            files={"file": ("v.zip", archive, "application/zip")},
        )
    after = _open_fd_count()
    assert after - before < 10, f"fd count grew {before} → {after}"
