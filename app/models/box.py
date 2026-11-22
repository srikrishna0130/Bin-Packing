from typing import Tuple
from pydantic import BaseModel, Field


class BoxDefinition(BaseModel):
    """Represents an available shipping box type from the catalogue."""
    type: str
    width: float = Field(..., gt=0, description="Width of the box in standard units")
    height: float = Field(..., gt=0, description="Height of the box in standard units")
    length: float = Field(..., gt=0, description="Length of the box in standard units")
    max_weight: float = Field(..., gt=0, description="Maximum weight capacity of the box")

    @property
    def volume(self) -> float:
        """Total cubic volume of the box."""
        return self.width * self.height * self.length

    @property
    def sorted_dimensions(self) -> Tuple[float, float, float]:
        """Dimensions sorted in ascending order for orthogonal 3D rotation checks."""
        return tuple(sorted([self.width, self.height, self.length]))  # type: ignore

    def can_accommodate_dimensions(self, dims: Tuple[float, float, float]) -> bool:
        """Check if an item with given sorted dimensions can physically fit inside this box."""
        box_dims = self.sorted_dimensions
        return (
            dims[0] <= box_dims[0]
            and dims[1] <= box_dims[1]
            and dims[2] <= box_dims[2]
        )
