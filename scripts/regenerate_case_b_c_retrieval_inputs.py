"""Regenerate the Case B and C upstream retrieval artifacts.

The script creates the four files recorded in the workflow provenance. It uses
the archived Case D county data for the 2021 ACS variables and the official
2024 Census county-boundary archive for the raw national boundary retrieval.
All repository paths are relative to this file.

Example:
    python scripts/regenerate_case_b_c_retrieval_inputs.py \
      --boundary-archive /path/to/cb_2024_us_county_500k.zip
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CASE_D_INPUT = (
    ROOT
    / "Analytical Specification Case Study"
    / "Case_D_Goal_Oriented"
    / "agent_artifacts"
    / "data_discovery"
    / "county_edi_2017_2021.gpkg"
)
CASE_B_OUTPUT = ROOT / "Analytical Specification Case Study" / "Case_B_Fully_Specified" / "agent_artifacts" / "data_retrieval"
CASE_C_OUTPUT = ROOT / "Analytical Specification Case Study" / "Case_C_Indicator_Specified" / "agent_artifacts" / "data_retrieval"

# These are the variables explicitly requested by the Case B and C workflows.
ACS_VARIABLES = [
    "B15003_001E", "B15003_017E", "B15003_018E", "B15003_019E",
    "B15003_020E", "B15003_021E", "B15003_022E", "B15003_023E",
    "B15003_024E", "B15003_025E", "B17001_001E", "B17001_002E",
    "B19001_001E", "B19001_002E", "B19001_003E", "B19001_004E",
    "B19001_005E", "B19001_006E", "B19056_001E", "B19056_002E",
    "B19058_001E", "B19058_002E", "B23025_002E", "B23025_005E",
]


def build_acs_input() -> pd.DataFrame:
    """Create the 3,108-row contiguous-U.S. ACS workflow input table."""
    source = gpd.read_file(CASE_D_INPUT)
    table = pd.DataFrame(source[["GEOID", "NAME", "STATEFP", "COUNTYFP", *ACS_VARIABLES]])
    table["state_fips"] = table.pop("STATEFP").astype(str).str.zfill(2)
    table["county_fips"] = table.pop("COUNTYFP").astype(str).str.zfill(3)
    table["year"] = "2021"
    table["survey_period"] = "2017-2021"
    table["source"] = "ACS 2021"
    if len(table) != 3108:
        raise ValueError(f"Expected 3,108 ACS rows, found {len(table)}.")
    return table


def write_gpkg(counties: gpd.GeoDataFrame, output_file: Path) -> None:
    """Write a national county-boundary retrieval artifact with a stable layer."""
    if output_file.exists():
        output_file.unlink()
    counties.to_file(output_file, layer="us_counties", driver="GPKG", index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--boundary-archive", type=Path, required=True)
    args = parser.parse_args()

    if not CASE_D_INPUT.is_file():
        raise FileNotFoundError(f"Missing archived Case D input: {CASE_D_INPUT}")
    if not args.boundary_archive.is_file():
        raise FileNotFoundError(f"Missing Census boundary archive: {args.boundary_archive}")

    # The upstream boundary retrieval is national (3,235 county equivalents);
    # each downstream workflow applies its contiguous-U.S. scope separately.
    counties = gpd.read_file(args.boundary_archive)
    if len(counties) != 3235:
        raise ValueError(f"Expected 3,235 county equivalents, found {len(counties)}.")

    acs = build_acs_input()
    for directory, csv_name, gpkg_name in (
        (CASE_B_OUTPUT, "download_the_386195.csv", "download_the_599189.gpkg"),
        (CASE_C_OUTPUT, "download_the_622091.csv", "download_the_968200.gpkg"),
    ):
        directory.mkdir(parents=True, exist_ok=True)
        acs.to_csv(directory / csv_name, index=False)
        write_gpkg(counties, directory / gpkg_name)


if __name__ == "__main__":
    main()
