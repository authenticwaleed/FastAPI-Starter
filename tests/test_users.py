from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"


def _body(name: str = "Ada Lovelace", email: str = "ada@example.com") -> dict[str, str]:
    return {"name": name, "email": email, "password": PASSWORD}


def test_create_user_returns_201_and_persists_the_user(client: TestClient) -> None:
    response = client.post("/api/v1/users", json=_body())

    assert response.status_code == 201

    created = response.json()
    assert created["id"] > 0
    assert created["name"] == "Ada Lovelace"
    assert created["email"] == "ada@example.com"
    assert created["is_active"] is True
    assert created["created_at"] is not None


def test_response_never_contains_the_password_or_its_hash(
    client: TestClient,
) -> None:
    response = client.post("/api/v1/users", json=_body())

    assert PASSWORD not in response.text
    assert "password" not in response.json()
    assert "hashed_password" not in response.json()


def test_get_user_returns_the_created_user(client: TestClient) -> None:
    created = client.post("/api/v1/users", json=_body()).json()

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
    client.post("/api/v1/users", json=_body(email="ada@example.com"))
    client.post("/api/v1/users", json=_body(name="Alan", email="alan@example.com"))

    response = client.get("/api/v1/users")

    assert [user["email"] for user in response.json()] == [
        "ada@example.com",
        "alan@example.com",
    ]


def test_duplicate_email_returns_409(client: TestClient) -> None:
    client.post("/api/v1/users", json=_body())

    response = client.post("/api/v1/users", json=_body())

    assert response.status_code == 409
    assert response.json()["detail"] == "Email already registered"


def test_create_user_rejects_invalid_email(client: TestClient) -> None:
    response = client.post("/api/v1/users", json=_body(email="not-an-email"))

    assert response.status_code == 422


def test_create_user_rejects_blank_name(client: TestClient) -> None:
    response = client.post("/api/v1/users", json=_body(name=""))

    assert response.status_code == 422


def test_create_user_rejects_a_short_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/users",
        json={"name": "Ada", "email": "ada@example.com", "password": "short"},
    )

    assert response.status_code == 422


def test_create_user_requires_a_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/users",
        json={"name": "Ada", "email": "ada@example.com"},
    )

    assert response.status_code == 422
