from fastapi.testclient import TestClient

from demo_apis.buggy_shop_api.main import app as buggy_app
from demo_apis.normal_shop_api.main import app as normal_app


def test_normal_shop_api_exposes_openapi() -> None:
    client = TestClient(normal_app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Normal Shop API"


def test_buggy_shop_api_exposes_openapi() -> None:
    client = TestClient(buggy_app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Buggy Shop API"


def test_normal_shop_api_expected_statuses() -> None:
    client = TestClient(normal_app)

    register_payload = {"email": "normal-test@example.com", "password": "secret"}
    assert client.post("/register", json=register_payload).status_code == 201
    assert client.post("/register", json=register_payload).status_code == 409
    assert client.post("/login", json={"email": register_payload["email"]}).status_code == 422
    assert client.get("/items/999999").status_code == 404
    assert client.post("/items", json={"name": "bad", "price": -1}).status_code == 422
    assert client.get("/users/me").status_code == 401


def test_buggy_shop_api_intentional_failures_are_observable() -> None:
    client = TestClient(buggy_app)

    register_payload = {"email": "buggy-test@example.com", "password": "secret"}
    assert client.post("/register", json=register_payload).status_code == 201
    assert client.post("/register", json=register_payload).status_code == 201
    assert client.post("/login", json={"email": register_payload["email"]}).status_code == 500
    assert client.get("/items/999999").status_code == 200
    assert client.post("/items", json={"name": "bad", "price": -1}).status_code == 201
    assert client.get("/users/me").status_code == 500
