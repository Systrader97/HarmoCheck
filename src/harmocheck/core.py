"""Calculation, presentation, and export engine for HarmoCheck."""

from __future__ import annotations

import math
import re
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


@dataclass(frozen=True)
class TEaThreshold:
    """Allowable total error thresholds, expressed as percentages."""

    optimal: float
    desirable: float
    minimum: float


@dataclass(frozen=True)
class AnalysisResult:
    """Calculation data and paths to the standard output artifacts."""

    raw_rows: int
    retained_rows: int
    periods: tuple[str, ...]
    years: tuple[int, ...]
    subpeer: pd.DataFrame
    peer: pd.DataFrame
    analyte: pd.DataFrame
    coverage: pd.DataFrame
    pdf_path: Path
    tables_path: Path
    charts_dir: Path
    chart_paths: Mapping[str, tuple[Path, ...]]


HARMONIZATION_LEVELS = ("Optimal", "Desirable", "Minimum", "Not acceptable", "Unknown")
RAW_COLUMNS = ("year", "qcMaterial", "participant", "analyte", "peerGroup", "subPeerGroup", "result")
DEFAULT_TEA: dict[str, TEaThreshold] = {
    "TSH": TEaThreshold(optimal=12.4, desirable=24.7, minimum=37.1),
    "Free T4": TEaThreshold(optimal=3.1, desirable=6.3, minimum=9.4),
    "Total T3": TEaThreshold(optimal=4.3, desirable=8.7, minimum=13.0),
}

DISPLAY_COLUMNS = {
    "subpeer": [
        "evaluationPeriod", "analyte", "peerGroup", "subPeerGroup",
        "pooledBias", "pooledCv", "tae", "harmonizationLevel",
    ],
    "peer": [
        "evaluationPeriod", "analyte", "peerGroup",
        "pooledBias", "pooledCv", "tae", "harmonizationLevel",
    ],
    "analyte": [
        "evaluationPeriod", "analyte", "pooledBias", "pooledCv", "tae", "harmonizationLevel",
    ],
}
DISPLAY_RENAMES = {
    "evaluationPeriod": "Year-Survey",
    "analyte": "Analyte",
    "peerGroup": "Peer group",
    "subPeerGroup": "Sub-peer group",
    "pooledBias": "Pooled Bias (%)",
    "pooledCv": "Pooled CV (%)",
    "tae": "TAE (%)",
    "harmonizationLevel": "Harmonization Level",
}


def classify_tae(tae: float, tea: Optional[TEaThreshold]) -> str:
    """Map total analytical error to the configured harmonization category."""

    if tea is None or pd.isna(tae):
        return "Unknown"
    if tae <= tea.optimal:
        return "Optimal"
    if tae <= tea.desirable:
        return "Desirable"
    if tae <= tea.minimum:
        return "Minimum"
    return "Not acceptable"


def percentile_inc(sorted_values: np.ndarray, percentile: float) -> float:
    """Excel-compatible PERCENTILE.INC with linear interpolation."""

    n = len(sorted_values)
    if n == 0:
        return float("nan")
    if n == 1:
        return float(sorted_values[0])
    p = min(1.0, max(0.0, percentile / 100.0))
    rank = (n - 1) * p + 1.0
    lower = int(math.floor(rank))
    fraction = rank - lower
    return float(sorted_values[lower - 1] + fraction * (sorted_values[min(lower, n - 1)] - sorted_values[lower - 1]))


def _normalise_heading(value: object) -> str:
    return re.sub(r"[\s_\-]", "", str(value).strip().lower())


def _find_column(columns: Iterable[object], aliases: set[str]) -> Optional[object]:
    normalised_aliases = {_normalise_heading(alias) for alias in aliases}
    return next((column for column in columns if _normalise_heading(column) in normalised_aliases), None)


