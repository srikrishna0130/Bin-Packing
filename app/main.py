from typing import List, Annotated
from fastapi import FastAPI, HTTPException, status, Body
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import (
    load_box_catalogue,
    MIN_PACKAGES_PER_REQUEST,
    MAX_PACKAGES_PER_REQUEST,
)
from app.models.package import PackageInput, PackingResponse
from app.services.packer import BinPackerService

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
        "and any unpackable items that exceed all box capacities."
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
                "assignment_example": {
                    "summary": "Sample from assignment",
                    "value": [
                        {"id": 123, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 5.0},
                        {"id": 125, "width": 5.0, "height": 5.0, "length": 10.0, "weight": 10.0},
                    ],
                }
            },
        ),
    ],
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

    return packer_service.pack(packages)
