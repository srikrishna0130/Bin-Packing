import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import MAX_PACKAGES_PER_REQUEST

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "A" in data["available_box_types"]


def test_api_pack_success():
    payload = [
        {"id": 123, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 5.0},
        {"id": 125, "width": 5.0, "height": 5.0, "length": 10.0, "weight": 10.0},
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["total_boxes"] == 1
    assert len(data["boxes"]) == 1
    assert data["boxes"][0]["box_type"] == "B"
    assert set(data["boxes"][0]["package_ids"]) == {123, 125}
    assert data["unpackable_packages"] == []


def test_api_empty_list_returns_validation_error():
    """Empty list [] must be rejected with 422 Unprocessable Entity."""
    response = client.post("/pack", json=[])
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data
    assert any("at least 1" in str(err) for err in data.get("errors", []))


def test_api_invalid_dimensions():
    """Negative dimensions must fail validation with 422."""
    payload = [
        {"id": 1, "width": -10.0, "height": 10.0, "length": 10.0, "weight": 5.0}
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 422


def test_api_zero_dimensions():
    """Zero dimensions must fail validation with 422."""
    payload = [
        {"id": 1, "width": 0.0, "height": 10.0, "length": 10.0, "weight": 5.0}
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 422


def test_api_duplicate_ids():
    """Duplicate IDs in a single shipment payload must return 400 Bad Request."""
    payload = [
        {"id": 101, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 5.0},
        {"id": 101, "width": 20.0, "height": 20.0, "length": 20.0, "weight": 5.0},
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 400
    assert "Duplicate package IDs found" in response.json()["detail"]


def test_api_partial_packing_200_with_unpackable():
    """
    Partial packing: valid package is shipped, unpackable package is returned in response
    with HTTP 200.
    """
    payload = [
        {"id": 1, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 5.0},
        {"id": 2, "width": 500.0, "height": 500.0, "length": 500.0, "weight": 5.0},
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["total_boxes"] == 1
    assert data["boxes"][0]["package_ids"] == [1]
    assert len(data["unpackable_packages"]) == 1
    assert data["unpackable_packages"][0]["id"] == 2


def test_api_max_batch_limit():
    """Exceeding MAX_PACKAGES_PER_REQUEST must fail validation with 422."""
    excessive_items = [
        {"id": i, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 5.0}
        for i in range(MAX_PACKAGES_PER_REQUEST + 1)
    ]
    response = client.post("/pack", json=excessive_items)
    assert response.status_code == 422
