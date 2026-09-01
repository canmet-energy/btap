#!/usr/bin/env python3
"""Building-stock adapter: NRCan footprint records in, OpenStudio massing out.

  python3 scripts/building_stock.py --fsa K1P --limit 10 --out /tmp/massing
  python3 scripts/building_stock.py --point 45.4215,-75.6972 --radius 300 --out /tmp/massing
  python3 scripts/building_stock.py --bbox -75.70,45.41,-75.69,45.43 --out /tmp/massing
  python3 scripts/building_stock.py --from-cache records.json --out /tmp/massing   # offline

WHY THIS IS MAINTAINER TOOLING (D-71): btap.modeling remains SDK-only and
offline. The fetch adapter lives outside the modeling package, so
``btap.modeling.geometry.footprint`` never learns where a ring came from.

AUTH follows scripts/fetch_necb_8_4_text.py: endpoint and X-API-Key come from
the environment, else from .mcp.json (gitignored, never committed with a live
key). Nothing is hardcoded, and the key is never printed, never written to the
cache, and never stored in a model. btap.simulation's Remote backend declines
to hardcode agent-facing MCP endpoints for exactly this reason; reading them at
runtime is the same rule honoured, not an exception to it.

CACHE: ``--cache`` writes the raw records, ``--from-cache`` rebuilds from them
with no network at all — so a fetch is reproducible and CI never needs the MCP,
the same split the NECB text fetcher uses.

Python port (PR-A2): maintains exact Ruby behavior on record rejection, height
field selection, provenance keys, and model stamping. JSON output is
deterministic (sorted keys, pretty-print) for clean diffs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Importable without installing the package
PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from btap._mcp import MCPClient, MCPError  # noqa: E402

# Import SDK modules only when actually building (not for --dry-run)
_SDK_IMPORTED = False


def _ensure_sdk():
    global _SDK_IMPORTED
    if _SDK_IMPORTED:
        return
    try:
        import openstudio  # noqa: F401

        from btap import modeling  # noqa: F401
        from btap.audit import AuditLog  # noqa: F401
        _SDK_IMPORTED = True
    except ImportError as e:
        raise RuntimeError(
            "OpenStudio SDK required to build models (pip install openstudio~=3.11.0)"
        ) from e


REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = "nrcan-buildings"

# Height fields to try, in order
HEIGHT_FIELDS = ["height_max_m"]


def height_of(record: dict) -> tuple[float | None, str | None]:
    """Extract usable height from record.

    height_min_m is the lowest ROOF point (a podium), not ground level —
    subtracting it understates the building. Only height_max_m is the height.

    Returns:
        (height_value, field_name) or (None, None)
    """
    for field in HEIGHT_FIELDS:
        value = record.get(field)
        if value and float(value) > 0:
            return float(value), field
    return None, None


def rejection(record: dict) -> str | None:
    """Check if record is unusable, return reason or None."""
    if record.get("geometry_geojson") is None:
        return "no geometry (query with include_geometry: true)"

    height, _ = height_of(record)
    if height is None:
        return "no usable height"

    area = record.get("building_area_m2")
    if not area or float(area) <= 0:
        return "no footprint area"

    return None


def provenance(record: dict, height_field: str) -> dict:
    """Extract provenance for audit trail.

    Everything worth carrying into the audit so a massing is reproducible
    from its source record. The API key is deliberately NOT part of this.
    """
    return {
        k: v for k, v in {
            "feature_id": record.get("feature_id"),
            "dataset": DATASET,
            "height_field": height_field,
            "building_class": record.get("building_class"),
            "vintage_year": record.get("vintage_year"),
            "fsa": record.get("fsa"),
            "climate_zone": record.get("climate_zone"),
            "province_code": record.get("province_code"),
            "csd_name": record.get("csd_name"),
        }.items() if v is not None
    }


def stamp_model(model, record: dict):
    """Carry the record's own attributes on the model.

    Deliberately NOT setStandardsBuildingType: building_class is NRCan's
    heuristic, not a standards building type, and conflating them would
    silently mis-tag every model.
    """
    properties = model.getBuilding().additionalProperties()

    for key in [
        "feature_id", "building_class", "vintage_year", "fsa",
        "climate_zone", "province_code", "csd_uid",
        "building_area_m2", "height_max_m", "estimated_floors", "estimated_gfa_m2"
    ]:
        value = record.get(key)
        if value is None:
            continue

        if isinstance(value, (int, float)):
            properties.setFeature(f"nrcan_{key}", float(value))
        else:
            properties.setFeature(f"nrcan_{key}", str(value))

    feature_id = record.get("feature_id")
    if feature_id:
        model.getBuilding().setName(f"NRCan {feature_id}")


def to_model(
    record: dict,
    floor_to_floor_height: float | None = None,
    zoning: str = "core_perimeter",
    multiplier: str = "mid",
    audit = None
) -> dict:
    """Convert one record to one OpenStudio model.

    Args:
        record: Building-stock record with geometry_geojson
        floor_to_floor_height: Storey height in meters (None = NRCan implied 3.5m)
        zoning: "core_perimeter" or "single"
        multiplier: "mid" (ground/mid/top) or "none" (every storey)
        audit: AuditLog instance

    Returns:
        {"model": <Model>, "record": <dict>, "audit": <AuditLog>}
        or
        {"model": None, "record": <dict>, "audit": <AuditLog>, "skipped": <reason>}
    """
    _ensure_sdk()
    from btap.audit import AuditLog
    from btap.modeling import create_from_footprint
    from btap.modeling.geometry import footprint as Footprint

    if audit is None:
        audit = AuditLog()

    reason = rejection(record)
    if reason:
        audit.warn(
            "geometry",
            "building-stock record skipped",
            inputs={"feature_id": record.get("feature_id"), "reason": reason}
        )
        return {"model": None, "record": record, "audit": audit, "skipped": reason}

    height, field = height_of(record)

    # Use NRCan implied height if not specified
    if floor_to_floor_height is None:
        floor_to_floor_height = Footprint.NRCAN_IMPLIED

    model = create_from_footprint(
        geojson=record["geometry_geojson"],
        height_m=height,
        floor_to_floor_height=floor_to_floor_height,
        zoning=zoning,
        multiplier=multiplier,
        source=provenance(record, field),
        audit=audit
    )

    stamp_model(model, record)

    return {"model": model, "record": record, "audit": audit}


def query_buildings(client: MCPClient, mode: str, options: dict) -> list[dict]:
    """Query building-stock MCP for records."""
    common = {
        "dataset_id": DATASET,
        "include_geometry": True,
        "limit": options["limit"]
    }

    if mode == "fsa":
        args = {**common, "fsa": options["fsa"]}
        tool = "query_buildings_fsa"
    elif mode == "point":
        args = {
            **common,
            "lat": options["lat"],
            "lon": options["lon"],
            "radius_m": options["radius"]
        }
        tool = "query_buildings_point"
    elif mode == "bbox":
        args = {
            **common,
            "west": options["west"],
            "south": options["south"],
            "east": options["east"],
            "north": options["north"]
        }
        tool = "query_buildings_bbox"
    else:
        raise ValueError(f"unknown query mode {mode}")

    result = client.call(tool, args)
    return result.get("buildings", [])


def main():
    parser = argparse.ArgumentParser(
        description="Building-stock adapter: NRCan footprints to OpenStudio massing"
    )

    # Query options
    query = parser.add_argument_group("query")
    query.add_argument("--fsa", help="query by forward sortation area (e.g. K1P)")
    query.add_argument("--point", help="query around LAT,LON")
    query.add_argument("--radius", type=float, default=500, help="point search radius, metres (500)")
    query.add_argument("--bbox", help="query bounding box W,S,E,N")
    query.add_argument("--limit", type=int, default=25, help="max records (25)")
    query.add_argument("--class", dest="klass", help="keep only this building_class")

    # Model options
    model = parser.add_argument_group("model")
    model.add_argument("--storey-height", type=float, help="floor-to-floor height in metres (NRCan implied 3.5m)")
    model.add_argument("--zoning", choices=["core_perimeter", "single"], default="core_perimeter",
                       help="zoning strategy (core_perimeter)")
    model.add_argument("--multiplier", choices=["mid", "none"], default="mid",
                       help="mid (ground/mid/top) | none (every storey)")

    # Output options
    output = parser.add_argument_group("output")
    output.add_argument("--out", type=Path, help="write .osm files and manifest.json here")
    output.add_argument("--cache", type=Path, help="save fetched records here")
    output.add_argument("--from-cache", type=Path, help="rebuild from saved records, no network")
    output.add_argument("--dry-run", action="store_true", help="fetch and report, build nothing")

    args = parser.parse_args()

    # Load records
    if args.from_cache:
        if not args.from_cache.is_file():
            parser.error(f"cache file not found: {args.from_cache}")
        records = json.loads(args.from_cache.read_text(encoding="utf-8"))
    else:
        # Determine query mode
        if args.fsa:
            mode = "fsa"
        elif args.point:
            mode = "point"
            try:
                lat, lon = args.point.split(",")
                args.lat = float(lat)
                args.lon = float(lon)
            except ValueError:
                parser.error("--point must be LAT,LON (e.g. 45.4215,-75.6972)")
        elif args.bbox:
            mode = "bbox"
            try:
                parts = args.bbox.split(",")
                if len(parts) != 4:
                    raise ValueError
                args.west, args.south, args.east, args.north = map(float, parts)
            except ValueError:
                parser.error("--bbox must be W,S,E,N (e.g. -75.70,45.41,-75.69,45.43)")
        else:
            parser.error("must specify --fsa, --point, --bbox, or --from-cache")

        try:
            client = MCPClient("building-stock")
            records = query_buildings(client, mode, vars(args))
        except MCPError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    # Filter by class if requested
    if args.klass:
        records = [r for r in records if r.get("building_class") == args.klass]

    print(f"fetched {len(records)} record(s)", file=sys.stderr)

    # Write cache if requested
    if args.cache:
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        args.cache.write_text(
            json.dumps(records, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )
        print(f"cached -> {args.cache}", file=sys.stderr)

    if args.dry_run:
        return 0

    if not args.out:
        parser.error("--out is required to build")

    # Build models
    _ensure_sdk()
    import openstudio

    from btap.audit import AuditLog

    args.out.mkdir(parents=True, exist_ok=True)
    audit = AuditLog()
    manifest = []

    for record in records:
        result = to_model(
            record,
            floor_to_floor_height=args.storey_height,
            zoning=args.zoning,
            multiplier=args.multiplier,
            audit=audit
        )

        feature_id = record.get("feature_id", "unknown")

        if result.get("skipped"):
            manifest.append({
                "feature_id": feature_id,
                "skipped": result["skipped"]
            })
            continue

        # Save model
        name = f"{feature_id[:8]}.osm"
        path = args.out / name
        result["model"].save(openstudio.toPath(str(path)), True)

        # Extract audit entry for manifest
        entry = None
        for e in reversed(audit.entries):
            if "measured-footprint" in str(e.get("action", "")):
                entry = e
                break

        manifest_entry = {
            "feature_id": feature_id,
            "osm": name,
            "building_class": record.get("building_class"),
        }

        if entry:
            inputs = entry.get("inputs", {})
            manifest_entry.update({
                "storeys": inputs.get("storeys_above"),
                "zoning": inputs.get("zoning"),
                "perimeter_zone_depth": inputs.get("perimeter_zone_depth"),
                "footprint_area_m2": inputs.get("footprint_area_m2"),
            })

        manifest_entry.update({
            "spaces": len(result["model"].getSpaces()),
            "thermal_zones": len(result["model"].getThermalZones()),
        })

        # Count zones on Story 0
        story_0_zones = sum(
            1 for z in result["model"].getThermalZones()
            if z.nameString().startswith("Story 0 ")
        )
        manifest_entry["zones_per_storey"] = story_0_zones

        manifest.append(manifest_entry)

    # Write manifest
    manifest_path = args.out / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

    built = sum(1 for m in manifest if "osm" in m)
    zoned = sum(1 for m in manifest if m.get("zoning") == "core_perimeter")
    skipped = len(manifest) - built

    print(f"built {built}/{len(records)} ({zoned} core/perimeter, {skipped} skipped)", file=sys.stderr)
    print(f"manifest -> {manifest_path}", file=sys.stderr)
    print(f"warnings: {len(audit.warnings)}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
