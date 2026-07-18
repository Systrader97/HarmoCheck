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

Optionally include `Semester`/`반기` with H1/H2 (or 상반기/하반기). Each evaluation period must include exactly three PT materials. If a semester column is absent, the UI selection is applied to a 3-material file. A 6-material year is split into the first and second three material codes automatically.
