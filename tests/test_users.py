from fastapi.testclient import TestClient


def test_create_user_returns_201_and_assigns_id(client: TestClient) -> None:
    response = client.post(
        "/api/v1/users",
        json={"name": "Ada Lovelace", "email": "ada@example.com"},
    )

    assert response.status_code == 201

    body = response.json()
    assert body["id"] == 1
    assert body["name"] == "Ada Lovelace"
    assert body["email"] == "ada@example.com"
    assert body["is_active"] is True


def test_get_user_returns_created_user(client: TestClient) -> None:
    created = client.post(
        "/api/v1/users",
        json={"name": "Ada Lovelace", "email": "ada@example.com"},
    ).json()

    response = client.get(f"/api/v1/users/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_unknown_user_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/users/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_list_users_starts_empty(client: TestClient) -> None:
    response = client.get("/api/v1/users")

    assert response.status_code == 200
    assert response.json() == []


def test_list_users_returns_every_created_user(client: TestClient) -> None:
    client.post(
        "/api/v1/users",
        json={"name": "Ada Lovelace", "email": "ada@example.com"},
    )
    client.post(
        "/api/v1/users",
        json={"name": "Alan Turing", "email": "alan@example.com"},
    )

    response = client.get("/api/v1/users")

    assert response.status_code == 200
    assert [user["email"] for user in response.json()] == [
        "ada@example.com",
        "alan@example.com",
    ]


def test_create_user_rejects_invalid_email(client: TestClient) -> None:
    response = client.post(
        "/api/v1/users",
        json={"name": "Ada Lovelace", "email": "not-an-email"},
    )

    assert response.status_code == 422


def test_create_user_rejects_blank_name(client: TestClient) -> None:
    response = client.post(
        "/api/v1/users",
        json={"name": "", "email": "ada@example.com"},
    )

    assert response.status_code == 422


def test_create_user_requires_email(client: TestClient) -> None:
    response = client.post(
        "/api/v1/users",
        json={"name": "Ada Lovelace"},
    )

    assert response.status_code == 422
