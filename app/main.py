from typing import List, Annotated
from fastapi import FastAPI, HTTPException, status, Body, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import (
    load_box_catalogue,
    MIN_PACKAGES_PER_REQUEST,
    MAX_PACKAGES_PER_REQUEST,
)
from app.models.package import PackageInput, PackingResponse
from app.services.packer import BinPackerService
from app.services.strategies import StrategyType

app = FastAPI(
    title="Bin Packing Service",
    description=(
        "Production-ready HTTP service to calculate the minimum number of shipping boxes "
        "and box assignments for a list of packages."
    ),
    version="1.0.0",
)

# Initialize box catalogue and packer service
catalogue = load_box_catalogue()
packer_service = BinPackerService(catalogue)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    """Custom handler for clean, client-friendly validation errors."""
    errors = []
    for error in exc.errors():
        field = " -> ".join(str(loc) for loc in error.get("loc", []))
        errors.append({
            "field": field,
            "message": error.get("msg", "Invalid value"),
            "type": error.get("type", "value_error"),
        })
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Request validation failed. Ensure input adheres to schema and limits.",
            "errors": errors,
        },
    )


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint for service monitoring."""
    return {"status": "healthy", "available_box_types": [b.type for b in catalogue]}


@app.post(
    "/pack",
    response_model=PackingResponse,
    status_code=status.HTTP_200_OK,
    summary="Calculate required shipping boxes",
    description=(
        "Accepts a list of packages with dimensions and weight. "
        "Returns the total number of boxes needed, the package IDs packed into each box, "
        "and any unpackable items that exceed all box capacities. "
        "Optionally select a packing strategy: 'bounding_box' (default) or 'volume_buffer'."
    ),
    tags=["Packing"],
)
async def pack_packages(
    packages: Annotated[
        List[PackageInput],
        Body(
            ...,
            min_length=MIN_PACKAGES_PER_REQUEST,
            max_length=MAX_PACKAGES_PER_REQUEST,
            description="List of packages to be packed (1 to 500 items).",
            openapi_examples={
                "assignment_sample": {
                    "summary": "1. Baseline (Assignment Sample)",
                    "description": "Two small packages that fit into a single Box B.",
                    "value": [
                        {"id": 123, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 5.0},
                        {"id": 125, "width": 5.0, "height": 5.0, "length": 10.0, "weight": 10.0},
                    ],
                },
                "progressive_upgrade": {
                    "summary": "2. Progressive Box Upgrade (B -> A)",
                    "description": "Three 70x70x70 items. Two fit in Box B; the third exceeds Box B height and triggers an automatic swap/upgrade to Box A.",
                    "value": [
                        {"id": "pkg_1", "width": 70.0, "height": 70.0, "length": 70.0, "weight": 10.0},
                        {"id": "pkg_2", "width": 70.0, "height": 70.0, "length": 70.0, "weight": 10.0},
                        {"id": "pkg_3", "width": 70.0, "height": 70.0, "length": 70.0, "weight": 10.0},
                    ],
                },
                "spatial_collision_upgrade": {
                    "summary": "3. Spatial Collision Avoidance (A -> C)",
                    "description": "Two 110x110x110 cubes. Total volume fits Box A, but 110+110=220 > 150. Detected and upgraded to Box C.",
                    "value": [
                        {"id": "cube_1", "width": 110.0, "height": 110.0, "length": 110.0, "weight": 20.0},
                        {"id": "cube_2", "width": 110.0, "height": 110.0, "length": 110.0, "weight": 20.0},
                    ],
                },
                "partial_shipment_unpackable": {
                    "summary": "4. Partial Shipment with Unpackable Item",
                    "description": "One standard package and one oversized package (exceeding all boxes), returning 200 OK with unpackable items itemized.",
                    "value": [
                        {"id": "standard_item", "width": 20.0, "height": 20.0, "length": 20.0, "weight": 15.0},
                        {"id": "oversized_item", "width": 500.0, "height": 500.0, "length": 500.0, "weight": 3500.0},
                    ],
                },
            },
        ),
    ],
    strategy: Annotated[
        StrategyType,
        Query(
            description=(
                "Packing validation strategy: 'bounding_box' (Method A: Cumulative Bounding Box, smallest first) "
                "or 'volume_buffer' (Method C: 100% single / 65% multi-item buffer, largest first)."
            ),
        ),
    ] = StrategyType.BOUNDING_BOX,
) -> PackingResponse:
    # Check for duplicate package IDs to protect data integrity
    seen_ids = set()
    duplicates = set()
    for pkg in packages:
        if pkg.id in seen_ids:
            duplicates.add(pkg.id)
        seen_ids.add(pkg.id)

    if duplicates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Duplicate package IDs found: {list(duplicates)}. Each package in a shipment must have a unique ID.",
        )

    return packer_service.pack(packages, strategy=strategy.value)
