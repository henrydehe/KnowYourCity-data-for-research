#!/usr/bin/env python3
"""
Extract GeoJSON layers from the Atlas of Informality ArcGIS web map.

Usage:
    python tools/extract_atlas_of_informality.py \
        --input data/atlas_of_informality_webmap.json \
        --output-dir data/atlas_of_informality
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ORIGIN_SHIFT = 2 * math.pi * 6378137 / 2.0  # Radius used by EPSG:3857


def mercator_to_lonlat(x: float, y: float) -> Tuple[float, float]:
    """Convert Web Mercator meters (EPSG:3857) to lon/lat (EPSG:4326)."""
    lon = (x / ORIGIN_SHIFT) * 180.0
    lat = (y / ORIGIN_SHIFT) * 180.0
    lat = 180.0 / math.pi * (2 * math.atan(math.exp(lat * math.pi / 180.0)) - math.pi / 2.0)
    return lon, lat


def sanitize_name(name: str) -> str:
    """Normalize layer names to lowercase snake_case for filenames."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "layer"


def convert_geometry(geometry: Dict[str, Any], geometry_type: str) -> Optional[Dict[str, Any]]:
    """Convert an ESRI geometry dict to a GeoJSON geometry."""
    if not geometry:
        return None

    if geometry_type == "esriGeometryPoint":
        lon, lat = mercator_to_lonlat(geometry["x"], geometry["y"])
        return {"type": "Point", "coordinates": [lon, lat]}

    if geometry_type == "esriGeometryPolyline":
        paths = geometry.get("paths", [])
        line_strings = []
        for path in paths:
            line = []
            for x, y in path:
                lon, lat = mercator_to_lonlat(x, y)
                line.append([lon, lat])
            if line:
                line_strings.append(line)
        if not line_strings:
            return None
        if len(line_strings) == 1:
            return {"type": "LineString", "coordinates": line_strings[0]}
        return {"type": "MultiLineString", "coordinates": line_strings}

    if geometry_type == "esriGeometryPolygon":
        rings = geometry.get("rings", [])
        converted = []
        for ring in rings:
            converted_ring = []
            for x, y in ring:
                lon, lat = mercator_to_lonlat(x, y)
                converted_ring.append([lon, lat])
            if converted_ring:
                converted.append(converted_ring)
        if not converted:
            return None
        if len(converted) == 1:
            return {"type": "Polygon", "coordinates": converted}
        # Treat multiple rings as separate polygons when topology is unknown.
        return {"type": "MultiPolygon", "coordinates": [[ring] for ring in converted]}

    raise ValueError(f"Unsupported geometry type: {geometry_type}")


def export_feature_collection(
    layer: Dict[str, Any], fc_layer: Dict[str, Any], out_dir: Path, source_app_id: str
) -> Optional[Path]:
    """Write a single feature collection layer to disk as GeoJSON."""
    layer_def = fc_layer.get("layerDefinition", {})
    feature_set = fc_layer.get("featureSet", {})
    geometry_type = layer_def.get("geometryType")
    features = feature_set.get("features", [])
    layer_name = layer_def.get("name") or layer.get("title") or layer.get("id") or "layer"
    file_name = f"atlas_of_informality_{sanitize_name(layer_name)}.geojson"
    output_path = out_dir / file_name

    geojson_features: List[Dict[str, Any]] = []
    for feature in features:
        geometry = convert_geometry(feature.get("geometry", {}), geometry_type)
        if geometry is None:
            continue
        properties = feature.get("attributes", {}) or {}
        geojson_features.append({"type": "Feature", "geometry": geometry, "properties": properties})

    if not geojson_features:
        return None

    payload = {
        "type": "FeatureCollection",
        "features": geojson_features,
        "metadata": {
            "source_app_id": source_app_id,
            "source_layer_id": layer.get("id"),
            "source_layer_title": layer.get("title"),
            "geometry_type": geometry_type,
            "feature_count": len(geojson_features),
        },
    }

    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def process_webmap(input_path: Path, output_dir: Path) -> List[Path]:
    """Extract feature collection layers from a downloaded ArcGIS web map."""
    data = json.loads(input_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    exported_paths: List[Path] = []

    for layer in data.get("operationalLayers", []):
        feature_collection = layer.get("featureCollection")
        if not feature_collection:
            continue
        for fc_layer in feature_collection.get("layers", []):
            geometry_type = (
                fc_layer.get("layerDefinition", {}).get("geometryType") or ""
            ).strip()
            if not geometry_type:
                continue
            exported = export_feature_collection(
                layer, fc_layer, output_dir, source_app_id="110e3d637cce4fe7bc41c4e5cd3f9d21"
            )
            if exported:
                exported_paths.append(exported)

    return exported_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/atlas_of_informality_webmap.json"),
        help="Path to the downloaded WebMap JSON definition.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/atlas_of_informality"),
        help="Directory for the exported GeoJSON files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    exported = process_webmap(args.input, args.output_dir)
    if not exported:
        raise SystemExit("No feature collection layers were exported.")
    print("Exported:")
    for path in exported:
        print(f" - {path}")


if __name__ == "__main__":
    main()
