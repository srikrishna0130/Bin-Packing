from typing import List, Tuple, Union
from pydantic import BaseModel, Field


class PackageInput(BaseModel):
    """Input payload for an individual package to be shipped."""
    id: Union[int, str] = Field(..., description="Unique package identifier")
    width: float = Field(..., gt=0, le=10000, description="Package width (must be positive)")
    height: float = Field(..., gt=0, le=10000, description="Package height (must be positive)")
    length: float = Field(..., gt=0, le=10000, description="Package length (must be positive)")
    weight: float = Field(..., gt=0, le=100000, description="Package weight (must be positive)")

    @property
    def volume(self) -> float:
        """Cubic volume of the package."""
        return self.width * self.height * self.length

    @property
    def sorted_dimensions(self) -> Tuple[float, float, float]:
        """Dimensions sorted in ascending order for orthogonal 3D rotation checks."""
        return tuple(sorted([self.width, self.height, self.length]))  # type: ignore


class PackedBox(BaseModel):
    """Details of a single shipping box packed with packages."""
    box_type: str = Field(..., description="Catalogue box identifier (e.g. 'A', 'B', 'C')")
    package_ids: List[Union[int, str]] = Field(..., description="List of package IDs packed into this box")
    total_weight: float = Field(..., description="Cumulative weight of packed packages")
    total_volume: float = Field(..., description="Cumulative volume of packed packages")
    max_weight: float = Field(..., description="Weight capacity of the box type")
    box_volume: float = Field(..., description="Total volume capacity of the box type")


class UnpackablePackage(BaseModel):
    """Details of a package that cannot fit into any available catalogue box."""
    id: Union[int, str] = Field(..., description="Package identifier")
    dimensions: List[float] = Field(..., description="Package dimensions [width, height, length]")
    weight: float = Field(..., description="Package weight")
    reason: str = Field(..., description="Explanation of why this package could not be packed")


class PackingResponse(BaseModel):
    """Overall response containing the number of shipping boxes and packing details."""
    total_boxes: int = Field(..., description="Total number of shipping boxes needed")
    boxes: List[PackedBox] = Field(default_factory=list, description="Breakdown of packages in each box")
    unpackable_packages: List[UnpackablePackage] = Field(
        default_factory=list,
        description="List of packages that could not fit into any available shipping box",
    )
