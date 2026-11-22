# Bin Packing HTTP Service

A robust, production-grade FastAPI service that calculates the minimum number of shipping boxes required to pack a list of items and returns the item-to-box assignments, respecting box dimensions and weight limits.

---

## 1. Quickstart

### Prerequisites
- Python 3.10+ (tested on Python 3.13)
- `pip`

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Run the Service
```bash
python -m uvicorn app.main:app --reload --port 8000
```
Interactive API docs are available at [http://localhost:8000/docs](http://localhost:8000/docs).

### Run Tests
```bash
python -m pytest -v
```

### Run with Docker (Optional)
```bash
docker build -t bin-packing-service .
docker run -p 8000:8000 bin-packing-service
```

---

## 2. API Contract

### Endpoint: `POST /pack`

Accepts a list of packages to pack into available shipping boxes.

#### Strategy Selection (`?strategy=...`)
The client can choose between two packing validation strategies via the `strategy` query parameter:
* **`strategy=bounding_box` (Default - Method A):** Uses cumulative bounding box expansion $[W, H, L]$. Sorts packages in **ascending volume** (smallest first) so small items pack tightly without creating dead air.
* **`strategy=volume_buffer` (Method C):** Uses realistic packaging buffer limits ($100\%$ for 1 item, $65\%$ for $\ge 2$ items). Sorts packages in **descending volume** (First-Fit Decreasing).

#### Sensible Limits & Guardrails
- **Batch Size:** Minimum 1 item, maximum 500 items per request (protects against payload exhaustion).
- **Physical Values:** `width`, `height`, `length`, and `weight` must be strictly positive (`> 0`).
- **Identifier Integrity:** Duplicate package IDs within a single request are rejected with `400 Bad Request`.

#### Example Request
```json
[
  { "id": 123, "width": 10.0, "height": 10.0, "length": 10.0, "weight": 5.0 },
  { "id": 125, "width": 5.0,  "height": 5.0,  "length": 10.0, "weight": 10.0 }
]
```

#### Example Response (`200 OK`)
```json
{
  "total_boxes": 1,
  "boxes": [
    {
      "box_type": "B",
      "package_ids": [123, 125],
      "total_weight": 15.0,
      "total_volume": 1250.0,
      "max_weight": 1000.0,
      "box_volume": 2000000.0
    }
  ],
  "unpackable_packages": []
}
```

#### Partial Packing for Oversized / Overweight Items (`200 OK`)
If an item exceeds the physical capacity or dimensions of *all* available boxes, the service ships the valid items and itemizes the unpackable items:
```json
{
  "total_boxes": 1,
  "boxes": [
    {
      "box_type": "B",
      "package_ids": [123],
      "total_weight": 5.0,
      "total_volume": 1000.0,
      "max_weight": 1000.0,
      "box_volume": 2000000.0
    }
  ],
  "unpackable_packages": [
    {
      "id": 999,
      "dimensions": [500.0, 500.0, 500.0],
      "weight": 3500.0,
      "reason": "Exceeds maximum allowable dimensions or weight capacity of any available box"
    }
  ]
}
```

#### Error Responses
- **Empty payload `[]` (`422 Unprocessable Entity`):** Empty input is rejected because a shipment must contain at least 1 item.
- **Negative / Zero dimensions (`422 Unprocessable Entity`):** Clean, field-level validation messages.
- **Duplicate IDs (`400 Bad Request`):** Clear message identifying the duplicated IDs.

---

## 3. Box Catalogue

The catalogue is stored in [`app/data/boxes.json`](app/data/boxes.json) and loaded via `app/config.py`:

| Box Type | Width | Height | Length | Max Weight | Volume | Notes |
| :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **B** | 100 | 200 | 100 | 1,000 | 2,000,000 | Smallest volume; tall aspect ratio |
| **A** | 150 | 150 | 150 | 1,000 | 3,375,000 | Medium volume; cubic |
| **C** | 300 | 400 | 300 | 3,000 | 36,000,000 | Largest volume and weight capacity |

*Note: Box B has a smaller volume ($2\text{M}$) than Box A ($3.375\text{M}$), but its height ($200$) is greater than Box A's ($150$). Thus, an item of length $180$ can fit in Box B but not Box A, whereas a cube of $120\times 120\times 120$ can fit in Box A but not Box B. The service handles these non-monotonic dimensional constraints automatically.*

---

## 4. Packing Algorithm: Progressive Upgrade with Strategy Pattern

### Why Not Brute Force?
3D bin packing is NP-hard. Brute forcing exponential placement trees causes request timeouts and latency spikes. Instead, we use an intuitive, deterministic, and highly efficient $O(N \log N)$ heuristic that prioritizes minimizing box count while choosing the smallest feasible box.

### Pluggable Strategies

We use the **Strategy Pattern** to separate packing validation into clean, interchangeable strategies:

#### Method A: Cumulative Bounding Box (`bounding_box`, Default)
* **Sorting:** Packages are sorted in **ascending order of volume** (smallest items first). This clusters small items tightly together and prevents premature inflation of bounding box dimensions.
* **Fit Check:** Maintains a single enclosing bounding box $[W, H, L]$ by evaluating expansion along $X$, $Y$, and $Z$ across 3D rotations. If the minimal enclosing bounding box fits within the shipping box, the items fit.

#### Method C: Volume Buffer (`volume_buffer`)
* **Sorting:** Packages are sorted in **descending order of volume** (First-Fit Decreasing).
* **Fit Check:** Enforces realistic packaging buffer limits:
  * Single item ($N=1$): Allows up to **$100\%$** ($1.0$) of box volume.
  * Multiple items ($N \ge 2$): Leaves a 35% buffer (caps volume at **$65\%$** / $0.65$) to account for void space between mixed rectangular items.

---

## 5. How Unit Testing Works: Invariants & Failure Cases

Since minimal bin packing is a heuristic rather than a provably unique mathematical optimum, unit testing verifies **physical, spatial, and logical invariants**:

1. **Item Conservation:** Every packable input package ID must appear in **exactly one** returned box. No packages lost, none duplicated.
2. **Unpackable Isolation:** Unpackable package IDs appear strictly in `unpackable_packages` and never in any packed box.
3. **Weight Feasibility:** For every packed box, $\sum \text{weight} \le \text{maxWeight}$.
4. **Volume Feasibility:** For every packed box, $\sum \text{volume} \le \text{box.volume}$.
5. **Rotational 3D Dimension Feasibility:** For every package inside a box, its sorted 3D dimensions $(d_1 \le d_2 \le d_3) \le (b_1 \le b_2 \le b_3)$ of the assigned box.
6. **Box Count Integrity:** `total_boxes == len(boxes)`.

### Tested Failure & Edge Cases:
- **Spatial Collision Forces Upgrade:** Two $110\times 110\times 110$ cubes have a combined volume under Box A's limit, but physically collide in Box A ($110+110=220 > 150$). Both `bounding_box` and `volume_buffer` catch this and upgrade to Box C.
- **Spatial Collision in Largest Box Forces Multiple Boxes:** Two $250\times 250\times 250$ cubes have a combined volume under Box C's limit, but collide in Box C ($250+250=500 > 400$). The packer catches this failure and splits them into 2 separate Box C boxes.
- **Incompatible Dimensions on Upgrade:** Package 1 fits only in Box B ($190\times 90\times 90$), Package 2 fits only in Box A ($140\times 140\times 140$). Upgrading to Box A fails because P1 exceeds A; upgrading to Box B fails because P2 exceeds B. The packer detects this and upgrades to Box C.
- **Strategy Selection & Parameter Validation:** Explicit selection of `bounding_box` and `volume_buffer` via query parameter, plus 422 error on invalid strategy names.
- **Negative & Zero Dimensions / Weights:** Rejected with `422 Unprocessable Entity`.
- **Missing Required Fields & Non-Numeric Types:** Rejected with `422 Unprocessable Entity`.
- **Empty List `[]`:** Rejected with `422 Unprocessable Entity`.
- **Duplicate IDs:** Rejected with `400 Bad Request`.
- **Exceeding Batch Limit (> 500 items):** Rejected with `422 Unprocessable Entity`.

---

## 6. Assumptions & Design Decisions

Where the assignment specification was open or silent, the following deliberate decisions and assumptions were made:

### A. What "Fits" Means & Geometric Constraints
1. **Rigid Rectangles:** All packages and shipping boxes are assumed to be rigid rectangular cuboids (no compressible/deformable packaging).
2. **Orthogonal 3D Rotation:** Packages can be freely rotated in 3D across any of the 6 orthogonal orientations unless a package has a "this side up" restriction (which the spec does not specify).
3. **Multi-Item Spatial Coexistence:**
   - **`bounding_box` (Method A):** Multiple items fit together if their combined minimal enclosing bounding box $[W, H, L]$ physically fits inside the box's outer dimensions, in addition to satisfying cumulative weight $\le \text{maxWeight}$ and volume $\le \text{box.volume}$.
   - **`volume_buffer` (Method C):** A single item can use up to $100\%$ of a box's volume, while multiple items are capped at $65\%$ ($0.65$) to account for real-world packing void ratios and air gaps.

### B. Package Ordering & Filling Heuristic
4. **Smallest-First for Bounding Box:** In the `bounding_box` strategy, packages are sorted **ascending by volume (smallest first)**. This clusters small items tightly together first and prevents large items from causing premature dimension inflation ("dead air").
5. **Largest-First for Volume Buffer:** In the `volume_buffer` strategy, packages are sorted **descending by volume (largest first)** following the classic First-Fit Decreasing heuristic.
6. **Box Upgrade Priority:** Boxes are evaluated in ascending order of volume: **Box B ($2.0\text{M}$) $\rightarrow$ Box A ($3.375\text{M}$) $\rightarrow$ Box C ($36.0\text{M}$)**. We prioritize minimizing the total box count: if an active box overflows, we attempt to swap/upgrade it to a larger box (Box A or Box C) before sealing it and opening an additional box.

### C. Error Handling & Partial Shipment Policy
7. **Unpackable Items (Partial Shipment Approach):** If an individual package exceeds the physical dimensions or weight capacity of all available boxes (e.g., weight $> 3,000$ or dimensions $> [300, 300, 400]$), the API does not throw an unhandled 500 error. Instead, it fulfills what it can: it packs all valid packages into boxes, sets `total_boxes` accordingly, and returns an `unpackable_packages` array detailing the oversized/overweight items with clear explanatory reasons. If all packages in a request are unpackable, it returns `200 OK` with `total_boxes: 0`, `boxes: []`, and all items listed in `unpackable_packages`.
8. **Empty Input (`[]`):** An empty list `[]` is rejected with `422 Unprocessable Entity` (`min_length=1`) on the assumption that a commercial shipping API requires at least one item to book a shipment.
9. **Duplicate Package IDs:** Each package within a single shipment payload must have a unique identifier. Duplicates are rejected with `400 Bad Request` to preserve parcel tracking integrity.

### D. System Guardrails & Non-Functional Decisions
10. **Sensible Batch Limits:** Requests are capped at a maximum of $500$ packages (`max_length=500`) to guarantee deterministic millisecond response times and guard against payload exhaustion / DoS attacks.
11. **Strict Positive Numbers & Sanity Bounds:** All physical dimensions and weights must be strictly positive (`> 0`). Dimensions are capped at $10,000$ and weights at $100,000$ to prevent integer/float overflow.
12. **Configurable Box Catalogue:** The box catalogue is decoupled into [`app/data/boxes.json`](app/data/boxes.json) and loaded via Pydantic models, allowing warehouse operators or reviewers to adjust box dimensions or add new box sizes without modifying service code.
13. **Stateless Service:** As stated in the take-home prompt's out-of-scope guidance, no external database or auth layer is required; the service is completely stateless and containerized.

---

## 7. Trade-offs Considered

* **Bounding Box vs. Full 3D Coordinate Meshing:** Bounding Box expansion offers $O(N)$ speed and zero external dependencies while preventing physical overlap. It is slightly more conservative on irregular L-shaped clusters than a full 3D physics engine, but runs in sub-millisecond time and is 100% deterministic.
* **Volume Buffer vs. Pure Geometry:** `volume_buffer` offers instant calculation by applying an empirical $65\%$ packing factor. It is fast and predictable, while `bounding_box` is preferred when strict geometric boundaries are required.
* **Progressive Upgrade vs. Global Multi-Bin Search:** Progressive box upgrading streams items one active box at a time, keeping memory minimal and the algorithm explainable, at the minor trade-off of not backtracking to re-open previously sealed boxes.

---

## 8. What to Do with More Time
- **3D Coordinate Output:** Return explicit $(x, y, z)$ placement offsets for each package to power a 3D packing visualizer in warehouse packing stations.
- **Backfilling Sealed Boxes:** Maintain a pool of partially filled sealed boxes and allow small remaining items to backfill residual volume before opening new boxes.
- **Client SDK Generation:** Auto-generate typed Python / TypeScript API client libraries directly from the FastAPI OpenAPI schema.
