# HarmoCheck Windows build

## Prerequisites

Install Python 3.11 or later, then run from the project folder:

```bat
python -m pip install -r requirements.txt
build_exe.bat
```

The distributable is written to `dist\HarmoCheck.exe`. The program is a local desktop application and does not send the selected EQA data to a network service.

## Input contract

The raw-data worksheet must contain these seven fields (the supplied English headers and their Korean equivalents are supported):

`Year`, `QC material`, `Participant`, `Analyte`, `Peer group`, `Sub-peer group`, `Result`

HarmoCheck derives the survey from the trailing number in `QC material`: codes ending in `01` to `03` become survey `A`, and those ending in `04` to `06` become survey `B`. Each Year-Survey assessment must include exactly three PT materials.
