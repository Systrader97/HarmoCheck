import tempfile
import unittest
from pathlib import Path

import pandas as pd

from harmocheck.core import (
    TEaThreshold,
    analyze_workbook,
    apply_tukey_and_min_participants,
    classify_tae,
    load_all_sheets,
)


def synthetic_raw(materials, year=2026):
    rows = []
    for material_index, material in enumerate(materials):
        for peer in ("Instrument A", "Instrument B"):
            for subpeer_index, subpeer in enumerate(("Model 1", "Model 2")):
                for participant in range(1, 13):
                    rows.append({
                        "Year": year,
                        "QC material": material,
                        "Participant": f"{participant:04d}",
                        "Analyte": "TSH",
                        "Peer group": peer,
                        "Sub-peer group": subpeer,
                        "Result": 1.0 + material_index * 0.1 + subpeer_index * 0.03 + participant * 0.001,
                    })
    return pd.DataFrame(rows)


def test_three_material_file_uses_selected_semester(tmp_path):
    workbook = tmp_path / "three_pt.xlsx"
    synthetic_raw(["CH5-26-01", "CH5-26-02", "CH5-26-03"]).to_excel(workbook, index=False)
    loaded = load_all_sheets(workbook, default_semester="H2")
    assert set(loaded["evaluationPeriod"]) == {"2026-H2"}
    assert loaded["qcMaterial"].nunique() == 3


def test_six_material_file_is_split_into_two_semesters(tmp_path):
    workbook = tmp_path / "six_pt.xlsx"
    synthetic_raw([f"CH5-26-{number:02d}" for number in range(1, 7)]).to_excel(workbook, index=False)
    loaded = load_all_sheets(workbook)
    assert set(loaded["evaluationPeriod"]) == {"2026-H1", "2026-H2"}
    assert loaded.groupby("evaluationPeriod")["qcMaterial"].nunique().to_dict() == {"2026-H1": 3, "2026-H2": 3}


def test_analysis_requires_complete_three_material_coverage(tmp_path):
    workbook = tmp_path / "missing_pt.xlsx"
    raw = synthetic_raw(["CH5-26-01", "CH5-26-02", "CH5-26-03"])
    raw = raw[raw["QC material"] != "CH5-26-03"]
    raw.to_excel(workbook, index=False)
    with unittest.TestCase().assertRaisesRegex(ValueError, "PT 물질 2개"):
        load_all_sheets(workbook)


def test_end_to_end_creates_semestral_outputs(tmp_path):
    workbook = tmp_path / "raw.xlsx"
    synthetic_raw(["CH5-26-01", "CH5-26-02", "CH5-26-03"]).to_excel(workbook, index=False)
    result = analyze_workbook(workbook, tmp_path / "output", tea_map={"TSH": TEaThreshold(5, 10, 15)}, generate_charts=False)
    assert result.periods == ("2026-H1",)
    assert set(result.analyte["ptMaterialCount"]) == {3}
    assert result.pdf_path.is_file()
    assert result.tables_path.is_file()


def test_harmonization_categories():
    tea = TEaThreshold(5, 10, 15)
    assert [classify_tae(value, tea) for value in (5, 10, 15, 16)] == ["Optimal", "Desirable", "Minimum", "Not acceptable"]


class HarmoCheckCoreTests(unittest.TestCase):
    """Executable regression tests without an additional test-runner dependency."""

    def _tmp_path(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def test_three_material_file_uses_selected_semester(self):
        test_three_material_file_uses_selected_semester(self._tmp_path())

    def test_six_material_file_is_split_into_two_semesters(self):
        test_six_material_file_is_split_into_two_semesters(self._tmp_path())

    def test_analysis_requires_complete_three_material_coverage(self):
        test_analysis_requires_complete_three_material_coverage(self._tmp_path())

    def test_end_to_end_creates_semestral_outputs(self):
        test_end_to_end_creates_semestral_outputs(self._tmp_path())

    def test_harmonization_categories(self):
        test_harmonization_categories()


if __name__ == "__main__":
    unittest.main(verbosity=2)
