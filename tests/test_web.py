import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import web


@pytest.fixture()
def web_client(tmp_path, monkeypatch):
    """A bare app with mount_web pointed at a throwaway build dir, with a
    secret file sitting just outside it."""
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text("INDEX")
    (web_dir / "about.html").write_text("ABOUT")
    (tmp_path / "secret.txt").write_text("SECRET")

    monkeypatch.setattr(web, "WEB_DIR", str(web_dir))
    monkeypatch.setattr(web, "INDEX", str(web_dir / "index.html"))
    app = FastAPI()
    web.mount_web(app)
    return TestClient(app), tmp_path


def test_serves_files_inside_the_build(web_client):
    client, _ = web_client
    assert client.get("/about").text == "ABOUT"
    assert client.get("/no-such-route").text == "INDEX"


def test_encoded_absolute_path_cannot_escape_the_build(web_client):
    """/%2F... reaches the handler as an absolute path, which os.path.join
    used to let replace WEB_DIR outright — an arbitrary file read."""
    client, tmp_path = web_client
    res = client.get(f"/%2F{str(tmp_path / 'secret.txt').lstrip('/')}")
    assert "SECRET" not in res.text
    assert "root:" not in client.get("/%2Fetc/passwd").text


def test_dot_dot_cannot_escape_the_build(web_client):
    client, _ = web_client
    assert "SECRET" not in client.get("/..%2Fsecret.txt").text
    assert "SECRET" not in client.get("/%2E%2E/secret").text
