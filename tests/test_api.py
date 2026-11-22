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


# ============================================================================
# API Validation & Error Cases
# ============================================================================

def test_api_empty_list_returns_validation_error():
    """Empty list [] must be rejected with 422 Unprocessable Entity."""
    response = client.post("/pack", json=[])
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data
    assert any("at least 1" in str(err) for err in data.get("errors", []))


def test_api_negative_dimensions():
    """Negative dimensions must fail validation with 422."""
    payload = [
        {"id": 1, "width": -10.0, "height": 10.0, "length": 10.0, "weight": 5.0}
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 422
    assert "greater than 0" in str(response.json())


def test_api_zero_dimensions():
    """Zero dimensions must fail validation with 422."""
    payload = [
        {"id": 1, "width": 0.0, "height": 10.0, "length": 10.0, "weight": 5.0}
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 422
    assert "greater than 0" in str(response.json())


def test_api_negative_weight():
    """Negative weight must fail validation with 422."""
    payload = [
        {"id": 1, "width": 10.0, "height": 10.0, "length": 10.0, "weight": -5.0}
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 422
    assert "greater than 0" in str(response.json())


def test_api_zero_weight():
    """Zero weight must fail validation with 422."""
    payload = [
        {"id": 1, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 0.0}
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 422
    assert "greater than 0" in str(response.json())


def test_api_missing_required_fields():
    """Payloads missing required fields (e.g. height, weight) must fail with 422."""
    payload = [
        {"id": 1, "width": 10.0, "length": 10.0}  # missing height and weight
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 422
    assert "Field required" in str(response.json())


def test_api_invalid_data_types():
    """Non-numeric dimension values must fail validation with 422."""
    payload = [
        {"id": 1, "width": "not-a-number", "height": 10.0, "length": 10.0, "weight": 5.0}
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 422


def test_api_null_values():
    """Null values for dimensions must fail validation with 422."""
    payload = [
        {"id": 1, "width": None, "height": 10.0, "length": 10.0, "weight": 5.0}
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 422


def test_api_non_list_payload():
    """Passing a single JSON object instead of an array of packages must fail with 422."""
    payload = {"id": 1, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 5.0}
    response = client.post("/pack", json=payload)
    assert response.status_code == 422


def test_api_excessive_dimensions():
    """Dimensions exceeding the sanity bound (> 10,000) must fail with 422."""
    payload = [
        {"id": 1, "width": 50000.0, "height": 10.0, "length": 10.0, "weight": 5.0}
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 422
    assert "less than or equal to 10000" in str(response.json())


def test_api_excessive_weight():
    """Weight exceeding the sanity bound (> 100,000) must fail with 422."""
    payload = [
        {"id": 1, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 500000.0}
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 422
    assert "less than or equal to 100000" in str(response.json())


def test_api_duplicate_ids():
    """Duplicate IDs in a single shipment payload must return 400 Bad Request."""
    payload = [
        {"id": 101, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 5.0},
        {"id": 101, "width": 20.0, "height": 20.0, "length": 20.0, "weight": 5.0},
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 400
    assert "Duplicate package IDs found" in response.json()["detail"]


def test_api_max_batch_limit():
    """Exceeding MAX_PACKAGES_PER_REQUEST must fail validation with 422."""
    excessive_items = [
        {"id": i, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 5.0}
        for i in range(MAX_PACKAGES_PER_REQUEST + 1)
    ]
    response = client.post("/pack", json=excessive_items)
    assert response.status_code == 422


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


def test_api_combined_packages_exceed_box_dimensions_despite_valid_volume():
    """
    Two packages of 250 x 250 x 250:
    Combined volume (31.25M) < Box C volume (36M).
    Combined: 250 + 250 = 500 > 400, cannot coexist in Box C.
    The API must return 2 boxes.
    """
    payload = [
        {"id": 1, "width": 250.0, "height": 250.0, "length": 250.0, "weight": 50.0},
        {"id": 2, "width": 250.0, "height": 250.0, "length": 250.0, "weight": 50.0},
    ]
    response = client.post("/pack", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["total_boxes"] == 2
    assert len(data["boxes"]) == 2


# ============================================================================
# Strategy Selection Query Parameter Tests
# ============================================================================

def test_api_strategy_selection_bounding_box():
    """Explicitly selecting ?strategy=bounding_box works."""
    payload = [
        {"id": 1, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 5.0},
    ]
    response = client.post("/pack?strategy=bounding_box", json=payload)
    assert response.status_code == 200
    assert response.json()["total_boxes"] == 1


def test_api_strategy_selection_volumetric_derating():
    """Explicitly selecting ?strategy=volumetric_derating works."""
    payload = [
        {"id": 1, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 5.0},
    ]
    response = client.post("/pack?strategy=volumetric_derating", json=payload)
    assert response.status_code == 200
    assert response.json()["total_boxes"] == 1


def test_api_strategy_invalid_returns_422():
    """Supplying an unknown strategy returns 422 Unprocessable Entity."""
    payload = [
        {"id": 1, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 5.0},
    ]
    response = client.post("/pack?strategy=non_existent_strategy", json=payload)
    assert response.status_code == 422
