"""Generate the simplified NYC taxi-zone geometry the map renders.

The real geometry is 263 zones and ~98,000 points (3.9 MB), which is too much to
ship to a browser. This fetches it from the same live dataset Cauzon investigates
and simplifies it with Douglas-Peucker, keeping the shapes recognisable at map
size while cutting the payload by roughly an order of magnitude.

The output is a generated artifact, like the fixtures — real data, reduced, never
hand-edited:

    python scripts/build_zone_geometry.py
"""

from __future__ import annotations

import json
import math
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "lib" / "taxi_zones.json"

# The same dataset the live backend reports on, so the map and the incident are
# about the same asset rather than two similar-looking things.
DATASET_ID = "8meu-9t5y"
SOURCE = f"https://data.cityofnewyork.us/resource/{DATASET_ID}.geojson?$limit=300"

# Degrees. ~0.0004 is around 40 m — well below one screen pixel at city scale.
TOLERANCE = 0.0004
# Rings smaller than this are slivers that add points without changing the shape.
MIN_RING_POINTS = 4
COORD_PRECISION = 4


def _perpendicular_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    if start == end:
        return math.dist(point, start)
    x0, y0 = point
    x1, y1 = start
    x2, y2 = end
    numerator = abs((x2 - x1) * (y1 - y0) - (x1 - x0) * (y2 - y1))
    return numerator / math.dist(start, end)


def simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas-Peucker, iterative so a long ring cannot blow the stack."""
    if len(points) < 3:
        return points

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]

    while stack:
        first, last = stack.pop()
        worst_index, worst_distance = -1, 0.0
        for i in range(first + 1, last):
            distance = _perpendicular_distance(points[i], points[first], points[last])
            if distance > worst_distance:
                worst_index, worst_distance = i, distance
        if worst_distance > tolerance:
            keep[worst_index] = True
            stack.append((first, worst_index))
            stack.append((worst_index, last))

    return [p for p, keep_it in zip(points, keep) if keep_it]


def main() -> None:
    print(f"fetching {SOURCE}")
    with urllib.request.urlopen(SOURCE, timeout=60) as response:
        raw = json.loads(response.read().decode("utf-8"))

    features = raw.get("features", [])
    zones = []
    points_before = points_after = 0

    for feature in features:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            continue

        polygons = (
            geometry["coordinates"]
            if geometry["type"] == "MultiPolygon"
            else [geometry["coordinates"]]
        )
        rings: list[list[list[float]]] = []
        for polygon in polygons:
            # Outer ring only; holes are invisible at this scale.
            outer = [(float(x), float(y)) for x, y in polygon[0]]
            points_before += len(outer)
            reduced = simplify(outer, TOLERANCE)
            if len(reduced) < MIN_RING_POINTS:
                continue
            points_after += len(reduced)
            rings.append(
                [[round(x, COORD_PRECISION), round(y, COORD_PRECISION)] for x, y in reduced]
            )

        if not rings:
            continue
        zones.append(
            {
                "id": properties.get("locationid"),
                "zone": properties.get("zone"),
                "borough": properties.get("borough"),
                "rings": rings,
            }
        )

    payload = {
        "source": f"https://data.cityofnewyork.us/d/{DATASET_ID}",
        "dataset_id": DATASET_ID,
        "note": (
            "Real NYC taxi-zone geometry, simplified with Douglas-Peucker "
            f"(tolerance {TOLERANCE} degrees) for browser delivery."
        ),
        "zones": zones,
    }
    OUT.write_text(json.dumps(payload, separators=(",", ":")) + "\n")

    size_kb = OUT.stat().st_size / 1024
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"  zones  {len(zones)}")
    print(f"  points {points_before} -> {points_after} "
          f"({points_after / max(points_before, 1):.1%})")
    print(f"  size   {size_kb:.0f} KB")


if __name__ == "__main__":
    main()
