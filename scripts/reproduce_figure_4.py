"""Recompute the four economic-distress maps reported as manuscript Figure 4.

The script starts with the shared ACS tables and Census county boundaries, builds
each index, joins it to geometry, and writes both the calculated data and a
four-panel PNG.  It never calls a web service and every input path is derived
from this repository.  Case D's two large GeoPackages are documented external
files; see ``Case_D_Goal_Oriented/DATA_AVAILABILITY.md`` before running.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CASE_STUDY = ROOT / "Analytical Specification Case Study"
CONTIGUOUS_EXCLUSIONS = {"02", "15", "60", "66", "69", "72", "78"}
LOW_INCOME_BINS = [f"B19001_00{i}E" for i in range(2, 7)]
HIGHER_DEGREES = [f"B15003_0{i}E" for i in range(22, 26)]
LESS_THAN_HIGH_SCHOOL = [f"B15003_0{i}E" for i in range(2, 17)]


def ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Return a share and preserve missing/zero denominators as missing."""
    return numerator.astype(float).div(denominator.astype(float).replace(0, np.nan))


def add_six_indicators(frame: pd.DataFrame, education_columns: list[str]) -> pd.DataFrame:
    """Calculate the six adverse ACS indicators used by every case."""
    data = frame.copy()
    data["low_education"] = ratio(data[education_columns].sum(axis=1), data["B15003_001E"])
    data["poverty"] = ratio(data["B17001_002E"], data["B17001_001E"])
    data["unemployment"] = ratio(data["B23025_005E"], data["B23025_002E"])
    data["low_income"] = ratio(data[LOW_INCOME_BINS].sum(axis=1), data["B19001_001E"])
    data["ssi"] = ratio(data["B19056_002E"], data["B19056_001E"])
    data["snap"] = ratio(data["B19058_002E"], data["B19058_001E"])
    return data


def minmax_index(data: pd.DataFrame) -> pd.DataFrame:
    """Build the fully specified index: mean of six min--max scaled shares."""
    indicators = ["low_education", "poverty", "unemployment", "low_income", "ssi", "snap"]
    for name in indicators:
        lower, upper = data[name].min(), data[name].max()
        data[f"{name}_scaled"] = (data[name] - lower) / (upper - lower)
    data["economic_distress_index"] = data[[f"{name}_scaled" for name in indicators]].mean(axis=1)
    return data


def percentile_index(data: pd.DataFrame) -> pd.DataFrame:
    """Build the indicator-specified index: mean of six county percentile ranks."""
    indicators = ["low_education", "poverty", "unemployment", "low_income", "ssi", "snap"]
    for name in indicators:
        data[f"{name}_percentile"] = data[name].rank(pct=True, method="average")
    data["economic_distress_index"] = data[[f"{name}_percentile" for name in indicators]].mean(axis=1)
    return data


def zscore_index(data: pd.DataFrame) -> pd.DataFrame:
    """Build the goal-oriented index: 50 + 10 times the mean six-indicator z score."""
    indicators = ["low_education", "poverty", "unemployment", "low_income", "ssi", "snap"]
    zscores = []
    for name in indicators:
        zname = f"{name}_zscore"
        data[zname] = (data[name] - data[name].mean()) / data[name].std(ddof=0)
        zscores.append(zname)
    data["economic_distress_index"] = 50 + 10 * data[zscores].mean(axis=1)
    return data


def join_counties(data: pd.DataFrame, boundaries: Path, key: str = "GEOID") -> gpd.GeoDataFrame:
    """Join one ACS row to each contiguous-US county boundary and project for plotting."""
    counties = gpd.read_file(boundaries)
    counties["GEOID"] = counties["GEOID"].astype(str).str.zfill(5)
    counties = counties[~counties["STATEFP"].astype(str).str.zfill(2).isin(CONTIGUOUS_EXCLUSIONS)]
    data = data.copy()
    data[key] = data[key].astype(str).str.replace(".0", "", regex=False).str.zfill(5)
    joined = counties.merge(data, left_on="GEOID", right_on=key, how="inner")
    if len(joined) < 3_000:
        raise ValueError(f"Only {len(joined)} ACS counties joined to {boundaries}; expected a contiguous-US county layer.")
    if len(joined) != len(data):
        print(f"Note: joined {len(joined)} of {len(data)} ACS rows; boundary-vintage county changes account for unmatched rows.")
    return joined.to_crs(5070)


