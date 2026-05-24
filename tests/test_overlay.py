from fastapi.testclient import TestClient

from multistream_revenue_tracker.ui.app import create_app


def test_overlay_page_returns_html():
    app = create_app()
    client = TestClient(app)
    response = client.get("/overlay?w=1280&h=80&name=0")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    body = response.text
    assert "overlay-root" in body
    assert "ws/overlay" in body
    assert "URLSearchParams" in body
    assert "goal-name" in body
