import importlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from chess_coach.api import dependencies

app_module = importlib.import_module("chess_coach.api.app")
HTML = {"Accept": "text/html,application/xhtml+xml"}


@pytest.fixture
def packaged(api, monkeypatch, tmp_path):
    _, _, _, _, settings, *_ = api
    settings.serve_frontend = True
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    build = tmp_path / "build"
    assets = build / "_app" / "immutable"
    assets.mkdir(parents=True)
    (build / "index.html").write_text(
        '<html><link href="/_app/immutable/app.js" rel="modulepreload">'
        '<link href="/_app/immutable/app.css" rel="stylesheet">Chess Coach shell</html>'
    )
    (assets / "app.js").write_text("export {};")
    (assets / "app.css").write_text("body {}")
    app = app_module.create_app(frontend_build=build)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client, build, settings


def test_packaged_serves_pages_assets_and_api(packaged):
    client, _, _ = packaged
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").json() == {"status": "ready"}
    assert client.get("/api/v1/games", headers=HTML).json()["total"] == 0

    for path in ("/", "/games", "/games/42", "/coach", "/training"):
        page = client.get(path, headers=HTML)
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert "Chess Coach shell" in page.text
    assert client.get("/games").status_code == 404
    assert client.head("/coach", headers=HTML).status_code == 200
    js = client.get("/_app/immutable/app.js", headers=HTML)
    assert js.status_code == 200 and js.text == "export {};"


def test_frontend_does_not_mask_missing_api_assets_or_private_files(packaged):
    client, build, _ = packaged
    # Even a misplaced build artifact cannot capture a browser API request.
    api_assets = build / "api" / "v1"
    api_assets.mkdir(parents=True)
    (api_assets / "unknown").write_text("should not be served")
    assert (
        client.get("/api/v1/games/", headers=HTML, follow_redirects=False).status_code
        == 307
    )
    assert client.post("/api/v1/unknown", headers=HTML).status_code == 404
    for path in ("/api", "/api/v1", "/api/v1/unknown"):
        response = client.get(path, headers=HTML)
        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"
    for path in (
        "/nonexistent.js",
        "/_app/immutable/missing",
        "/.env",
        "/.git/config",
        "/data/chess_coach.db",
        "/pyproject.toml",
        "/uv.lock",
    ):
        assert client.get(path, headers=HTML).status_code == 404


def test_packaged_rejects_host_spoofing_and_cross_site_mutation(packaged):
    client, _, _ = packaged
    for host in ("untrusted.example", "untrusted.example@127.0.0.1", "127.0.0.1:bad"):
        response = client.get("/health/live", headers={"Host": host})
        assert response.status_code == 400
        assert response.json()["code"] == "HOST_NOT_ALLOWED"
    path = "/api/v1/player"
    for headers in (
        {"Origin": "https://untrusted.example"},
        {"Origin": "http://127.0.0.1:9999"},
        {"Origin": "http://127.0.0.1:5173", "Sec-Fetch-Site": "same-site"},
        {"Origin": "http://127.0.0.1:4173", "Sec-Fetch-Site": "same-site"},
        {"Sec-Fetch-Site": "cross-site"},
    ):
        response = client.put(path, json={"username": "testplayer"}, headers=headers)
        assert response.status_code == 403
        assert response.json()["code"] == "ORIGIN_NOT_ALLOWED"
        assert "access-control-allow-origin" not in response.headers
    assert (
        client.put(
            path,
            content='{"username":"testplayer"}',
            headers={"Content-Type": "text/plain"},
        ).status_code
        == 422
    )
    assert (
        client.put(
            path,
            json={"username": "testplayer"},
            headers={
                "Origin": "http://127.0.0.1:8000",
                "Sec-Fetch-Site": "same-origin",
            },
        ).status_code
        == 200
    )


def test_packaged_readiness_detects_storage_and_build_regressions(packaged):
    client, build, settings = packaged
    (build / "_app" / "immutable" / "app.js").unlink()
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["code"] == "FRONTEND_BUILD_MISSING"
    assert client.get("/health/live").status_code == 200
    with sqlite3.connect(settings.database_path) as db:
        db.execute("UPDATE alembic_version SET version_num = 'stale'")
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["code"] == "MIGRATIONS_INCOMPATIBLE"


def test_missing_or_incomplete_build_refuses_packaged_mode(api, tmp_path, monkeypatch):
    settings = api[4]
    settings.serve_frontend = True
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    build = tmp_path / "not-built"
    with pytest.raises(RuntimeError, match="pnpm --dir frontend build"):
        app_module.create_app(frontend_build=build)
    build.mkdir()
    (build / "index.html").touch()
    (build / "_app" / "immutable").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="pnpm --dir frontend build"):
        app_module.create_app(frontend_build=build)


def test_packaged_startup_never_initializes_a_missing_database(packaged, tmp_path):
    _, build, settings = packaged
    settings.database_path = tmp_path / "missing.db"
    app = app_module.create_app(frontend_build=build)
    with (
        pytest.raises(RuntimeError, match="DATABASE_MISSING.*alembic upgrade head"),
        TestClient(app, base_url="http://127.0.0.1:8000"),
    ):
        pytest.fail("Packaged startup accepted an uninitialized database")
    assert not settings.database_path.exists()
