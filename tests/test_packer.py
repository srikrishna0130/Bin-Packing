import pytest
from typing import List, Dict
from app.models.box import BoxDefinition
from app.models.package import PackageInput, PackingResponse
from app.services.packer import BinPackerService, can_pack_geometrically_3d


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
    Strictly verifies physical and logical invariants regardless of heuristic:
    1. Count consistency
    2. Item conservation (no dropped, no duplicated items)
    3. Weight capacity
    4. Volume capacity
    5. Single-item rotational fit
    6. Multi-item 3D spatial collision-free coexistence
    """
    catalogue_map: Dict[str, BoxDefinition] = {b.type: b for b in catalogue}
    input_pkg_map = {p.id: p for p in input_packages}

    # Invariant 1: Total box count matches length of boxes list
    assert response.total_boxes == len(response.boxes), (
        f"total_boxes ({response.total_boxes}) does not match len(boxes) ({len(response.boxes)})"
    )

    # Invariant 2: Item conservation
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
                f"Package {p.id} with dimensions {p.sorted_dimensions} does not fit in box {box.box_type}"
            )

        # Invariant 4: True 3D spatial feasibility (no physical collisions)
        assert can_pack_geometrically_3d(box_def, box_packages), (
            f"Box {box.box_type} contains packages that physically collide in 3D space!"
        )


def test_assignment_sample(packer_service, default_catalogue):
    """Test the exact sample payload from the assignment doc."""
    packages = [
        PackageInput(id=123, width=10.0, height=10.0, length=10.0, weight=5.0),
        PackageInput(id=125, width=5.0, height=5.0, length=10.0, weight=10.0),
    ]
    response = packer_service.pack(packages)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 1
    assert response.boxes[0].box_type == "B"
    assert set(response.boxes[0].package_ids) == {123, 125}
    assert len(response.unpackable_packages) == 0


def test_box_selection_by_dimension_fit(packer_service, default_catalogue):
    """
    Package dimensions: 120 x 120 x 120.
    Box B is 100 x 200 x 100 -> item cannot fit in Box B (120 > 100).
    Box A is 150 x 150 x 150 -> item fits in Box A.
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
    Items 1 and 2 fit into Box B (70x70x70 fits along the 200 height: 70+70=140 <= 200).
    Adding item 3 overflows Box B (needs 3x70=210 > 200),
    but all three fit comfortably into Box A (which holds a 2x2 grid: 140x140 <= 150x150).
    The packer should upgrade to Box A instead of opening multiple boxes.
    """
    packages = [
        PackageInput(id="p1", width=70.0, height=70.0, length=70.0, weight=10.0),
        PackageInput(id="p2", width=70.0, height=70.0, length=70.0, weight=10.0),
        PackageInput(id="p3", width=70.0, height=70.0, length=70.0, weight=10.0),
    ]
    response = packer_service.pack(packages)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 1
    assert response.boxes[0].box_type == "A"
    assert set(response.boxes[0].package_ids) == {"p1", "p2", "p3"}


def test_geometric_collision_failure_forces_box_upgrade(packer_service, default_catalogue):
    """
    FAILURE CASE:
    Two cubes of size 110 x 110 x 110:
    - Total volume: 2,662,000 <= 3,375,000 (Box A volume).
    - Total weight: 20 <= 1000.
    - Each cube individually fits in Box A (110 <= 150).
    - BUT two 110-wide cubes CANNOT fit inside Box A (150x150x150) because 110 + 110 = 220 > 150!
    The packer must detect this spatial failure in Box A and upgrade to Box C (300x400x300)
    where they physically fit side-by-side.
    """
    box_a = next(b for b in default_catalogue if b.type == "A")
    packages = [
        PackageInput(id="cube_1", width=110.0, height=110.0, length=110.0, weight=10.0),
        PackageInput(id="cube_2", width=110.0, height=110.0, length=110.0, weight=10.0),
    ]

    # Directly verify that Box A physically rejects the collision
    assert not can_pack_geometrically_3d(box_a, packages)

    response = packer_service.pack(packages)
    verify_packing_invariants(response, packages, default_catalogue)

    # Must NOT pack them into Box A; must be upgraded to Box C
    assert response.total_boxes == 1
    assert response.boxes[0].box_type == "C"
    assert set(response.boxes[0].package_ids) == {"cube_1", "cube_2"}


def test_geometric_collision_in_largest_box_forces_multiple_boxes(packer_service, default_catalogue):
    """
    FAILURE CASE:
    Two cubes of size 250 x 250 x 250:
    - Total volume: 31,250,000 <= 36,000,000 (Box C volume).
    - Total weight: 200 <= 3000.
    - Each cube individually fits in Box C (300 x 400 x 300).
    - BUT 250 + 250 = 500 > 400 (exceeds all dimensions of Box C).
    They cannot coexist in the largest box. The service must catch this failure
    and split them into 2 separate Box C boxes rather than erroneously putting them in 1 box.
    """
    box_c = next(b for b in default_catalogue if b.type == "C")
    packages = [
        PackageInput(id="big_cube_1", width=250.0, height=250.0, length=250.0, weight=100.0),
        PackageInput(id="big_cube_2", width=250.0, height=250.0, length=250.0, weight=100.0),
    ]

    # Directly verify that Box C rejects two 250 cubes
    assert not can_pack_geometrically_3d(box_c, packages)

    response = packer_service.pack(packages)
    verify_packing_invariants(response, packages, default_catalogue)

    # Must be split into 2 separate boxes
    assert response.total_boxes == 2
    assert len(response.boxes) == 2
    for b in response.boxes:
        assert b.box_type == "C"
        assert len(b.package_ids) == 1


def test_incompatible_dimensions_during_box_upgrade(packer_service, default_catalogue):
    """
    FAILURE CASE:
    - Package 1 (190 x 90 x 90) fits in Box B (height 200), but cannot fit in Box A (max dim 150).
    - Package 2 (140 x 140 x 140) fits in Box A, but cannot fit in Box B (width 100).
    When trying to pack both:
    - Box B cannot hold Package 2.
    - Box A cannot hold Package 1.
    The packer must recognize that upgrading from B to A fails, and must jump to Box C.
    """
    packages = [
        PackageInput(id="long_item", width=190.0, height=90.0, length=90.0, weight=20.0),
        PackageInput(id="wide_item", width=140.0, height=140.0, length=140.0, weight=20.0),
    ]
    response = packer_service.pack(packages)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 1
    assert response.boxes[0].box_type == "C"
    assert set(response.boxes[0].package_ids) == {"long_item", "wide_item"}


def test_partial_packing_with_unpackable_item(packer_service, default_catalogue):
    """One valid item, two unpackable items (one oversized, one overweight)."""
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
    """When all items are unpackable, return 0 boxes and list all unpackable items."""
    packages = [
        PackageInput(id="huge_1", width=600.0, height=600.0, length=600.0, weight=50.0),
        PackageInput(id="heavy_2", width=50.0, height=50.0, length=50.0, weight=5000.0),
    ]
    response = packer_service.pack(packages)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 0
    assert len(response.boxes) == 0
    assert len(response.unpackable_packages) == 2


def test_multiple_boxes_required_due_to_weight(packer_service, default_catalogue):
    """When packages exceed Box C max weight (3000), multiple boxes must be used."""
    packages = [
        PackageInput(id=f"item_{i}", width=50.0, height=50.0, length=50.0, weight=1200.0)
        for i in range(4)
    ]
    response = packer_service.pack(packages)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 2


def test_combined_packages_fit_volume_and_weight_and_individual_dims_but_fail_spatially():
    """
    CRITICAL EDGE CASE (Explicitly requested verification):
    Given a single box type of size 150 x 150 x 150 (max_weight = 1000):
    Package 1: 110 x 110 x 110, weight 10 (Volume = 1,331,000)
    Package 2: 110 x 110 x 110, weight 10 (Volume = 1,331,000)

    Verification:
    1. sum(volume) = 2,662,000 <= 3,375,000 (Box volume) -> PASSES volume limit
    2. sum(weight) = 20 <= 1000 (Box weight capacity) -> PASSES weight limit
    3. P1 dimensions <= Box dimensions (110 <= 150) -> PASSES individual dimension limit
    4. P2 dimensions <= Box dimensions (110 <= 150) -> PASSES individual dimension limit
    5. BUT COMBINED: 110 + 110 = 220 > 150 along every axis!
       They CANNOT physically fit together in this box.

    Expectation:
    When this is the only box type available, the algorithm MUST NOT put them in 1 box.
    It must split them into 2 separate boxes of this type.
    """
    single_box_catalogue = [
        BoxDefinition(type="A", width=150.0, height=150.0, length=150.0, max_weight=1000.0)
    ]
    packer = BinPackerService(single_box_catalogue)
    packages = [
        PackageInput(id="cube_1", width=110.0, height=110.0, length=110.0, weight=10.0),
        PackageInput(id="cube_2", width=110.0, height=110.0, length=110.0, weight=10.0),
    ]

    # Pre-condition assertions proving the exact premise of the question:
    box = single_box_catalogue[0]
    total_vol = sum(p.volume for p in packages)
    total_w = sum(p.weight for p in packages)
    assert total_vol <= box.volume, f"Total volume {total_vol} exceeds {box.volume}"
    assert total_w <= box.max_weight, f"Total weight {total_w} exceeds {box.max_weight}"
    for p in packages:
        assert box.can_accommodate_dimensions(p.sorted_dimensions), f"{p.id} exceeds single dimensions"

    # Verify that 3D spatial check REJECTS putting them together in this box:
    assert not can_pack_geometrically_3d(box, packages), "Should be physically impossible to pack together"

    # Run the packer:
    response = packer.pack(packages)
    verify_packing_invariants(response, packages, single_box_catalogue)

    # Must require 2 boxes, NOT 1:
    assert response.total_boxes == 2
    assert len(response.boxes) == 2
    assert response.boxes[0].box_type == "A"
    assert response.boxes[1].box_type == "A"
    assert response.boxes[0].package_ids == ["cube_1"]
    assert response.boxes[1].package_ids == ["cube_2"]