def _canonicalise_sheet(frame: pd.DataFrame) -> pd.DataFrame:
    """Return raw-data columns from a compatible sheet, otherwise an empty frame."""

    aliases = {
        "year": {"year", "연도"},
        "qcMaterial": {"qcmaterial", "qc material", "ptmaterial", "pt material", "qc물질", "시료", "물질"},
        "participant": {"participant", "기관", "기관코드", "참가기관", "participantid"},
        "analyte": {"analyte", "검사항목", "항목", "검사종목"},
        "peerGroup": {"peergroup", "peer group", "peer", "peer그룹", "동일군"},
        "subPeerGroup": {"subpeergroup", "sub-peer group", "sub peer group", "subpeer", "세부동일군"},
        "result": {"result", "결과", "측정값", "검사결과"},
    }
    mapped = {name: _find_column(frame.columns, names) for name, names in aliases.items()}
    if all(mapped.values()):
        out = frame[[mapped[name] for name in RAW_COLUMNS]].copy()
        out.columns = list(RAW_COLUMNS)
    elif frame.shape[1] >= 7:
        # Legacy KEQAS workbooks store the raw-data contract in the first
        # seven columns; derived sheets are discarded if conversion fails.
        out = frame.iloc[:, :7].copy()
        out.columns = list(RAW_COLUMNS)
    else:
        return pd.DataFrame(columns=list(RAW_COLUMNS))

    out["year"] = pd.to_numeric(out["year"], errors="coerce")
    out["result"] = pd.to_numeric(out["result"], errors="coerce")
    for column in ("qcMaterial", "participant", "analyte", "peerGroup", "subPeerGroup"):
        out[column] = out[column].astype("string").fillna("").str.strip()
    out = out.dropna(subset=["year", "result"])
    if out.empty:
        return pd.DataFrame(columns=list(RAW_COLUMNS))
    out["year"] = out["year"].astype(int)
    return out


def _natural_key(value: object) -> tuple[object, ...]:
    return tuple(int(piece) if piece.isdigit() else piece.lower() for piece in re.split(r"(\d+)", str(value)))


def _survey_from_material(material: object) -> str:
    """Derive KEQAS survey A/B from the trailing PT-material number in column B."""

    match = re.search(r"(?:-|_)?(\d+)$", str(material).strip())
    if match is None:
        raise ValueError(f"QC material code has no trailing survey number: {material!r}")
    number = int(match.group(1))
    if 1 <= number <= 3:
        return "A"
    if 4 <= number <= 6:
        return "B"
    raise ValueError(
        f"QC material {material!r} ends in {number}; expected 01-03 for survey A or 04-06 for survey B."
    )


def _attach_evaluation_period(frame: pd.DataFrame) -> pd.DataFrame:
    """Create ``YYYY-A/B`` assessment labels directly from the QC-material column."""

    out = frame.copy()
    out["survey"] = out["qcMaterial"].map(_survey_from_material)
    out["evaluationPeriod"] = out["year"].astype(str) + "-" + out["survey"]
    period_counts = out.groupby("evaluationPeriod")["qcMaterial"].nunique()
    invalid = period_counts[period_counts != 3]
    if not invalid.empty:
        detail = ", ".join(f"{period} ({count} materials)" for period, count in invalid.items())
        raise ValueError(f"Each Year-Survey assessment must contain exactly three PT materials: {detail}")
    return out


def load_all_sheets(xlsx_path: str | Path) -> pd.DataFrame:
    """Read compatible raw-data worksheets and derive A/B from column B material codes."""

    try:
        workbook = pd.ExcelFile(xlsx_path)
    except Exception as exc:
        raise RuntimeError(f"Unable to open Excel workbook: {exc}") from exc

    frames: list[pd.DataFrame] = []
    try:
        for sheet in workbook.sheet_names:
            frame = _canonicalise_sheet(workbook.parse(sheet_name=sheet, header=0))
            if not frame.empty:
                frames.append(frame)
    finally:
        workbook.close()
    if not frames:
        raise RuntimeError("No valid raw data found. Check the Year through Result columns.")
    return _attach_evaluation_period(pd.concat(frames, ignore_index=True))


