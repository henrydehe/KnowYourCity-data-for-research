#!/usr/bin/env python3
"""Download Know Your City settlements for a specific country."""
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import zipfile

import requests
import shapefile  # type: ignore
import sys

FILTER_ENDPOINT = "https://sdinet.org/wp-content/themes/sdinet-2022/ajax/get-filter.php"
SETTLEMENT_URL = "https://sdinet.org/settlement/{form_id}/{ona_id}"
WGS84_PRJ = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,'
    "298.257223563]],PRIMEM['Greenwich',0],UNIT['degree',0.0174532925199433]]"
)
SETTLEMENT_RE = re.compile(r"var settlement = (\{.*?\});", re.S)
SHAPE_RE = re.compile(r"var shape = (\[\[.*?\]\]);", re.S)


@dataclass
class SettlementRecord:
    """Structured settlement information."""

    settlement_id: str
    city: str
    name: str
    country: str
    url: str


@dataclass
class ParsedSettlement:
    """Parsed payload ready for export."""

    rec_id: int
    city: str
    name: str
    last_updated: str
    year: Optional[int]
    population: Optional[int]
    area_acres: Optional[float]
    structures: Optional[int]

    geometry: List[Tuple[float, float]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--country",
        default="Nigeria",
        help="Country name key, defaults to 'Nigeria' (must match the API key)",
    )
    parser.add_argument(
        "--output",
        default="kyc_cln_data_Nigeria_latest",
        help="Output shapefile base name (without extension)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="Seconds to sleep between settlement page requests",
    )
    return parser.parse_args()


def fetch_filter_payload() -> Dict:
    response = requests.get(FILTER_ENDPOINT, timeout=60)
    response.raise_for_status()
    return response.json()


def list_country_settlements(payload: Dict, country_key: str) -> List[SettlementRecord]:
    verified = payload.get("verified", {})
    if country_key not in verified:
        raise KeyError(f"Country '{country_key}' not found in filter data")

    settlements: List[SettlementRecord] = []
    country_entries = verified[country_key]
    for city, items in country_entries.items():
        if city == "info":
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            form_id = item.get("form_id")
            ona_id = item.get("ona_id")
            name = item.get("name", "Unknown")
            if not form_id or not ona_id:
                continue
            url = SETTLEMENT_URL.format(form_id=form_id, ona_id=ona_id)
            settlements.append(
                SettlementRecord(
                    settlement_id=str(ona_id),
                    city=str(city),
                    name=str(name),
                    country=country_key,
                    url=url,
                )
            )
    return settlements


def _safe_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.strip()
        if not value or value.lower() in {"na", "n/a", "nan"}:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Optional[str]) -> Optional[int]:
    number = _safe_float(value)
    if number is None:
        return None
    return int(round(number))


def _format_date(raw_value: Optional[str]) -> Tuple[str, Optional[int]]:
    if not raw_value:
        return "Unknown", None
    text = raw_value.strip()
    if not text:
        return "Unknown", None

    if "T" in text:
        text = text.split("T", 1)[0]

    parsed: Optional[datetime] = None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue

    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return raw_value, None

    return parsed.strftime("%d.%m.%Y"), parsed.year


def parse_settlement_page(html: str) -> Tuple[Dict, List[Tuple[float, float]]]:
    settlement_match = SETTLEMENT_RE.search(html)
    if not settlement_match:
        raise ValueError("Could not locate settlement payload in page")
    payload = json.loads(settlement_match.group(1))

    shape_match = SHAPE_RE.search(html)
    if not shape_match:
        raise ValueError("Could not locate geometry payload in page")
    shape_raw = json.loads(shape_match.group(1))
    geometry: List[Tuple[float, float]] = []
    for lat_str, lon_str in shape_raw:
        lat = float(lat_str)
        lon = float(lon_str)
        geometry.append((lon, lat))

    if geometry and geometry[0] != geometry[-1]:
        geometry.append(geometry[0])

    return payload, geometry


