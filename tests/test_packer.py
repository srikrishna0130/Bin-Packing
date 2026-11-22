import pytest
from typing import List, Dict
from app.models.box import BoxDefinition
from app.models.package import PackageInput, PackingResponse
from app.services.packer import BinPackerService


@pytest.fixture
def default_catalogue() -> List[BoxDefinition]:
    """Fixed catalogue from the assignment specification."""
    return [
        BoxDefinition(type="A", width=150.0, height=150.0, length=150.0, max_weight=1000.0),
        BoxDefinition(type="B", width=100.0, height=200.0, length=100.0, max_weight=1000.0),
        BoxDefinition(type="C", width=300.0, height=400.0, length=300.0, max_weight=3000.0),
    ]


@pytest.fixture
def packer_service(default_catalogue) -> BinPackerService:
    return BinPackerService(default_catalogue)


def verify_packing_invariants(
    response: PackingResponse,
    input_packages: List[PackageInput],
    catalogue: List[BoxDefinition],
):
    """
    Core verification helper for bin packing:
    Regardless of whether an optimal or heuristic packing is used,
    the output must strictly satisfy these physical and logical invariants.
    """
    catalogue_map: Dict[str, BoxDefinition] = {b.type: b for b in catalogue}
    input_pkg_map = {p.id: p for p in input_packages}

    # Invariant 1: Total box count matches length of boxes list
    assert response.total_boxes == len(response.boxes), (
        f"total_boxes ({response.total_boxes}) does not match len(boxes) ({len(response.boxes)})"
    )

    # Invariant 2: Item conservation
    # Every input package must be either in a packed box or in unpackable_packages
    packed_ids = []
    for box in response.boxes:
        packed_ids.extend(box.package_ids)

    unpackable_ids = [u.id for u in response.unpackable_packages]

    # No duplicate IDs across packed boxes
    assert len(packed_ids) == len(set(packed_ids)), "A package ID appears more than once across boxes!"

    # No overlap between packed and unpackable
    assert set(packed_ids).isdisjoint(set(unpackable_ids)), (
        "A package ID appears in both packed boxes and unpackable packages!"
    )

    # All input packages are accounted for
    all_accounted_ids = set(packed_ids) | set(unpackable_ids)
    assert all_accounted_ids == set(input_pkg_map.keys()), (
        f"Mismatch between input packages and accounted packages: {set(input_pkg_map.keys()) - all_accounted_ids}"
    )

    # Invariant 3: Physical constraints for every packed box
    for box in response.boxes:
        box_def = catalogue_map.get(box.box_type)
        assert box_def is not None, f"Box type {box.box_type} not found in catalogue"

        box_packages = [input_pkg_map[pkg_id] for pkg_id in box.package_ids]
        sum_weight = sum(p.weight for p in box_packages)
        sum_volume = sum(p.volume for p in box_packages)

        # Weight limit must not be breached
        assert sum_weight <= box_def.max_weight, (
            f"Box {box.box_type} exceeded max weight: {sum_weight} > {box_def.max_weight}"
        )

        # Volume limit must not be breached
        assert sum_volume <= box_def.volume, (
            f"Box {box.box_type} exceeded volume capacity: {sum_volume} > {box_def.volume}"
        )

        # Individual package dimensions must fit inside the box (with 3D rotation)
        for p in box_packages:
            assert box_def.can_accommodate_dimensions(p.sorted_dimensions), (
                f"Package {p.id} with dimensions {p.sorted_dimensions} does not physically fit in box {box.box_type} {box_def.sorted_dimensions}"
            )


def test_assignment_sample(packer_service, default_catalogue):
    """Test the exact sample payload from the assignment doc."""
    packages = [
        PackageInput(id=123, width=10.0, height=10.0, length=10.0, weight=5.0),
        PackageInput(id=125, width=5.0, height=5.0, length=10.0, weight=10.0),
    ]
    response = packer_service.pack(packages)
    verify_packing_invariants(response, packages, default_catalogue)

    # Both items are tiny and should fit in a single Box B (smallest by volume)
    assert response.total_boxes == 1
    assert response.boxes[0].box_type == "B"
    assert set(response.boxes[0].package_ids) == {123, 125}
    assert len(response.unpackable_packages) == 0


