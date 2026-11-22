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

## 4. Packing Algorithm: Progressive Upgrade Heuristic

### Why Not Brute Force?
3D bin packing is NP-hard. Brute forcing exponential placement trees causes request timeouts and latency spikes. Instead, we use an intuitive, deterministic, and highly efficient $O(N \log N)$ heuristic that prioritizes minimizing box count while choosing the smallest feasible box.

### The Algorithm Step-by-Step
1. **Unpackable Segregation:**
   - Check if each package fits into at least one box in the catalogue (weight $\le \text{maxWeight}$ and rotated dimensions $\le \text{box dimensions}$).
   - Packages that fit in no box are immediately isolated into `unpackable_packages`.
2. **First-Fit Decreasing Ordering:**
   - Sort packable packages in **descending order of volume and weight**.
   - Packing larger items first prevents awkward large items from being stranded at the end and forcing unnecessary additional boxes.
3. **Active Box Life Cycle (Progressive Upgrade):**
   - For the first item, open the smallest box type capable of holding it.
   - For each subsequent item:
     - **Fit in current box:** If it satisfies remaining volume, weight, and dimensional constraints, add it to the active box.
     - **Upgrade / Swap:** If the current box is full, test whether **all items in the active box plus the new item** can fit together into a larger box type (e.g. swap B $\rightarrow$ A, or B/A $\rightarrow$ C).
     - **Finalize:** If even the largest box (Box C) cannot hold them all together, seal the current active box, commit it to `boxes`, and start a fresh active box starting from the smallest box that fits the new item.

---

## 5. How Unit Testing Works for a Heuristic

Since minimal bin packing is a heuristic rather than a provably unique mathematical optimum, **how do we unit test it?**

Rather than asserting arbitrary magic box numbers, unit testing verifies **physical and logical invariants**:

1. **Item Conservation:** Every packable input package ID must appear in **exactly one** returned box. No packages lost, none duplicated.
2. **Unpackable Isolation:** Unpackable package IDs appear strictly in `unpackable_packages` and never in any packed box.
3. **Weight Feasibility:** For every packed box, $\sum \text{weight} \le \text{box.max\_weight}$.
4. **Volume Feasibility:** For every packed box, $\sum \text{volume} \le \text{box.volume}$.
5. **Rotational 3D Dimension Feasibility:** For every package inside a box, its sorted 3D dimensions $(d_1 \le d_2 \le d_3) \le (b_1 \le b_2 \le b_3)$ of the assigned box.
6. **Box Count Integrity:** `total_boxes == len(boxes)`.
7. **Deterministic Heuristic Scenarios:**
   - Small items select Box B.
   - Wide items ($120\times 120\times 120$) select Box A (too wide for B).
   - Progressive upgrade swaps Box B to Box A when a third item overflows B.
   - Partial packing test cases where oversized items are segregated alongside valid boxes.

---

## 6. Assumptions & Design Decisions

1. **What "Fits" Means:** An item fits in a box if its rotated orthogonal dimensions $(d_1, d_2, d_3)$ fit inside the box $(b_1, b_2, b_3)$, and the cumulative volume and weight of all items do not exceed the box's volume and weight limits.
2. **Partial Shipment (HTTP 200):** If unpackable packages are present, the API packs what it can and returns the rest in `unpackable_packages`.
3. **Empty Input (`[]`):** Rejected with `422 Unprocessable Entity` because a shipment request must have at least 1 item.
4. **Catalogue Extensibility:** Box types are loaded from `boxes.json`, making it easy to add or adjust box types without changing service code.

---

## 7. What to Do with More Time
- **3D Guillotine / Shelf Placement:** Add 3D coordinate nesting for non-cubic irregular clusters.
- **Multi-bin Best Fit:** Maintain multiple concurrently open bins to backfill small packages into earlier partially-filled boxes.
- **Client SDK / OpenAPI generation:** Generate typed clients directly from the FastAPI schema.
