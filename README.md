# HarmoCheck

Harmonization evaluation tool based on KEQAS EQA.

**HarmoCheck** is a Windows desktop application for semestral harmonization assessment using Korean External Quality Assessment Scheme (KEQAS EQA) raw data. It assesses each `Year-Survey` period with the **three PT materials distributed for that survey**.

## What it does

- Reads compatible raw-data sheets from an `.xlsx` workbook.
- Validates the 3-PT-material-per-semester rule before calculation.
- Applies Tukey outlier exclusion and requires at least 10 participating institutions per sub-peer group.
- Calculates pooled bias, CV, TAE and the configured TEa-based harmonization level at sub-peer, peer and analyte levels.
- Exports an Excel table workbook, PDF report and semestral trend charts.
- Provides a green local Windows UI. Selected data are processed only on the local computer.

## Survey data handling

HarmoCheck derives the survey directly from the trailing material number in the QC material column: `01` to `03` are survey `A`, and `04` to `06` are survey `B`. A valid Year-Survey period must contain exactly three PT materials.

The program will not publish a harmonization result for an incomplete period; every eligible analyte must have all three PT materials after filtering.

### Harmonization classification

At each level, the calculated TAE is compared with the analyte-specific total allowable error (TEa). The TFT study applied TEa criteria derived from the EFLM biological-variation database; HarmoCheck exposes the TEa thresholds in the application settings so that they can be reviewed or updated before analysis.

| Harmonization level | Criterion |
| --- | --- |
| Optimal | $\mathrm{TAE} \leq \mathrm{Optimal\ TEa}$ |
| Desirable | $\mathrm{Optimal\ TEa} < \mathrm{TAE} \leq \mathrm{Desirable\ TEa}$ |
| Minimum | $\mathrm{Desirable\ TEa} < \mathrm{TAE} \leq \mathrm{Minimum\ TEa}$ |
| Unacceptable | $\mathrm{TAE} > \mathrm{Minimum\ TEa}$ |

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