def apply_tukey_and_min_participants(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply Tukey exclusion, n>=10, complete coverage, and a two-peer minimum.

    A valid analyte assessment requires at least two peer groups that each
    retain data for all three PT materials.  An analyte represented by only
    one peer group cannot be used to assess nationwide harmonization.
    """

    key_columns = ["evaluationPeriod", "qcMaterial", "analyte", "peerGroup", "subPeerGroup"]
    retained: list[pd.DataFrame] = []
    for _, group in frame.groupby(key_columns, sort=False):
        values = np.sort(group["result"].dropna().to_numpy(dtype=float))
        if not len(values):
            continue
        q1, q3 = percentile_inc(values, 25), percentile_inc(values, 75)
        iqr = q3 - q1
        kept = group[group["result"].between(q1 - 1.5 * iqr, q3 + 1.5 * iqr)]
        if kept["participant"].nunique(dropna=True) >= 10:
            retained.append(kept)
    if not retained:
        return frame.iloc[0:0].copy()
    out = pd.concat(retained, ignore_index=True)

    # A peer group must itself cover the complete three-material survey.
    peer_coverage = out.groupby(["evaluationPeriod", "analyte", "peerGroup"])["qcMaterial"].nunique()
    complete_peers = peer_coverage[peer_coverage == 3].index
    out = out.set_index(["evaluationPeriod", "analyte", "peerGroup"]).loc[
        lambda indexed: indexed.index.isin(complete_peers)
    ].reset_index()
    if out.empty:
        return out

    # Keep an assessment only when two or more complete peer groups remain.
    peer_counts = out.groupby(["evaluationPeriod", "analyte"])["peerGroup"].nunique()
    eligible_assessments = peer_counts[peer_counts >= 2].index
    return out.set_index(["evaluationPeriod", "analyte"]).loc[
        lambda indexed: indexed.index.isin(eligible_assessments)
    ].reset_index()


def compute_subpeer_survey_stats(frame: pd.DataFrame) -> pd.DataFrame:
    key = ["evaluationPeriod", "qcMaterial", "analyte", "peerGroup", "subPeerGroup"]
    out = frame.groupby(key)["result"].agg(mean="mean", sd="std").reset_index()
    out["cv"] = np.where(out["mean"] != 0, out["sd"] / out["mean"] * 100, np.nan)
    peer_key = ["evaluationPeriod", "qcMaterial", "analyte", "peerGroup"]
    peer_means = out.groupby(peer_key)["mean"].mean().rename("peerMean")
    out = out.join(peer_means, on=peer_key)
    out["bias"] = np.where(
        out["peerMean"].notna() & out["peerMean"].ne(0),
        out["mean"].sub(out["peerMean"]).div(out["peerMean"]).abs() * 100,
        np.nan,
    )
    return out.drop(columns="peerMean")


def _rms(values: pd.Series) -> float:
    values = values.dropna().to_numpy(dtype=float)
    return math.sqrt(float(np.mean(np.square(values)))) if len(values) else float("nan")


def _pool(frame: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    out = frame.groupby(group_columns).agg(pooledBias=("bias", "mean"), pooledCv=("cv", _rms)).reset_index()
    out["tae"] = out["pooledBias"].abs() + 1.65 * out["pooledCv"]
    return out


def compute_subpeer_pooled(subpeer: pd.DataFrame) -> pd.DataFrame:
    return _pool(subpeer, ["evaluationPeriod", "analyte", "peerGroup", "subPeerGroup"])


def compute_peer_pooled(subpeer: pd.DataFrame) -> pd.DataFrame:
    material = _pool(subpeer, ["evaluationPeriod", "analyte", "qcMaterial", "peerGroup"])
    material = material.rename(columns={"pooledBias": "bias", "pooledCv": "cv"})
    return _pool(material, ["evaluationPeriod", "analyte", "peerGroup"])


def compute_analyte_pooled(subpeer: pd.DataFrame) -> pd.DataFrame:
    material = _pool(subpeer, ["evaluationPeriod", "analyte", "qcMaterial"])
    material = material.rename(columns={"pooledBias": "bias", "pooledCv": "cv"})
    return _pool(material, ["evaluationPeriod", "analyte"])


def _add_metadata(summary: pd.DataFrame, raw: pd.DataFrame, tea_map: Mapping[str, TEaThreshold]) -> pd.DataFrame:
    materials = raw.groupby(["evaluationPeriod", "analyte"])["qcMaterial"].agg(
        lambda values: ", ".join(sorted(map(str, values.unique()), key=_natural_key))
    ).rename("ptMaterials")
    out = summary.join(materials, on=["evaluationPeriod", "analyte"])
    out["ptMaterialCount"] = out["ptMaterials"].str.split(", ").str.len()
    out["harmonizationLevel"] = [
        classify_tae(float(tae), tea_map.get(str(analyte)))
        for tae, analyte in zip(out["tae"], out["analyte"])
    ]
    return out


def _period_key(period: object) -> tuple[int, int, str]:
    match = re.match(r"^(\d{4})-([AB])$", str(period))
    return (int(match.group(1)), 0 if match.group(2) == "A" else 1, str(period)) if match else (9999, 9, str(period))


def display_table(frame: pd.DataFrame, level: str) -> pd.DataFrame:
    """Return a user-facing level table with the requested columns and headings only."""

    if level not in DISPLAY_COLUMNS:
        raise ValueError(f"Unknown display level: {level}")
    out = frame.loc[:, DISPLAY_COLUMNS[level]].copy()
    out = out.sort_values(["evaluationPeriod", "analyte"], key=lambda series: series.map(_period_key) if series.name == "evaluationPeriod" else series, kind="stable")
    return out.rename(columns=DISPLAY_RENAMES)


def display_coverage(frame: pd.DataFrame) -> pd.DataFrame:
    """Show only assessment validation information in the UI and Excel workbook."""

    out = frame.loc[:, ["evaluationPeriod", "analyte", "PT_material_count"]].copy()
    out = out.sort_values(["evaluationPeriod", "analyte"], key=lambda series: series.map(_period_key) if series.name == "evaluationPeriod" else series, kind="stable")
    return out.rename(columns={"evaluationPeriod": "Year-Survey", "analyte": "Analyte", "PT_material_count": "PT Material Count"})


def generate_trend_charts(peer: pd.DataFrame, analyte: pd.DataFrame, output_dir: Path) -> dict[str, list[tuple[str, Path]]]:
    """Create Java-report-style peer and analyte trend charts for each analyte."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    # The output directory belongs to this report.  Clear old chart files so
    # that analytes removed by the current eligibility rules never reappear.
    for previous_chart in output_dir.glob("*.png"):
        previous_chart.unlink()
    definitions = (
        ("bias", "pooledBias", "Pooled Bias (%)"),
        ("cv", "pooledCv", "Pooled CV (%)"),
        ("tae", "tae", "TAE (%)"),
    )
    results: dict[str, list[tuple[str, Path]]] = {key: [] for key, _, _ in definitions}
    colors_cycle = ("#D81B60", "#FB8C00", "#0B8F3A", "#1E88E5", "#7B1FA2", "#00897B", "#6D4C41")

    for chart_key, metric, ylabel in definitions:
        for analyte_name in sorted(analyte["analyte"].dropna().unique(), key=str):
            peer_rows = peer[peer["analyte"].eq(analyte_name)].copy()
            analyte_rows = analyte[analyte["analyte"].eq(analyte_name)].copy()
            periods = sorted(set(peer_rows["evaluationPeriod"]).union(analyte_rows["evaluationPeriod"]), key=_period_key)
            if not periods:
                continue
            figure, axis = plt.subplots(figsize=(10.2, 6.2))
            for index, (peer_name, group) in enumerate(peer_rows.groupby("peerGroup", sort=True)):
                values = group.set_index("evaluationPeriod")[metric].reindex(periods)
                axis.plot(periods, values, marker="o", linewidth=2, markersize=5, color=colors_cycle[index % len(colors_cycle)], label=str(peer_name))
            values = analyte_rows.set_index("evaluationPeriod")[metric].reindex(periods)
            axis.plot(periods, values, marker="o", linewidth=2.6, markersize=5, color="#111111", label="Analyte level")
            axis.set_title(f"Semestral {ylabel.replace(' (%)', '')} Trend of {analyte_name}", fontsize=16, fontweight="bold", pad=14)
            axis.set_xlabel("Year-Survey", fontsize=11, fontweight="bold")
            axis.set_ylabel(ylabel, fontsize=11, fontweight="bold")
            axis.grid(True, linestyle="--", linewidth=0.7, alpha=0.65)
            axis.set_axisbelow(True)
            axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=3, frameon=False, fontsize=9)
            figure.subplots_adjust(left=0.11, right=0.96, top=0.88, bottom=0.22)
            safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(analyte_name)).strip("_")
            path = output_dir / f"{chart_key.title()}_Trend_{safe_name}.png"
            figure.savefig(path, dpi=190)
            plt.close(figure)
            results[chart_key].append((str(analyte_name), path))
    return results


