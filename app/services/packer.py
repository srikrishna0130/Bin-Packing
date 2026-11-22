from typing import List, Optional, Tuple
from app.models.box import BoxDefinition
from app.models.package import PackageInput, PackedBox, UnpackablePackage, PackingResponse


class ActiveBox:
    """Represents a box currently being packed."""

    def __init__(self, box_def: BoxDefinition):
        self.box_def = box_def
        self.items: List[PackageInput] = []

    @property
    def total_weight(self) -> float:
        return sum(item.weight for item in self.items)

    @property
    def total_volume(self) -> float:
        return sum(item.volume for item in self.items)

    def can_fit_item(self, item: PackageInput) -> bool:
        """Check if an item can be added to the current box without exceeding limits (naive check)."""
        if self.total_weight + item.weight > self.box_def.max_weight:
            return False
        if self.total_volume + item.volume > self.box_def.volume:
            return False
        if not self.box_def.can_accommodate_dimensions(item.sorted_dimensions):
            return False
        return True

    def to_packed_box(self) -> PackedBox:
        return PackedBox(
            box_type=self.box_def.type,
            package_ids=[item.id for item in self.items],
            total_weight=round(self.total_weight, 2),
            total_volume=round(self.total_volume, 2),
            max_weight=self.box_def.max_weight,
            box_volume=self.box_def.volume,
        )


class BinPackerService:
    """Bin packing service using the baseline Progressive Upgrade heuristic (naive volume/weight check)."""

    def __init__(self, boxes: List[BoxDefinition]):
        if not boxes:
            raise ValueError("Box catalogue must contain at least one box definition.")
        # Sort boxes by volume ascending, then max_weight ascending
        self.boxes = sorted(boxes, key=lambda b: (b.volume, b.max_weight))

    def _can_box_hold_all(self, box_def: BoxDefinition, items: List[PackageInput]) -> bool:
        """Check if all items together satisfy a box definition's weight, volume, and dimensions."""
        total_weight = sum(item.weight for item in items)
        if total_weight > box_def.max_weight:
            return False
        total_volume = sum(item.volume for item in items)
        if total_volume > box_def.volume:
            return False
        for item in items:
            if not box_def.can_accommodate_dimensions(item.sorted_dimensions):
                return False
        return True

    def _find_smallest_box_for_item(self, item: PackageInput) -> Optional[BoxDefinition]:
        """Find the smallest box in the catalogue that can fit this single item."""
        for box_def in self.boxes:
            if item.weight <= box_def.max_weight and box_def.can_accommodate_dimensions(
                item.sorted_dimensions
            ):
                return box_def
        return None

    def pack(self, packages: List[PackageInput]) -> PackingResponse:
        """
        Packs the given packages into shipping boxes using the Progressive Upgrade heuristic.

        1. Identifies and segregates any unpackable packages (exceeding all available boxes).
        2. Sorts packable packages descending by volume to maximize packing density.
        3. Fills an active box:
           - Tries to fit the next item into the current box.
           - If full, attempts to swap/upgrade the active box to a larger box type.
           - If even the largest box cannot fit the items together, finalizes the active box
             and opens a new box (starting with the smallest possible size for the new item).
        4. Returns the total boxes, the package IDs in each box, and any unpackable packages.
        """
        packable: List[PackageInput] = []
        unpackable: List[UnpackablePackage] = []

        # Step 1: Segregate unpackable packages
        for pkg in packages:
            smallest_box = self._find_smallest_box_for_item(pkg)
            if smallest_box is None:
                unpackable.append(
                    UnpackablePackage(
                        id=pkg.id,
                        dimensions=[pkg.width, pkg.height, pkg.length],
                        weight=pkg.weight,
                        reason="Exceeds maximum allowable dimensions or weight capacity of any available box",
                    )
                )
            else:
                packable.append(pkg)

        # If no items are packable, return early with 0 boxes
        if not packable:
            return PackingResponse(
                total_boxes=0,
                boxes=[],
                unpackable_packages=unpackable,
            )

        # Step 2: Sort packable items descending by volume, then weight (First-Fit Decreasing heuristic)
        packable.sort(key=lambda p: (p.volume, p.weight), reverse=True)

        packed_boxes: List[PackedBox] = []
        active_box: Optional[ActiveBox] = None

        # Step 3: Progressive Upgrade packing loop
        for pkg in packable:
            if active_box is None:
                box_def = self._find_smallest_box_for_item(pkg)
                assert box_def is not None  # Guaranteed by Step 1 check
                active_box = ActiveBox(box_def)
                active_box.items.append(pkg)
                continue

            # Try to fit in current active box
            if active_box.can_fit_item(pkg):
                active_box.items.append(pkg)
            else:
                # Active box is full with current item. Try upgrading to a larger box!
                candidate_items = active_box.items + [pkg]
                upgraded = False

                # Consider boxes strictly larger than the current active box
                for candidate_box in self.boxes:
                    if candidate_box.volume <= active_box.box_def.volume:
                        continue
                    if self._can_box_hold_all(candidate_box, candidate_items):
                        # Upgrade to this larger box
                        active_box.box_def = candidate_box
                        active_box.items.append(pkg)
                        upgraded = True
                        break

                if not upgraded:
                    # Cannot fit together even in larger boxes. Finalize current active box.
                    packed_boxes.append(active_box.to_packed_box())
                    # Start a new active box with the smallest box fitting this item
                    new_box_def = self._find_smallest_box_for_item(pkg)
                    assert new_box_def is not None
                    active_box = ActiveBox(new_box_def)
                    active_box.items.append(pkg)

        # Finalize remaining active box
        if active_box is not None and active_box.items:
            packed_boxes.append(active_box.to_packed_box())

        return PackingResponse(
            total_boxes=len(packed_boxes),
            boxes=packed_boxes,
            unpackable_packages=unpackable,
        )
