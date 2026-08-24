from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"


def _body(name: str = "Ada Lovelace", email: str = "ada@example.com") -> dict[str, str]:
    return {"name": name, "email": email, "password": PASSWORD}


def _create(client: TestClient, email: str = "ada@example.com") -> dict:
    return client.post("/api/v1/users", json=_body(email=email)).json()


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
    assert response.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_list_users_returns_every_created_user(client: TestClient) -> None:
    client.post("/api/v1/users", json=_body(email="ada@example.com"))
    client.post("/api/v1/users", json=_body(name="Alan", email="alan@example.com"))

    response = client.get("/api/v1/users")

    assert [user["email"] for user in response.json()["items"]] == [
        "ada@example.com",
        "alan@example.com",
    ]


def test_list_users_never_exposes_a_password(client: TestClient) -> None:
    client.post("/api/v1/users", json=_body())

    response = client.get("/api/v1/users")

    assert PASSWORD not in response.text
    assert "hashed_password" not in response.text


def test_list_users_returns_one_page_at_a_time(client: TestClient) -> None:
    for index in range(3):
        _create(client, email=f"user{index}@example.com")

    response = client.get("/api/v1/users", params={"page": 1, "page_size": 2})

    page = response.json()
    assert [user["email"] for user in page["items"]] == [
        "user0@example.com",
        "user1@example.com",
    ]
    assert page["total"] == 3
    assert page["page"] == 1
    assert page["page_size"] == 2


def test_list_users_second_page_continues_where_the_first_ended(
    client: TestClient,
) -> None:
    for index in range(3):
        _create(client, email=f"user{index}@example.com")

    response = client.get("/api/v1/users", params={"page": 2, "page_size": 2})

    page = response.json()
    assert [user["email"] for user in page["items"]] == ["user2@example.com"]
    assert page["total"] == 3


def test_list_users_past_the_last_page_is_empty(client: TestClient) -> None:
    _create(client)

    response = client.get("/api/v1/users", params={"page": 5, "page_size": 20})

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_users_rejects_a_page_below_one(client: TestClient) -> None:
    assert client.get("/api/v1/users", params={"page": 0}).status_code == 422


def test_list_users_rejects_an_oversized_page(client: TestClient) -> None:
    assert client.get("/api/v1/users", params={"page_size": 101}).status_code == 422


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


def test_update_user_changes_only_what_was_sent(client: TestClient) -> None:
    created = _create(client)

    response = client.patch(
        f"/api/v1/users/{created['id']}",
        json={"name": "Ada L"},
    )

    assert response.status_code == 200

    updated = response.json()
    assert updated["name"] == "Ada L"
    assert updated["email"] == created["email"]
    assert updated["id"] == created["id"]


def test_update_user_is_visible_on_the_next_read(client: TestClient) -> None:
    created = _create(client)

    client.patch(f"/api/v1/users/{created['id']}", json={"name": "Ada L"})

    response = client.get(f"/api/v1/users/{created['id']}")

    assert response.json()["name"] == "Ada L"


def test_update_user_can_change_the_email(client: TestClient) -> None:
    created = _create(client)

    response = client.patch(
        f"/api/v1/users/{created['id']}",
        json={"email": "ada.lovelace@example.com"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "ada.lovelace@example.com"


def test_update_user_never_returns_the_new_password(client: TestClient) -> None:
    created = _create(client)

    response = client.patch(
        f"/api/v1/users/{created['id']}",
        json={"password": "a brand new password"},
    )

    assert response.status_code == 200
    assert "a brand new password" not in response.text
    assert "password" not in response.json()
    assert "hashed_password" not in response.json()


def test_update_user_with_an_empty_body_changes_nothing(
    client: TestClient,
) -> None:
    created = _create(client)

    response = client.patch(f"/api/v1/users/{created['id']}", json={})

    assert response.status_code == 200
    assert response.json() == created


def test_update_unknown_user_returns_404(client: TestClient) -> None:
    response = client.patch("/api/v1/users/999", json={"name": "Nobody"})

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_update_to_a_taken_email_returns_409(client: TestClient) -> None:
    _create(client, email="ada@example.com")
    alan = _create(client, email="alan@example.com")

    response = client.patch(
        f"/api/v1/users/{alan['id']}",
        json={"email": "ada@example.com"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Email already registered"


def test_update_to_the_users_own_email_is_allowed(client: TestClient) -> None:
    created = _create(client)

    response = client.patch(
        f"/api/v1/users/{created['id']}",
        json={"email": "ada@example.com"},
    )

    assert response.status_code == 200


def test_update_user_rejects_an_invalid_email(client: TestClient) -> None:
    created = _create(client)

    response = client.patch(
        f"/api/v1/users/{created['id']}",
        json={"email": "not-an-email"},
    )

    assert response.status_code == 422


def test_update_user_rejects_a_short_password(client: TestClient) -> None:
    created = _create(client)

    response = client.patch(
        f"/api/v1/users/{created['id']}",
        json={"password": "short"},
    )

    assert response.status_code == 422


def test_delete_user_returns_204_with_no_body(client: TestClient) -> None:
    created = _create(client)

    response = client.delete(f"/api/v1/users/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""


def test_deleted_user_is_gone(client: TestClient) -> None:
    created = _create(client)

    client.delete(f"/api/v1/users/{created['id']}")

    assert client.get(f"/api/v1/users/{created['id']}").status_code == 404
    assert client.get("/api/v1/users").json()["total"] == 0


def test_delete_frees_the_email_address(client: TestClient) -> None:
    created = _create(client)

    client.delete(f"/api/v1/users/{created['id']}")

    assert client.post("/api/v1/users", json=_body()).status_code == 201


def test_delete_unknown_user_returns_404(client: TestClient) -> None:
    response = client.delete("/api/v1/users/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_delete_leaves_other_users_alone(client: TestClient) -> None:
    ada = _create(client, email="ada@example.com")
    _create(client, email="alan@example.com")

    client.delete(f"/api/v1/users/{ada['id']}")

    page = client.get("/api/v1/users").json()
    assert [user["email"] for user in page["items"]] == ["alan@example.com"]
    assert page["total"] == 1
