from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Set, Tuple
from app.models.box import BoxDefinition
from app.models.package import PackageInput


class StrategyType(str, Enum):
    """Available bin-packing fitting strategies."""
    BOUNDING_BOX = "bounding_box"
    VOLUMETRIC_DERATING = "volumetric_derating"


class PackingStrategy(ABC):
    """Abstract Strategy interface for package sorting and box fit validation."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique strategy name."""
        pass

    @abstractmethod
    def sort_packages(self, packages: List[PackageInput]) -> List[PackageInput]:
        """Order packages prior to packing."""
        pass

    @abstractmethod
    def can_fit_items(self, box_def: BoxDefinition, items: List[PackageInput]) -> bool:
        """Determine whether the collection of items fits inside box_def."""
        pass


class BoundingBoxStrategy(PackingStrategy):
    """
    Method A: Cumulative Bounding Box Strategy.
    - Sorts packages in ascending order of volume (smallest items first).
    - Checks weight capacity and individual dimensions.
    - Maintains a cumulative enclosing bounding box [W, H, L] by testing
      expansion along X, Y, and Z for incoming packages across 3D rotations.
    """

    @property
    def name(self) -> str:
        return StrategyType.BOUNDING_BOX.value

    def sort_packages(self, packages: List[PackageInput]) -> List[PackageInput]:
        # Smallest items first to cluster tightly and minimize bounding box dead air
        return sorted(packages, key=lambda p: (p.volume, p.weight))

    def can_fit_items(self, box_def: BoxDefinition, items: List[PackageInput]) -> bool:
        if not items:
            return True

        # Weight capacity check
        total_weight = sum(item.weight for item in items)
        if total_weight > box_def.max_weight:
            return False

        # Volume capacity check
        total_volume = sum(item.volume for item in items)
        if total_volume > box_def.volume:
            return False

        # Single item fit check
        for item in items:
            if not box_def.can_accommodate_dimensions(item.sorted_dimensions):
                return False

        if len(items) == 1:
            return True

        # Cumulative bounding box check
        box_dims = box_def.sorted_dimensions
        curr_w, curr_h, curr_l = items[0].sorted_dimensions

        for item in items[1:]:
            rotations = set([
                (item.width, item.height, item.length),
                (item.width, item.length, item.height),
                (item.height, item.width, item.length),
                (item.height, item.length, item.width),
                (item.length, item.width, item.height),
                (item.length, item.height, item.width),
            ])

            best_candidate = None
            best_candidate_vol = float("inf")

            for w, h, l in rotations:
                attachments = [
                    (curr_w + w, max(curr_h, h), max(curr_l, l)),
                    (max(curr_w, w), curr_h + h, max(curr_l, l)),
                    (max(curr_w, w), max(curr_h, h), curr_l + l),
                ]
                for cand_w, cand_h, cand_l in attachments:
                    cand_sorted = tuple(sorted([cand_w, cand_h, cand_l]))
                    if (
                        cand_sorted[0] <= box_dims[0]
                        and cand_sorted[1] <= box_dims[1]
                        and cand_sorted[2] <= box_dims[2]
                    ):
                        cand_vol = cand_sorted[0] * cand_sorted[1] * cand_sorted[2]
                        if cand_vol < best_candidate_vol:
                            best_candidate_vol = cand_vol
                            best_candidate = (cand_w, cand_h, cand_l)

            if best_candidate is None:
                return False

            curr_w, curr_h, curr_l = best_candidate

        return True


class VolumetricDeratingStrategy(PackingStrategy):
    """
    Method C: Volumetric Derating / Fill Factor Strategy.
    - Sorts packages descending by volume (First-Fit Decreasing).
    - Checks weight capacity and individual dimensions.
    - Limits volume to 100% (1.0) for a single item, and derates to 65% (0.65)
      for multiple items to account for realistic packing void ratios.
    """

    def __init__(self, multi_item_derating_factor: float = 0.65):
        if not (0.0 < multi_item_derating_factor <= 1.0):
            raise ValueError("Derating factor must be between 0.0 and 1.0")
        self.multi_item_derating_factor = multi_item_derating_factor

    @property
    def name(self) -> str:
        return StrategyType.VOLUMETRIC_DERATING.value

    def sort_packages(self, packages: List[PackageInput]) -> List[PackageInput]:
        # Largest items first (First-Fit Decreasing heuristic)
        return sorted(packages, key=lambda p: (p.volume, p.weight), reverse=True)

    def can_fit_items(self, box_def: BoxDefinition, items: List[PackageInput]) -> bool:
        if not items:
            return True

        # Weight capacity check
        total_weight = sum(item.weight for item in items)
        if total_weight > box_def.max_weight:
            return False

        # Individual dimensions check
        for item in items:
            if not box_def.can_accommodate_dimensions(item.sorted_dimensions):
                return False

        # Volumetric derating check
        total_volume = sum(item.volume for item in items)
        allowed_factor = 1.0 if len(items) <= 1 else self.multi_item_derating_factor
        if total_volume > box_def.volume * allowed_factor:
            return False

        return True


# Strategy Registry
STRATEGY_REGISTRY = {
    StrategyType.BOUNDING_BOX.value: BoundingBoxStrategy(),
    StrategyType.VOLUMETRIC_DERATING.value: VolumetricDeratingStrategy(),
}


def get_packing_strategy(strategy_name: str) -> PackingStrategy:
    """Retrieve a packing strategy instance by name."""
    strategy = STRATEGY_REGISTRY.get(strategy_name)
    if not strategy:
        available = list(STRATEGY_REGISTRY.keys())
        raise ValueError(f"Unknown strategy '{strategy_name}'. Available: {available}")
    return strategy
