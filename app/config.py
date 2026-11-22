import json
from pathlib import Path
from typing import List
from app.models.box import BoxDefinition

DATA_DIR = Path(__file__).resolve().parent / "data"
BOXES_FILE = DATA_DIR / "boxes.json"

MAX_PACKAGES_PER_REQUEST = 500
MIN_PACKAGES_PER_REQUEST = 1


def load_box_catalogue(file_path: Path = BOXES_FILE) -> List[BoxDefinition]:
    """Load and parse the box catalogue from JSON file."""
    if not file_path.exists():
        raise FileNotFoundError(f"Box catalogue file not found: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [BoxDefinition(**item) for item in data]