def test_box_selection_by_dimension_fit(packer_service, default_catalogue):
    """
    Package dimensions: 120 x 120 x 120.
    Box B is 100 x 200 x 100 -> item cannot fit in Box B (120 > 100).
    Box A is 150 x 150 x 150 -> item fits in Box A.
    Verifies that the packer selects Box A even though Box B is smaller in volume.
    """
    packages = [
        PackageInput(id=1, width=120.0, height=120.0, length=120.0, weight=50.0),
    ]
    response = packer_service.pack(packages)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 1
    assert response.boxes[0].box_type == "A"
    assert response.boxes[0].package_ids == [1]


def test_progressive_upgrade_swaps_to_larger_box(packer_service, default_catalogue):
    """
    Test progressive upgrade:
    Items 1 and 2 fit into Box B.
    Adding item 3 exceeds Box B (e.g. combined volume or weight),
    but all three fit comfortably into Box A.
    The packer should upgrade to Box A instead of shipping two separate boxes.
    """
    # Box B volume: 2,000,000. Box A volume: 3,375,000.
    # Package volume: 900,000 each (e.g. 90 x 100 x 100).
    # Two packages: 1,800,000 <= 2,000,000 (fits in B).
    # Three packages: 2,700,000 > 2,000,000 (exceeds B, but fits in A's 3,375,000).
    packages = [
        PackageInput(id="p1", width=90.0, height=100.0, length=100.0, weight=10.0),
        PackageInput(id="p2", width=90.0, height=100.0, length=100.0, weight=10.0),
        PackageInput(id="p3", width=90.0, height=100.0, length=100.0, weight=10.0),
    ]
    response = packer_service.pack(packages)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 1
    assert response.boxes[0].box_type == "A"
    assert set(response.boxes[0].package_ids) == {"p1", "p2", "p3"}


def test_partial_packing_with_unpackable_item(packer_service, default_catalogue):
    """
    Test the partial shipment requirement:
    One item is packable, and one item is unpackable (exceeds Box C capacity).
    The service must pack the valid item into a box and return the unpackable
    item in `unpackable_packages` (partial 200 approach).
    """
    packages = [
        PackageInput(id="valid_1", width=20.0, height=20.0, length=20.0, weight=10.0),
        PackageInput(id="oversized_2", width=500.0, height=500.0, length=500.0, weight=10.0),
        PackageInput(id="overweight_3", width=50.0, height=50.0, length=50.0, weight=4000.0),
    ]
    response = packer_service.pack(packages)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 1
    assert response.boxes[0].package_ids == ["valid_1"]

    unpackable_ids = [u.id for u in response.unpackable_packages]
    assert "oversized_2" in unpackable_ids
    assert "overweight_3" in unpackable_ids


def test_all_items_unpackable(packer_service, default_catalogue):
    """If all items are unpackable, return 0 boxes and all items in unpackable_packages."""
    packages = [
        PackageInput(id="huge_1", width=600.0, height=600.0, length=600.0, weight=50.0),
        PackageInput(id="heavy_2", width=50.0, height=50.0, length=50.0, weight=5000.0),
    ]
    response = packer_service.pack(packages)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 0
    assert len(response.boxes) == 0
    assert len(response.unpackable_packages) == 2


def test_multiple_boxes_required(packer_service, default_catalogue):
    """
    When packages together exceed the largest box (Box C),
    multiple boxes must be opened.
    """
    # Box C max weight: 3000.
    # 4 packages each weighing 1200 -> total 4800 weight -> cannot fit in 1 Box C.
    packages = [
        PackageInput(id=f"item_{i}", width=100.0, height=100.0, length=100.0, weight=1200.0)
        for i in range(4)
    ]
    response = packer_service.pack(packages)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes > 1
