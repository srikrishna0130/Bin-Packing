import pytest
from typing import List, Dict, NamedTuple
from app.models.box import BoxDefinition
from app.models.package import PackageInput, PackingResponse
from app.services.packer import BinPackerService
from app.services.strategies import (
    BoundingBoxStrategy,
    VolumeBufferStrategy,
    StrategyType,
)


class PlacedItem(NamedTuple):
    x: float
    y: float
    z: float
    width: float
    height: float
    length: float


def aabb_overlaps(a: PlacedItem, b: PlacedItem) -> bool:
    return not (
        a.x + a.width <= b.x or b.x + b.width <= a.x or
        a.y + a.height <= b.y or b.y + b.height <= a.y or
        a.z + a.length <= b.z or b.z + b.length <= a.z
    )


def can_pack_geometrically_3d(box_def: BoxDefinition, items: List[PackageInput]) -> bool:
    """Test verification utility: independently verifies if items can physically coexist in 3D."""
    if len(items) <= 1:
        return True
    box_w, box_h, box_l = box_def.width, box_def.height, box_def.length
    placed: List[PlacedItem] = []
    for item in items:
        candidate_points = {(0.0, 0.0, 0.0)}
        for p in placed:
            candidate_points.add((p.x + p.width, p.y, p.z))
            candidate_points.add((p.x, p.y + p.height, p.z))
            candidate_points.add((p.x, p.y, p.z + p.length))
        sorted_points = sorted(candidate_points, key=lambda pt: (pt[1], pt[0], pt[2]))
        placed_this_item = False
        rotations = set([
            (item.width, item.height, item.length), (item.width, item.length, item.height),
            (item.height, item.width, item.length), (item.height, item.length, item.width),
            (item.length, item.width, item.height), (item.length, item.height, item.width),
        ])
        for pt_x, pt_y, pt_z in sorted_points:
            if placed_this_item:
                break
            for w, h, l in rotations:
                if pt_x + w > box_w or pt_y + h > box_h or pt_z + l > box_l:
                    continue
                cand = PlacedItem(pt_x, pt_y, pt_z, w, h, l)
                if any(aabb_overlaps(cand, other) for other in placed):
                    continue
                placed.append(cand)
                placed_this_item = True
                break
        if not placed_this_item:
            return False
    return True


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
    check_spatial: bool = True,
):
    """
    Core verification helper for bin packing:
    Strictly verifies physical and logical invariants regardless of heuristic:
    1. Count consistency
    2. Item conservation (no dropped, no duplicated items)
    3. Weight capacity
    4. Volume capacity
    5. Single-item rotational fit
    6. Multi-item 3D spatial collision-free coexistence (when check_spatial=True)
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

    assert len(packed_ids) == len(set(packed_ids)), "A package ID appears more than once across boxes!"
    assert set(packed_ids).isdisjoint(set(unpackable_ids)), (
        "A package ID appears in both packed boxes and unpackable packages!"
    )

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

        assert sum_weight <= box_def.max_weight, (
            f"Box {box.box_type} exceeded max weight: {sum_weight} > {box_def.max_weight}"
        )
        assert sum_volume <= box_def.volume, (
            f"Box {box.box_type} exceeded volume capacity: {sum_volume} > {box_def.volume}"
        )
        for p in box_packages:
            assert box_def.can_accommodate_dimensions(p.sorted_dimensions), (
                f"Package {p.id} with dimensions {p.sorted_dimensions} does not fit in box {box.box_type}"
            )

        if check_spatial:
            assert can_pack_geometrically_3d(box_def, box_packages), (
                f"Box {box.box_type} contains packages that physically collide in 3D space!"
            )


# ============================================================================
# METHOD A: Cumulative Bounding Box Strategy Tests
# ============================================================================

def test_bounding_box_assignment_sample(packer_service, default_catalogue):
    """Test the exact sample payload from the assignment doc with BoundingBoxStrategy."""
    packages = [
        PackageInput(id=123, width=10.0, height=10.0, length=10.0, weight=5.0),
        PackageInput(id=125, width=5.0, height=5.0, length=10.0, weight=10.0),
    ]
    response = packer_service.pack(packages, strategy=StrategyType.BOUNDING_BOX.value)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 1
    assert response.boxes[0].box_type == "B"
    assert set(response.boxes[0].package_ids) == {123, 125}
    assert len(response.unpackable_packages) == 0


def test_bounding_box_sorts_ascending_by_volume():
    """Verify that BoundingBoxStrategy orders packages smallest-first."""
    strategy = BoundingBoxStrategy()
    pkgs = [
        PackageInput(id="big", width=50.0, height=50.0, length=50.0, weight=10.0),      # vol 125,000
        PackageInput(id="small", width=10.0, height=10.0, length=10.0, weight=1.0),     # vol 1,000
        PackageInput(id="medium", width=20.0, height=20.0, length=20.0, weight=5.0),    # vol 8,000
    ]
    sorted_pkgs = strategy.sort_packages(pkgs)
    assert [p.id for p in sorted_pkgs] == ["small", "medium", "big"]


def test_bounding_box_selection_by_dimension_fit(packer_service, default_catalogue):
    """Package (120x120x120) fits in Box A, but exceeds Box B width (100)."""
    packages = [
        PackageInput(id=1, width=120.0, height=120.0, length=120.0, weight=50.0),
    ]
    response = packer_service.pack(packages, strategy=StrategyType.BOUNDING_BOX.value)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 1
    assert response.boxes[0].box_type == "A"
    assert response.boxes[0].package_ids == [1]


def test_bounding_box_progressive_upgrade_swaps_to_larger_box(packer_service, default_catalogue):
    """
    Items 1 and 2 fit into Box B (70x70x70 fits along the 200 height: 70+70=140 <= 200).
    Adding item 3 overflows Box B (needs 3x70=210 > 200),
    but all three fit comfortably into Box A (2x2 grid: 140x140 <= 150x150).
    The packer upgrades to Box A.
    """
    packages = [
        PackageInput(id="p1", width=70.0, height=70.0, length=70.0, weight=10.0),
        PackageInput(id="p2", width=70.0, height=70.0, length=70.0, weight=10.0),
        PackageInput(id="p3", width=70.0, height=70.0, length=70.0, weight=10.0),
    ]
    response = packer_service.pack(packages, strategy=StrategyType.BOUNDING_BOX.value)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 1
    assert response.boxes[0].box_type == "A"
    assert set(response.boxes[0].package_ids) == {"p1", "p2", "p3"}


def test_bounding_box_catches_collision_and_upgrades_to_box_c(packer_service, default_catalogue):
    """
    Two cubes of 110x110x110:
    - Combined volume: 2,662,000 <= 3,375,000 (Box A volume)
    - Combined weight: 20 <= 1000
    - BUT combined bounding box is [220, 110, 110], exceeding Box A (150x150x150).
    BoundingBoxStrategy detects this failure and upgrades to Box C (300x400x300).
    """
    packages = [
        PackageInput(id="cube_1", width=110.0, height=110.0, length=110.0, weight=10.0),
        PackageInput(id="cube_2", width=110.0, height=110.0, length=110.0, weight=10.0),
    ]
    response = packer_service.pack(packages, strategy=StrategyType.BOUNDING_BOX.value)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 1
    assert response.boxes[0].box_type == "C"
    assert set(response.boxes[0].package_ids) == {"cube_1", "cube_2"}


def test_bounding_box_collision_in_largest_box_forces_multiple_boxes(packer_service, default_catalogue):
    """
    Two cubes of 250x250x250 in Box C:
    Combined bounding box is [500, 250, 250] > 400.
    Cannot fit in Box C together -> must split into 2 separate Box C boxes.
    """
    packages = [
        PackageInput(id="big_cube_1", width=250.0, height=250.0, length=250.0, weight=100.0),
        PackageInput(id="big_cube_2", width=250.0, height=250.0, length=250.0, weight=100.0),
    ]
    response = packer_service.pack(packages, strategy=StrategyType.BOUNDING_BOX.value)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 2
    assert len(response.boxes) == 2
    for b in response.boxes:
        assert b.box_type == "C"
        assert len(b.package_ids) == 1


def test_bounding_box_single_box_catalogue_forces_multiple_boxes():
    """
    With ONLY Box A (150x150x150) available, two 110x110x110 cubes
    must be split into 2 separate Box A boxes.
    """
    catalogue = [BoxDefinition(type="A", width=150.0, height=150.0, length=150.0, max_weight=1000.0)]
    packer = BinPackerService(catalogue, default_strategy=BoundingBoxStrategy())
    packages = [
        PackageInput(id="cube_1", width=110.0, height=110.0, length=110.0, weight=10.0),
        PackageInput(id="cube_2", width=110.0, height=110.0, length=110.0, weight=10.0),
    ]
    response = packer.pack(packages)
    verify_packing_invariants(response, packages, catalogue)

    assert response.total_boxes == 2
    assert response.boxes[0].box_type == "A"
    assert response.boxes[1].box_type == "A"


def test_bounding_box_incompatible_dimensions_during_upgrade(packer_service, default_catalogue):
    """
    P1 (190x90x90) fits in Box B (height 200), not Box A (max 150).
    P2 (140x140x140) fits in Box A, not Box B (width 100).
    Neither A nor B can hold both -> must upgrade to Box C.
    """
    packages = [
        PackageInput(id="long_item", width=190.0, height=90.0, length=90.0, weight=20.0),
        PackageInput(id="wide_item", width=140.0, height=140.0, length=140.0, weight=20.0),
    ]
    response = packer_service.pack(packages, strategy=StrategyType.BOUNDING_BOX.value)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 1
    assert response.boxes[0].box_type == "C"
    assert set(response.boxes[0].package_ids) == {"long_item", "wide_item"}


def test_bounding_box_partial_packing_with_unpackable_item(packer_service, default_catalogue):
    """One packable item, two unpackable items (one oversized, one overweight)."""
    packages = [
        PackageInput(id="valid_1", width=20.0, height=20.0, length=20.0, weight=10.0),
        PackageInput(id="oversized_2", width=500.0, height=500.0, length=500.0, weight=10.0),
        PackageInput(id="overweight_3", width=50.0, height=50.0, length=50.0, weight=4000.0),
    ]
    response = packer_service.pack(packages, strategy=StrategyType.BOUNDING_BOX.value)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 1
    assert response.boxes[0].package_ids == ["valid_1"]
    unpackable_ids = [u.id for u in response.unpackable_packages]
    assert "oversized_2" in unpackable_ids
    assert "overweight_3" in unpackable_ids


def test_bounding_box_all_items_unpackable(packer_service, default_catalogue):
    """All items unpackable -> return 0 boxes and list all unpackables."""
    packages = [
        PackageInput(id="huge_1", width=600.0, height=600.0, length=600.0, weight=50.0),
        PackageInput(id="heavy_2", width=50.0, height=50.0, length=50.0, weight=5000.0),
    ]
    response = packer_service.pack(packages, strategy=StrategyType.BOUNDING_BOX.value)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 0
    assert len(response.boxes) == 0
    assert len(response.unpackable_packages) == 2


def test_bounding_box_multiple_boxes_required_due_to_weight(packer_service, default_catalogue):
    """Packages exceed Box C max weight (3000) -> multiple boxes required."""
    packages = [
        PackageInput(id=f"item_{i}", width=50.0, height=50.0, length=50.0, weight=1200.0)
        for i in range(4)
    ]
    response = packer_service.pack(packages, strategy=StrategyType.BOUNDING_BOX.value)
    verify_packing_invariants(response, packages, default_catalogue)

    assert response.total_boxes == 2


# ============================================================================
# METHOD C: Volume Buffer Strategy Tests
# ============================================================================

def test_volume_buffer_sorts_descending_by_volume():
    """Verify that VolumeBufferStrategy orders packages largest-first (FFD)."""
    strategy = VolumeBufferStrategy()
    pkgs = [
        PackageInput(id="small", width=10.0, height=10.0, length=10.0, weight=1.0),
        PackageInput(id="big", width=50.0, height=50.0, length=50.0, weight=10.0),
        PackageInput(id="medium", width=20.0, height=20.0, length=20.0, weight=5.0),
    ]
    sorted_pkgs = strategy.sort_packages(pkgs)
    assert [p.id for p in sorted_pkgs] == ["big", "medium", "small"]


def test_volume_buffer_single_item_allows_100_percent():
    """A single item can use up to 100% of the box volume."""
    strategy = VolumeBufferStrategy(multi_item_buffer_factor=0.65)
    box = BoxDefinition(type="A", width=150.0, height=150.0, length=150.0, max_weight=1000.0)
    # Single item with 90% volume of Box A
    item = PackageInput(id=1, width=145.0, height=145.0, length=145.0, weight=100.0)
    assert strategy.can_fit_items(box, [item])


def test_volume_buffer_multi_item_derates_to_65_percent(packer_service, default_catalogue):
    """
    Two 110x110x110 cubes:
    Combined volume = 2.662M.
    Box A volume = 3.375M. At 65% limit: 3.375M * 0.65 = 2.193M.
    Because 2.662M > 2.193M, VolumeBufferStrategy rejects Box A
    and upgrades to Box C (where 36M * 0.65 = 23.4M >= 2.662M).
    """
    packages = [
        PackageInput(id="c1", width=110.0, height=110.0, length=110.0, weight=10.0),
        PackageInput(id="c2", width=110.0, height=110.0, length=110.0, weight=10.0),
    ]
    response = packer_service.pack(packages, strategy=StrategyType.VOLUME_BUFFER.value)
    verify_packing_invariants(response, packages, default_catalogue, check_spatial=False)

    assert response.total_boxes == 1
    assert response.boxes[0].box_type == "C"
    assert set(response.boxes[0].package_ids) == {"c1", "c2"}


def test_volume_buffer_forces_multiple_boxes_in_largest_box(packer_service, default_catalogue):
    """
    Two 250x250x250 cubes:
    Combined volume = 31.25M.
    Box C volume at 65% limit = 36M * 0.65 = 23.4M.
    Because 31.25M > 23.4M, it exceeds the multi-item limit and forces 2 separate Box C boxes.
    """
    packages = [
        PackageInput(id="b1", width=250.0, height=250.0, length=250.0, weight=50.0),
        PackageInput(id="b2", width=250.0, height=250.0, length=250.0, weight=50.0),
    ]
    response = packer_service.pack(packages, strategy=StrategyType.VOLUME_BUFFER.value)
    verify_packing_invariants(response, packages, default_catalogue, check_spatial=False)

    assert response.total_boxes == 2
    assert len(response.boxes) == 2
    for b in response.boxes:
        assert b.box_type == "C"
