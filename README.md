# HarmoCheck

Harmonization evaluation tool based on KEQAS EQA.

**HarmoCheck** is a Windows desktop application for semestral harmonization assessment using Korean External Quality Assessment Scheme (KEQAS EQA) raw data. It assesses each `year-semester` period with the **three PT materials distributed for that semester**.

## What it does

- Reads compatible raw-data sheets from an `.xlsx` workbook.
- Validates the 3-PT-material-per-semester rule before calculation.
- Applies Tukey outlier exclusion and requires at least 10 participating institutions per sub-peer group.
- Calculates pooled bias, CV, TAE and the configured TEa-based harmonization level at sub-peer, peer and analyte levels.
- Exports an Excel table workbook, PDF report and semestral trend charts.
- Provides a green local Windows UI. Selected data are processed only on the local computer.

## Semestral data handling

Use an explicit `Semester` column whenever a workbook contains more than one period. Values such as `H1`, `H2`, first semester, and second semester are supported. For a workbook containing one three-material semester, select its semester in the UI. If a single year has six materials and no semester column, HarmoCheck assigns the first three material codes to H1 and the next three to H2.

The program will not publish a harmonization result for an incomplete period; every eligible analyte must have all three PT materials after filtering.

## Run from source

```bat
python -m pip install -r requirements.txt
python main.py
```

See [BUILD_EXE_WINDOWS.md](BUILD_EXE_WINDOWS.md) to create `HarmoCheck.exe`.

## Data safety

The repository intentionally contains no KEQAS raw data or institutional results. Use only de-identified or authorized data when sharing derived files.

## Disclaimer

HarmoCheck is an analytical support tool. Laboratory specialists remain responsible for verifying input data, TEa criteria and final interpretations before operational use.