def _report_header(pdf: canvas.Canvas, page_width: float, page_height: float) -> None:
    pdf.setFillColor(colors.HexColor("#0C5B38"))
    pdf.rect(0, page_height - 1.45 * cm, page_width, 1.45 * cm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(1.5 * cm, page_height - 0.92 * cm, "HarmoCheck")
    pdf.setFont("Helvetica", 8.5)
    pdf.drawRightString(page_width - 1.5 * cm, page_height - 0.92 * cm, "Semestral assessment | 3 PT materials per period")


def _link_text(pdf: canvas.Canvas, text: str, destination: str, x: float, y: float, bold: bool = False) -> float:
    font = "Helvetica-Bold" if bold else "Helvetica"
    size = 11.5 if bold else 10.5
    pdf.setFont(font, size)
    pdf.setFillColor(colors.HexColor("#123D29"))
    pdf.drawString(x, y, text)
    width = stringWidth(text, font, size)
    pdf.linkAbsolute("", destination, Rect=(x, y - 2, x + width, y + size), thickness=0)
    return y - (0.72 * cm if bold else 0.55 * cm)


def _draw_contents(pdf: canvas.Canvas, page_width: float, page_height: float) -> None:
    _report_header(pdf, page_width, page_height)
    x, y = 1.7 * cm, page_height - 3.0 * cm
    pdf.setFillColor(colors.HexColor("#123D29"))
    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawString(x, y, "Contents")
    y -= 1.0 * cm
    y = _link_text(pdf, "1. Nationwide Harmonization Evaluation Results", "subpeer-first", x, y, bold=True)
    y = _link_text(pdf, "(1) Sub-peer group level", "subpeer-first", x + 0.55 * cm, y)
    y = _link_text(pdf, "(2) Peer group level", "peer-first", x + 0.55 * cm, y)
    y = _link_text(pdf, "(3) Analyte level", "analyte-first", x + 0.55 * cm, y)
    y -= 0.45 * cm
    y = _link_text(pdf, "2. Trends in Harmonization", "trend-bias-first", x, y, bold=True)
    y = _link_text(pdf, "(1) Bias Trend", "trend-bias-first", x + 0.55 * cm, y)
    y = _link_text(pdf, "(2) CV Trend", "trend-cv-first", x + 0.55 * cm, y)
    _link_text(pdf, "(3) TAE Trend", "trend-tae-first", x + 0.55 * cm, y)


def _ellipsize(pdf: canvas.Canvas, value: object, width: float, font: str = "Helvetica", size: float = 6.7) -> str:
    text = str(value)
    if stringWidth(text, font, size) <= width - 0.12 * cm:
        return text
    suffix = "..."
    while text and stringWidth(text + suffix, font, size) > width - 0.12 * cm:
        text = text[:-1]
    return text + suffix


def _draw_table_section(
    pdf: canvas.Canvas,
    frame: pd.DataFrame,
    level: str,
    period: str,
    first_bookmark: str,
    page_width: float,
    page_height: float,
) -> None:
    title = f"Nationwide Harmonization Evaluation at {level} level (Year-Survey: {period})"
    displayed = display_table(frame[frame["evaluationPeriod"].eq(period)], {"Sub-peer group": "subpeer", "Peer group": "peer", "Analyte": "analyte"}[level])
    columns = list(displayed.columns)
    width_map = {
        "Sub-peer group": [1.65, 1.5, 2.15, 3.15, 1.9, 1.75, 1.2, 2.65],
        "Peer group": [1.75, 1.7, 3.6, 1.9, 1.75, 1.2, 2.65],
        "Analyte": [1.85, 2.2, 1.9, 1.75, 1.2, 2.75],
    }
    widths = [value * cm for value in width_map[level]]
    chunks = [displayed.iloc[index:index + 43] for index in range(0, len(displayed), 43)] or [displayed]
    for index, chunk in enumerate(chunks):
        if index:
            pdf.showPage()
        _report_header(pdf, page_width, page_height)
        if index == 0:
            pdf.bookmarkPage(first_bookmark)
        x, y = 1.45 * cm, page_height - 2.35 * cm
        pdf.setFillColor(colors.HexColor("#123D29"))
        pdf.setFont("Helvetica-Bold", 11.5)
        pdf.drawString(x, y, title if index == 0 else f"{title} (continued)")
        y -= 0.57 * cm
        for column_index, column in enumerate(columns):
            left = x + sum(widths[:column_index])
            pdf.setFillColor(colors.HexColor("#0C5B38"))
            pdf.rect(left, y - 0.39 * cm, widths[column_index], 0.45 * cm, fill=1, stroke=0)
            pdf.setFillColor(colors.white)
            pdf.setFont("Helvetica-Bold", 6.3)
            pdf.drawString(left + 0.07 * cm, y - 0.23 * cm, _ellipsize(pdf, column, widths[column_index], "Helvetica-Bold", 6.3))
        y -= 0.48 * cm
        pdf.setFont("Helvetica", 6.7)
        for row_index, (_, row) in enumerate(chunk.iterrows()):
            if row_index % 2 == 0:
                pdf.setFillColor(colors.HexColor("#F0F8F3"))
                pdf.rect(x, y - 0.285 * cm, sum(widths), 0.34 * cm, fill=1, stroke=0)
            level_value = str(row.get("Harmonization Level", ""))
            if level_value == "Not acceptable":
                text_color = colors.HexColor("#A51D1D")
            elif level_value == "Optimal":
                text_color = colors.HexColor("#0C5B38")
            else:
                text_color = colors.HexColor("#1B2A20")
            for column_index, column in enumerate(columns):
                left = x + sum(widths[:column_index])
                value = row[column]
                text = f"{float(value):.2f}" if column in {"Pooled Bias (%)", "Pooled CV (%)", "TAE (%)"} and pd.notna(value) else str(value)
                pdf.setFillColor(text_color if column == "Harmonization Level" else colors.HexColor("#1B2A20"))
                pdf.drawString(left + 0.07 * cm, y - 0.18 * cm, _ellipsize(pdf, text, widths[column_index]))
            y -= 0.35 * cm


def _draw_chart_page(
    pdf: canvas.Canvas,
    chart_path: Path,
    chart_title: str,
    bookmark: Optional[str],
    page_width: float,
    page_height: float,
) -> None:
    _report_header(pdf, page_width, page_height)
    if bookmark:
        pdf.bookmarkPage(bookmark)
    pdf.setFillColor(colors.HexColor("#123D29"))
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(1.45 * cm, page_height - 2.25 * cm, chart_title)
    image_width = page_width - 2.9 * cm
    image_height = page_height - 4.4 * cm
    pdf.drawImage(str(chart_path), 1.45 * cm, 1.4 * cm, width=image_width, height=image_height, preserveAspectRatio=True, anchor="c", mask="auto")


def generate_pdf_report(
    subpeer: pd.DataFrame,
    peer: pd.DataFrame,
    analyte: pd.DataFrame,
    chart_paths: Mapping[str, list[tuple[str, Path]]],
    output_dir: Path,
) -> Path:
    """Write a linked table-of-contents report with level tables and trend charts."""

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "HarmoCheck_Report.pdf"
    pdf = canvas.Canvas(str(path), pagesize=A4, pageCompression=1)
    page_width, page_height = A4
    _draw_contents(pdf, page_width, page_height)
    pdf.showPage()

    periods = sorted(analyte["evaluationPeriod"].dropna().unique(), key=_period_key)
    levels = (
        ("Sub-peer group", subpeer, "subpeer-first"),
        ("Peer group", peer, "peer-first"),
        ("Analyte", analyte, "analyte-first"),
    )
    # Follow the table of contents: all Year-Surveys for the sub-peer level,
    # then all peer-level tables, then all analyte-level tables.
    for level, frame, first_bookmark in levels:
        for period_index, period in enumerate(periods):
            bookmark = first_bookmark if period_index == 0 else f"{level}-{period}"
            _draw_table_section(pdf, frame, level, str(period), bookmark, page_width, page_height)
            pdf.showPage()

    chart_titles = {"bias": "Bias Trend", "cv": "CV Trend", "tae": "TAE Trend"}
    for chart_key in ("bias", "cv", "tae"):
        entries = chart_paths.get(chart_key, [])
        for index, (analyte_name, chart_path) in enumerate(entries):
            _draw_chart_page(
                pdf,
                chart_path,
                f"{chart_titles[chart_key]} - {analyte_name}",
                f"trend-{chart_key}-first" if index == 0 else None,
                page_width,
                page_height,
            )
            if not (chart_key == "tae" and index == len(entries) - 1):
                pdf.showPage()
    pdf.save()
    return path


def save_tables_excel(subpeer: pd.DataFrame, peer: pd.DataFrame, analyte: pd.DataFrame, coverage: pd.DataFrame, output_dir: Path) -> Path:
    """Save user-facing labels and omit internal PT-material metadata columns."""

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "HarmoCheck_Tables.xlsx"
    tables = (
        ("SurveyValidation", display_coverage(coverage)),
        ("SubPeerGroupLevel", display_table(subpeer, "subpeer")),
        ("PeerGroupLevel", display_table(peer, "peer")),
        ("AnalyteLevel", display_table(analyte, "analyte")),
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, table in tables:
            table.to_excel(writer, sheet_name=sheet_name, index=False)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                font = copy(cell.font)
                font.bold = True
                font.color = "FFFFFF"
                cell.font = font
                fill = copy(cell.fill)
                fill.fill_type = "solid"
                fill.fgColor.rgb = "FF0C5B38"
                cell.fill = fill
            for column in sheet.columns:
                letter = column[0].column_letter
                width = min(40, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
                sheet.column_dimensions[letter].width = width
    return path


def analyze_workbook(
    xlsx_path: str | Path,
    output_dir: str | Path,
    tea_map: Optional[Mapping[str, TEaThreshold]] = None,
    generate_charts: bool = True,
) -> AnalysisResult:
    """Run the complete semestral assessment, exports, and linked report generation."""

    raw = load_all_sheets(xlsx_path)
    filtered = apply_tukey_and_min_participants(raw)
    if filtered.empty:
        raise RuntimeError("No complete 3-PT assessment data remain after Tukey and n>=10 filtering.")
    subpeer_stats = compute_subpeer_survey_stats(filtered)
    thresholds = dict(DEFAULT_TEA if tea_map is None else tea_map)
    subpeer = _add_metadata(compute_subpeer_pooled(subpeer_stats), filtered, thresholds)
    peer = _add_metadata(compute_peer_pooled(subpeer_stats), filtered, thresholds)
    analyte = _add_metadata(compute_analyte_pooled(subpeer_stats), filtered, thresholds)
    coverage = (
        filtered.groupby(["evaluationPeriod", "analyte"])["qcMaterial"].agg(
            PT_material_count="nunique", PT_materials=lambda values: ", ".join(sorted(map(str, values.unique()), key=_natural_key))
        ).reset_index()
    )
    output = Path(output_dir)
    charts_dir = output / "TrendCharts"
    chart_paths = generate_trend_charts(peer, analyte, charts_dir)
    if not generate_charts:
        # Keep report charts available; the flag only controls the optional
        # standalone chart directory after report generation.
        for chart_file in charts_dir.glob("*.png"):
            chart_file.unlink()
        charts_dir.mkdir(parents=True, exist_ok=True)
        chart_paths = generate_trend_charts(peer, analyte, charts_dir)
    pdf_path = generate_pdf_report(subpeer, peer, analyte, chart_paths, output)
    tables_path = save_tables_excel(subpeer, peer, analyte, coverage, output)
    periods = tuple(sorted(filtered["evaluationPeriod"].unique(), key=_period_key))
    years = tuple(sorted(int(year) for year in raw["year"].unique()))
    visible_chart_paths = {key: tuple(path for _, path in entries) for key, entries in chart_paths.items()}
    return AnalysisResult(
        len(raw), len(filtered), periods, years, subpeer, peer, analyte,
        coverage, pdf_path, tables_path, charts_dir, visible_chart_paths,
    )