def build_parsed_records(
    settlements: Iterable[SettlementRecord], sleep_seconds: float
) -> Tuple[List[ParsedSettlement], List[Tuple[SettlementRecord, str]]]:
    session = requests.Session()
    session.headers.update({"User-Agent": "kyc-downloader/0.1"})

    parsed: List[ParsedSettlement] = []
    failures: List[Tuple[SettlementRecord, str]] = []
    for idx, settlement in enumerate(settlements, start=1):
        try:
            response = session.get(settlement.url, timeout=60)
            payload, geometry = parse_settlement_page(response.text)
        except requests.RequestException as exc:
            message = f"{settlement.name} ({settlement.url}) - {exc}"
            print(f"Warning: {message}", file=sys.stderr)
            failures.append((settlement, str(exc)))
            continue
        except ValueError as exc:
            status = response.status_code
            message = (
                f"{settlement.name} ({settlement.url}) - "
                f"HTTP {status}: {exc}"
            )
            print(f"Warning: {message}", file=sys.stderr)
            failures.append((settlement, str(exc)))
            continue

        last_updated = payload.get("section_A/A1a_Last_Updated") or payload.get(
            "section_A/A1_Profile_Date"
        )
        formatted_date, year = _format_date(last_updated)

        population = _safe_int(payload.get("section_C/C11_Population_Estimate"))
        if not population or population <= 0:
            households = _safe_float(payload.get("section_C/C9_Households")) or 0
            hh_size = _safe_float(payload.get("section_C/C10_Household_Size")) or 0
            computed = int(round(households * hh_size))
            population = computed if computed > 0 else None

        area_acres = _safe_float(payload.get("section_B/B2b_Area_acres"))
        structures = _safe_int(payload.get("section_C/C5_Structures_Total"))

        parsed.append(
            ParsedSettlement(
                rec_id=idx,
                city=settlement.city,
                name=settlement.name,
                last_updated=formatted_date,
                year=year,
                population=population,
                area_acres=area_acres,
                structures=structures,
                geometry=geometry,
            )
        )

        time.sleep(sleep_seconds)

    return parsed, failures


def write_shapefile(records: List[ParsedSettlement], output_base: Path) -> Path:
    writer = shapefile.Writer(str(output_base))
    writer.autoBalance = 1

    writer.field("Id", "N", 6, 0)
    writer.field("Country", "C", size=50)
    writer.field("City", "C", size=100)
    writer.field("Settlement", "C", size=150)
    writer.field("Last_updat", "C", size=20)
    writer.field("kyc_pop", "N", 12, 0)
    writer.field("kyc_area", "N", 10, 3)
    writer.field("kyc_struct", "N", 10, 0)
    writer.field("kyc_year", "N", 6, 0)

    for record in records:
        writer.record(
            record.rec_id,
            "Nigeria",
            record.city,
            record.name,
            record.last_updated,
            record.population or 0,
            record.area_acres or 0.0,
            record.structures or 0,
            record.year or 0,
        )
        writer.poly([record.geometry])

    writer.close()

    prj_path = output_base.with_suffix(".prj")
    prj_path.write_text(WGS84_PRJ, encoding="utf-8")
    cpg_path = output_base.with_suffix(".cpg")
    cpg_path.write_text("UTF-8", encoding="utf-8")

    zip_path = output_base.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for suffix in (".cpg", ".dbf", ".prj", ".shp", ".shx"):
            file_path = output_base.with_suffix(suffix)
            archive.write(file_path, arcname=output_base.name + suffix)

    for suffix in (".cpg", ".dbf", ".prj", ".shp", ".shx"):
        file_path = output_base.with_suffix(suffix)
        if file_path.exists():
            file_path.unlink()

    return zip_path


def main() -> None:
    args = parse_args()
    payload = fetch_filter_payload()
    settlements = list_country_settlements(payload, args.country)
    if not settlements:
        raise SystemExit(f"No settlements found for country '{args.country}'")

    parsed_records, failures = build_parsed_records(settlements, args.sleep)
    if not parsed_records:
        raise SystemExit("No settlements could be downloaded successfully")
    output_base = Path(args.output)
    zip_path = write_shapefile(parsed_records, output_base)

    print(
        f"Wrote {len(parsed_records)} settlements to {zip_path.name} "
        f"({zip_path.resolve()})"
    )
    if failures:
        print(f"Skipped {len(failures)} settlement(s); see warnings above.")


if __name__ == "__main__":
    main()
