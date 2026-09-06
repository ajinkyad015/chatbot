import uuid

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def _unique_username() -> str:
    return f"user-{uuid.uuid4().hex[:12]}"


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_id_header_is_present():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_register_and_login_successful():
    username = _unique_username()
    password = "correct-horse-battery-staple"

    register_response = client.post(
        "/register",
        json={"username": username, "password": password},
    )
    assert register_response.status_code == 201
    assert register_response.json() == {"username": username}

    login_response = client.post(
        "/login",
        json={"username": username, "password": password},
    )
    assert login_response.status_code == 200

    data = login_response.json()
    assert data["token_type"] == "bearer"
    assert data["access_token"]


def test_register_rejects_duplicate_username():
    username = _unique_username()
    password = "correct-horse-battery-staple"

    client.post(
        "/register",
        json={"username": username, "password": password},
    )

    duplicate = client.post(
        "/register",
        json={"username": username, "password": password},
    )
    assert duplicate.status_code == 409


def test_login_rejects_wrong_password():
    response = client.post(
        "/login",
        json={
            "username": _unique_username(),
            "password": "wrong-password",
        },
    )
    assert response.status_code == 401


def test_register_validates_password_length():
    response = client.post(
        "/register",
        json={"username": _unique_username(), "password": "short"},
    )
    assert response.status_code == 422


def test_protected_route_requires_bearer_token():
    response = client.post("/conversations")

    assert response.status_code in (401, 403)