def b_and_human_cases() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Return reproducible human-reference and fully specified Case B layers."""
    folder = CASE_STUDY / "Case_B_Fully_Specified" / "agent_artifacts" / "data_retrieval"
    acs = pd.read_csv(folder / "download_the_386195.csv")
    # The human reference and Case B use the same declared six components and
    # equal-weight min--max aggregation; separate outputs retain the manuscript panels.
    data = add_six_indicators(acs, HIGHER_DEGREES)
    # Case B operationalizes low education as less than some college: one minus
    # the share in ACS B15003 categories 019--025.
    some_college_or_higher = [f"B15003_0{i}E" for i in range(19, 26)]
    data["low_education"] = 1 - ratio(data[some_college_or_higher].sum(axis=1), data["B15003_001E"])
    data = minmax_index(data)
    boundary = folder / "download_the_599189.gpkg"
    return join_counties(data, boundary), join_counties(data, boundary)


def c_case() -> gpd.GeoDataFrame:
    """Return the Case C percentile-rank layer from its own shared raw inputs."""
    folder = CASE_STUDY / "Case_C_Indicator_Specified" / "agent_artifacts" / "data_retrieval"
    acs = pd.read_csv(folder / "download_the_622091.csv")
    # No-bachelor's education is total minus bachelor's, master's, professional, doctorate.
    no_bachelors = [column for column in acs.columns if column.startswith("B15003_") and column not in HIGHER_DEGREES + ["B15003_001E"]]
    data = percentile_index(add_six_indicators(acs, no_bachelors))
    return join_counties(data, folder / "download_the_968200.gpkg")


def d_case() -> gpd.GeoDataFrame:
    """Return the Case D z-score layer, using its shared ACS table and county GeoPackage."""
    folder = CASE_STUDY / "Case_D_Goal_Oriented" / "agent_artifacts"
    boundary = folder / "data_discovery" / "county_edi_2017_2021.gpkg"
    if not boundary.exists():
        raise FileNotFoundError(
            f"Missing {boundary.relative_to(ROOT)}. Download it to that relative path and verify its checksum "
            "as instructed in Analytical Specification Case Study/Case_D_Goal_Oriented/DATA_AVAILABILITY.md."
        )
    acs = pd.read_csv(folder / "data_discovery" / "acs_2017_2021_county_edi_variables.csv")
    acs = acs.rename(columns={"FIPS": "GEOID"})
    # Case D's supplied CSV already contains the six derived adverse shares.
    data = acs.copy()
    data["low_education"] = data["pct_less_than_high_school"]
    data["poverty"] = data["pct_below_poverty"]
    data["unemployment"] = data["pct_unemployment"]
    data["low_income"] = data["pct_less_than_30k"]
    data["ssi"] = data["pct_with_ssi"]
    data["snap"] = data["pct_with_snap_public_assistance"]
    return join_counties(zscore_index(data), boundary)


def plot_panel(ax: plt.Axes, layer: gpd.GeoDataFrame, title: str) -> None:
    """Plot a comparable five-class map without relying on a GUI application."""
    layer.plot(column="economic_distress_index", scheme="NaturalBreaks", k=5, cmap="YlOrRd", linewidth=0, ax=ax, legend=True,
               legend_kwds={"loc": "lower left", "title": "Economic distress"})
    ax.set_title(title, fontsize=10)
    ax.set_axis_off()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reproduction_output" / "figure_4")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    human, case_b = b_and_human_cases()
    case_c, case_d = c_case(), d_case()
    layers = [("human_reference", human, "(a) Human reference"), ("case_b", case_b, "(b) Fully specified"),
              ("case_c", case_c, "(c) Indicator specified"), ("case_d", case_d, "(d) Goal oriented")]
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    for axis, (name, layer, title) in zip(axes.flat, layers):
        layer.drop(columns="geometry").to_csv(args.output_dir / f"{name}_index.csv", index=False)
        layer.to_file(args.output_dir / f"{name}_index.geojson", driver="GeoJSON")
        plot_panel(axis, layer, title)
    fig.suptitle("Economic Distress Index Across the Contiguous United States", fontsize=14)
    fig.tight_layout()
    fig.savefig(args.output_dir / "figure_4.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote Figure 4 and four calculated layers to {args.output_dir}")


if __name__ == "__main__":
    main()
