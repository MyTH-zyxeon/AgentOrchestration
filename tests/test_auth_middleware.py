from fastapi.testclient import TestClient

from src.api.server import create_app


def test_trailing_slash_protected_route_rejects_anonymous_before_redirect():
    client = TestClient(create_app(), follow_redirects=False)

    response = client.get("/api/v2/agents/")

    assert response.status_code == 401
    assert response.text == "Unauthorized"


def test_trailing_slash_protected_route_rejects_blank_bearer_token():
    client = TestClient(create_app(), follow_redirects=False)

    response = client.get(
        "/api/v2/agents/",
        headers={"Authorization": "Bearer "},
    )

    assert response.status_code == 401
    assert response.text == "Unauthorized"


def test_trailing_slash_protected_route_allows_valid_bearer_redirect():
    client = TestClient(create_app(), follow_redirects=False)

    response = client.get(
        "/api/v2/agents/",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code in {200, 307}
    assert response.status_code != 401
