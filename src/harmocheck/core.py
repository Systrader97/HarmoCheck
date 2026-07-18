"""Calculation and export engine for HarmoCheck.

Each assessment is intentionally limited to the three PT materials distributed
in one KEQAS EQA semester.  The module has no UI dependencies and can therefore
also be used in automated validation workflows.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas


@dataclass(frozen=True)
class TEaThreshold:
    """Allowable total error thresholds expressed as percentages."""

    optimal: float
    desirable: float
    minimum: float


@dataclass(frozen=True)
class AnalysisResult:
    """Completed calculation data and paths to the generated deliverables."""

    raw_rows: int
    retained_rows: int
    periods: tuple[str, ...]
    subpeer: pd.DataFrame
    peer: pd.DataFrame
    analyte: pd.DataFrame
    coverage: pd.DataFrame
    pdf_path: Path
    tables_path: Path
    charts_dir: Path


HARMONIZATION_LEVELS = ("Optimal", "Desirable", "Minimum", "Not acceptable", "Unknown")
RAW_COLUMNS = ("year", "qcMaterial", "participant", "analyte", "peerGroup", "subPeerGroup", "result")
PERIOD_COLUMN_ALIASES = {
    "semester", "half", "period", "evaluationperiod", "evaluation period",
    "반기", "평가반기", "평가기간", "조사차수", "차수",
}
DEFAULT_TEA: dict[str, TEaThreshold] = {
    "TSH": TEaThreshold(optimal=6.7, desirable=10.0, minimum=20.0),
    "Free T4": TEaThreshold(optimal=5.0, desirable=7.0, minimum=12.0),
    "Total T3": TEaThreshold(optimal=4.0, desirable=6.0, minimum=11.0),
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
    k = int(math.floor(rank))
    d = rank - k
    return float(sorted_values[k - 1] + d * (sorted_values[min(k, n - 1)] - sorted_values[k - 1]))


def _normalise_heading(value: object) -> str:
    return re.sub(r"[\s_\-]", "", str(value).strip().lower())


def _find_column(columns: Iterable[object], aliases: set[str]) -> Optional[object]:
    normalised_aliases = {_normalise_heading(alias) for alias in aliases}
    return next((column for column in columns if _normalise_heading(column) in normalised_aliases), None)


def _canonicalise_sheet(frame: pd.DataFrame) -> tuple[pd.DataFrame, Optional[str]]:
    """Return a canonical raw-data frame, or an empty frame for non-raw sheets."""

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
        # Compatibility with the supplied legacy workbook: the first seven
        # columns are the raw-data contract, while later sheets are ignored if
        # those columns cannot be converted to a valid year/result pair.
        out = frame.iloc[:, :7].copy()
        out.columns = list(RAW_COLUMNS)
    else:
        return pd.DataFrame(columns=list(RAW_COLUMNS)), None

    period_column = _find_column(frame.columns, PERIOD_COLUMN_ALIASES)
    if period_column is not None:
        out["_semesterSource"] = frame[period_column]
    out["year"] = pd.to_numeric(out["year"], errors="coerce")
    out["result"] = pd.to_numeric(out["result"], errors="coerce")
    for column in ("qcMaterial", "participant", "analyte", "peerGroup", "subPeerGroup"):
        out[column] = out[column].astype("string").fillna("").str.strip()
    out = out.dropna(subset=["year", "result"])
    if out.empty:
        return pd.DataFrame(columns=list(RAW_COLUMNS)), None
    out["year"] = out["year"].astype(int)
    return out, "_semesterSource" if "_semesterSource" in out else None


def _semester_from_value(value: object) -> str:
    text = str(value).strip().lower().replace(" ", "")
    if text in {"h2", "2", "2nd", "second", "하반기", "후반기", "2반기"} or "하반" in text or "2" in text:
        return "H2"
    if text in {"h1", "1", "1st", "first", "상반기", "전반기", "1반기"} or "상반" in text or "1" in text:
        return "H1"
    raise ValueError(f"반기 값을 해석할 수 없습니다: {value!r}. H1/H2 또는 상반기/하반기를 사용하세요.")


def _natural_key(value: object) -> tuple[object, ...]:
    return tuple(int(piece) if piece.isdigit() else piece.lower() for piece in re.split(r"(\d+)", str(value)))


def _attach_evaluation_period(frame: pd.DataFrame, default_semester: str) -> pd.DataFrame:
    """Attach a ``YYYY-H1/H2`` label and validate the 3-material contract."""

    default_semester = _semester_from_value(default_semester)
    out = frame.copy()
    if "_semesterSource" in out:
        out["semester"] = out["_semesterSource"].map(_semester_from_value)
        out = out.drop(columns=["_semesterSource"])
    else:
        pieces: list[pd.DataFrame] = []
        for _, group in out.groupby("year", sort=True):
            materials = sorted(group["qcMaterial"].dropna().unique(), key=_natural_key)
            if len(materials) == 3:
                lookup = {material: default_semester for material in materials}
            elif len(materials) == 6:
                lookup = {material: "H1" if index < 3 else "H2" for index, material in enumerate(materials)}
            else:
                year = int(group["year"].iloc[0])
                raise ValueError(
                    f"{year}년 자료에서 PT 물질 {len(materials)}개가 발견되었습니다. "
                    "반기당 정확히 3개가 필요합니다. 반기 열(H1/H2)을 추가하거나 3개 물질만 포함한 파일을 사용하세요."
                )
            copy = group.copy()
            copy["semester"] = copy["qcMaterial"].map(lookup)
            pieces.append(copy)
        out = pd.concat(pieces, ignore_index=True)

    out["evaluationPeriod"] = out["year"].astype(str) + "-" + out["semester"]
    period_counts = out.groupby("evaluationPeriod")["qcMaterial"].nunique()
    invalid = period_counts[period_counts != 3]
    if not invalid.empty:
        detail = ", ".join(f"{period} ({count}개)" for period, count in invalid.items())
        raise ValueError(f"각 반기 평가에는 PT 물질이 정확히 3개 있어야 합니다: {detail}")
    return out


def load_all_sheets(xlsx_path: str | Path, default_semester: str = "H1") -> pd.DataFrame:
    """Read every compatible raw-data sheet and assign its evaluation semester."""

    try:
        workbook = pd.ExcelFile(xlsx_path)
    except Exception as exc:
        raise RuntimeError(f"Excel 파일을 열 수 없습니다: {exc}") from exc
    frames: list[pd.DataFrame] = []
    try:
        for sheet in workbook.sheet_names:
            frame, _ = _canonicalise_sheet(workbook.parse(sheet_name=sheet, header=0))
            if not frame.empty:
                frames.append(frame)
    finally:
        # Explicitly release the workbook; otherwise Windows keeps the input
        # .xlsx locked after an analysis finishes.
        workbook.close()
    if not frames:
        raise RuntimeError("유효한 raw data를 찾지 못했습니다. Year~Result의 7개 열을 확인하세요.")
    return _attach_evaluation_period(pd.concat(frames, ignore_index=True), default_semester)


def apply_tukey_and_min_participants(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply Tukey outlier exclusion, n>=10, and complete 3-material coverage."""

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

    # A semestral result must reflect all three PT materials for the analyte.
    coverage = out.groupby(["evaluationPeriod", "analyte"])["qcMaterial"].nunique()
    complete = coverage[coverage == 3].index
    return out.set_index(["evaluationPeriod", "analyte"]).loc[
        lambda indexed: indexed.index.isin(complete)
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
        (out["mean"].sub(out["peerMean"]).div(out["peerMean"]).abs() * 100),
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


def _period_key(period: str) -> tuple[int, int, str]:
    match = re.match(r"^(\d{4})-H([12])$", str(period))
    return (int(match.group(1)), int(match.group(2)), str(period)) if match else (9999, 9, str(period))


def generate_trend_charts(subpeer: pd.DataFrame, peer: pd.DataFrame, analyte: pd.DataFrame, output_dir: Path) -> None:
    """Create categorical semestral trends for TAE, bias and CV."""

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)

    def draw(frame: pd.DataFrame, metric: str, title: str, prefix: str, groups: list[str]) -> None:
        groupby = ["analyte", *groups]
        for keys, group in frame.groupby(groupby, sort=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            group = group.sort_values("evaluationPeriod", key=lambda s: s.map(_period_key))
            labels = group["evaluationPeriod"].tolist()
            label = " | ".join(str(item) for item in keys[1:]) or "All groups"
            figure, axis = plt.subplots(figsize=(7.2, 4.2))
            axis.plot(labels, group[metric], marker="o", linewidth=2.2, color="#118a54")
            axis.set_title(f"{title} - {keys[0]}\n{label}", fontweight="bold")
            axis.set_xlabel("Evaluation period (semester)")
            axis.set_ylabel(metric)
            axis.grid(axis="y", alpha=0.25)
            figure.tight_layout()
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", "_".join(map(str, keys)))
            figure.savefig(output_dir / f"{prefix}_{safe}.png", dpi=170)
            plt.close(figure)

    for metric, label in (("tae", "TAE"), ("pooledBias", "Bias"), ("pooledCv", "CV")):
        draw(subpeer, metric, f"{label} trend (sub-peer pooled)", f"{metric}_SubPeer", ["peerGroup", "subPeerGroup"])
        draw(peer, metric, f"{label} trend (peer pooled)", f"{metric}_Peer", ["peerGroup"])
        draw(analyte, metric, f"{label} trend (analyte pooled)", f"{metric}_Analyte", [])


def _draw_summary_table(pdf: canvas.Canvas, frame: pd.DataFrame, title: str, page_height: float, page_width: float) -> None:
    columns = ["evaluationPeriod", "analyte", "peerGroup", "subPeerGroup", "pooledBias", "pooledCv", "tae", "harmonizationLevel"]
    columns = [column for column in columns if column in frame.columns]
    widths = [2.0, 2.2, 2.6, 2.6, 1.45, 1.45, 1.1, 2.0][: len(columns)]
    widths = [width * cm for width in widths]
    x = 1.5 * cm
    y = page_height - 3.2 * cm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.setFillColor(colors.HexColor("#0C5B38"))
    pdf.drawString(x, y, title)
    y -= 0.55 * cm
    pdf.setFillColor(colors.white)
    pdf.setStrokeColor(colors.HexColor("#0C5B38"))
    pdf.setFillColor(colors.HexColor("#0C5B38"))
    for index, column in enumerate(columns):
        pdf.rect(x + sum(widths[:index]), y - 0.38 * cm, widths[index], 0.42 * cm, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 6.6)
        pdf.drawString(x + sum(widths[:index]) + 0.07 * cm, y - 0.22 * cm, column)
    y -= 0.5 * cm
    pdf.setFont("Helvetica", 6.6)
    for row_index, (_, row) in enumerate(frame.sort_values(["evaluationPeriod", "analyte"]).head(42).iterrows()):
        if y < 1.8 * cm:
            pdf.showPage()
            _report_header(pdf, page_width, page_height, "HarmoCheck report (continued)")
            y = page_height - 3.2 * cm
        if row_index % 2 == 0:
            pdf.setFillColor(colors.HexColor("#EEF8F1"))
            pdf.rect(x, y - 0.29 * cm, sum(widths), 0.34 * cm, fill=1, stroke=0)
        pdf.setFillColor(colors.HexColor("#1E2B23"))
        for index, column in enumerate(columns):
            value = row[column]
            text = f"{float(value):.3f}" if column in {"pooledBias", "pooledCv", "tae"} and pd.notna(value) else str(value)
            pdf.drawString(x + sum(widths[:index]) + 0.07 * cm, y - 0.18 * cm, text[:25])
        y -= 0.36 * cm


def _report_header(pdf: canvas.Canvas, page_width: float, page_height: float, title: str) -> None:
    pdf.setFillColor(colors.HexColor("#0C5B38"))
    pdf.rect(0, page_height - 1.45 * cm, page_width, 1.45 * cm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(1.5 * cm, page_height - 0.92 * cm, title)
    pdf.setFont("Helvetica", 8.5)
    pdf.drawRightString(page_width - 1.5 * cm, page_height - 0.92 * cm, "Semestral assessment | 3 PT materials per period")


def generate_pdf_report(subpeer: pd.DataFrame, peer: pd.DataFrame, analyte: pd.DataFrame, tea_map: Mapping[str, TEaThreshold], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "HarmoCheck_Report.pdf"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    _report_header(pdf, width, height, "HarmoCheck")
    pdf.setFillColor(colors.HexColor("#12321F"))
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(1.5 * cm, height - 2.55 * cm, "Harmonization assessment report")
    pdf.setFont("Helvetica", 9.2)
    pdf.drawString(1.5 * cm, height - 3.15 * cm, "Assessment rule: each result pools exactly three PT materials from one EQA semester.")
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(1.5 * cm, height - 4.05 * cm, "TEa thresholds used")
    y = height - 4.6 * cm
    pdf.setFont("Helvetica", 9)
    for analyte_name, threshold in tea_map.items():
        pdf.drawString(1.7 * cm, y, f"{analyte_name}: Optimal {threshold.optimal:.2f}% | Desirable {threshold.desirable:.2f}% | Minimum {threshold.minimum:.2f}%")
        y -= 0.48 * cm
    pdf.setFillColor(colors.HexColor("#5A6B60"))
    pdf.setFont("Helvetica-Oblique", 8)
    pdf.drawString(1.5 * cm, 2.0 * cm, "Unknown means a TEa threshold has not yet been configured for the analyte.")
    for frame, title in ((subpeer, "Sub-peer pooled summary"), (peer, "Peer pooled summary"), (analyte, "Analyte pooled summary")):
        pdf.showPage()
        _report_header(pdf, width, height, "HarmoCheck")
        _draw_summary_table(pdf, frame, title, height, width)
    pdf.save()
    return path


def save_tables_excel(subpeer: pd.DataFrame, peer: pd.DataFrame, analyte: pd.DataFrame, coverage: pd.DataFrame, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "HarmoCheck_Tables.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        coverage.to_excel(writer, sheet_name="Coverage", index=False)
        subpeer.to_excel(writer, sheet_name="SubPeerPooled", index=False)
        peer.to_excel(writer, sheet_name="PeerPooled", index=False)
        analyte.to_excel(writer, sheet_name="AnalytePooled", index=False)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for column in sheet.columns:
                letter = column[0].column_letter
                width = min(40, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
                sheet.column_dimensions[letter].width = width
    return path


def analyze_workbook(
    xlsx_path: str | Path,
    output_dir: str | Path,
    tea_map: Optional[Mapping[str, TEaThreshold]] = None,
    default_semester: str = "H1",
    generate_charts: bool = True,
) -> AnalysisResult:
    """Run the complete semestral assessment and write the standard outputs."""

    raw = load_all_sheets(xlsx_path, default_semester=default_semester)
    filtered = apply_tukey_and_min_participants(raw)
    if filtered.empty:
        raise RuntimeError("Tukey 이상치 제외와 기관 수(n>=10) 조건 후 남은 완전한 3-PT 평가 자료가 없습니다.")
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
    if generate_charts:
        generate_trend_charts(subpeer, peer, analyte, charts_dir)
    else:
        charts_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = generate_pdf_report(subpeer, peer, analyte, thresholds, output)
    tables_path = save_tables_excel(subpeer, peer, analyte, coverage, output)
    periods = tuple(sorted(filtered["evaluationPeriod"].unique(), key=_period_key))
    return AnalysisResult(len(raw), len(filtered), periods, subpeer, peer, analyte, coverage, pdf_path, tables_path, charts_dir)
