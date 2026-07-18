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

## Methodology

### Study basis and analytical unit

The harmonization framework was developed from the 2024–2025 KEQAS EQA thyroid-hormone analysis. In this thyroid function test (TFT) application, all 12 surveys used serum-based, intended-to-be commutable quality-control materials (SIQCs), reducing the potential for matrix-related effects. HarmoCheck evaluates one `Year-Survey` period at a time: survey `A` contains QC materials ending in `01`–`03`, and survey `B` contains those ending in `04`–`06`.

For an analyte, the calculation is performed at three levels:

- **Sub-peer group level:** laboratories using the same analyser model and its dedicated reagent system.
- **Peer group level:** analyser groups from the same manufacturer. The peer-group mean is used as the assigned (true) value because laboratories in a peer group are expected to share similar matrix-related bias.
- **Analyte level:** all eligible sub-peer groups across peer groups.

Each period must contain exactly three PT materials. Results are first assessed within each `Year-Survey × QC material × analyte × peer group × sub-peer group` stratum using Tukey's 1.5-IQR rule:

$$
Q_1 - 1.5\,IQR \leq x \leq Q_3 + 1.5\,IQR
$$

where $IQR = Q_3 - Q_1$. The current HarmoCheck implementation retains a stratum only when at least 10 distinct laboratories remain after outlier exclusion. A peer group must retain all three PT materials, and an analyte is reported only when at least two complete peer groups remain. This excludes analytes such as Total T4 when only one eligible peer group survives the participation criteria.

### Notation

For PT material *j* (*j* = 1, 2, 3) in a `Year-Survey` period and sub-peer group *i*:

- **Mean<sub>S,i,j</sub>** and **SD<sub>S,i,j</sub>** are the sub-peer group mean and standard deviation.
- **n<sub>j</sub>** is the number of sub-peer groups within a peer group for PT material *j*.
- **N<sub>j</sub>** is the total number of eligible sub-peer groups across all peer groups for PT material *j*.

### Assigned value at the peer-group level

The assigned (true) value for a peer group is the unweighted mean of its sub-peer group means. Equal weighting prevents a dominant sub-peer group from being overrepresented:

$$
\mathrm{Mean}_{P,j} = \frac{1}{n_j}\sum_{i=1}^{n_j}\mathrm{Mean}_{S,i,j}
$$

### Sub-peer group level

For each PT material:

$$
\mathrm{Bias}_{S,i,j} = \left|\frac{\mathrm{Mean}_{S,i,j} - \mathrm{Mean}_{P,j}}{\mathrm{Mean}_{P,j}}\right| \times 100
$$

$$
\mathrm{CV}_{S,i,j} = \frac{\mathrm{SD}_{S,i,j}}{\mathrm{Mean}_{S,i,j}} \times 100
$$

The three PT-material results are pooled as the arithmetic mean of bias and the root-mean-square (RMS) of CV:

$$
\mathrm{Pooled\ Bias}_{S,i} = \frac{1}{3}\sum_{j=1}^{3}\mathrm{Bias}_{S,i,j}
$$

$$
\mathrm{Pooled\ CV}_{S,i} = \sqrt{\frac{1}{3}\sum_{j=1}^{3}\left(\mathrm{CV}_{S,i,j}\right)^2}
$$

$$
\mathrm{TAE}_{S,i} = \mathrm{Pooled\ Bias}_{S,i} + 1.65 \times \mathrm{Pooled\ CV}_{S,i}
$$

### Peer group level

For each PT material, HarmoCheck pools the eligible sub-peer group results within a peer group:

$$
\mathrm{Bias}_{P,j} = \frac{1}{n_j}\sum_{i=1}^{n_j}\mathrm{Bias}_{S,i,j}
$$

$$
\mathrm{CV}_{P,j} = \sqrt{\frac{1}{n_j}\sum_{i=1}^{n_j}\left(\mathrm{CV}_{S,i,j}\right)^2}
$$

The peer-group values for the period are then pooled across the three PT materials:

$$
\mathrm{Pooled\ Bias}_{P} = \frac{1}{3}\sum_{j=1}^{3}\mathrm{Bias}_{P,j}
$$

$$
\mathrm{Pooled\ CV}_{P} = \sqrt{\frac{1}{3}\sum_{j=1}^{3}\left(\mathrm{CV}_{P,j}\right)^2}
$$

$$
\mathrm{TAE}_{P} = \mathrm{Pooled\ Bias}_{P} + 1.65 \times \mathrm{Pooled\ CV}_{P}
$$

### Analyte level

For each PT material, the analyte-level metrics are calculated across all eligible sub-peer groups:

$$
\mathrm{Bias}_{A,j} = \frac{1}{N_j}\sum_{i=1}^{N_j}\mathrm{Bias}_{S,i,j}
$$

$$
\mathrm{CV}_{A,j} = \sqrt{\frac{1}{N_j}\sum_{i=1}^{N_j}\left(\mathrm{CV}_{S,i,j}\right)^2}
$$

They are then pooled across the three PT materials:

$$
\mathrm{Pooled\ Bias}_{A} = \frac{1}{3}\sum_{j=1}^{3}\mathrm{Bias}_{A,j}
$$

$$
\mathrm{Pooled\ CV}_{A} = \sqrt{\frac{1}{3}\sum_{j=1}^{3}\left(\mathrm{CV}_{A,j}\right)^2}
$$

$$
\mathrm{TAE}_{A} = \mathrm{Pooled\ Bias}_{A} + 1.65 \times \mathrm{Pooled\ CV}_{A}
$$

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
