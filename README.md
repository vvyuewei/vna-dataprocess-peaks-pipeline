# VNA Data Process Peaks Pipeline

Tools for extracting single-peak and double-peak resonance features from wide-format S11 CSV data.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run the GUI

```powershell
python resonance_feature_gui.py
```

On Windows, you can also double-click:

```text
run_resonance_feature_gui.bat
```

## Input Format

- CSV wide format
- First column: frequency
- Other columns: S11 curves
- S11 column names should include `Cs` and `ks`, for example `S11_Cs10_ks0p01`
- Optional `Cr` is supported; if missing, the output `Cr` column is left blank

## Output

Single-peak mode:

```text
Cr, Cs, ks, f_res, S11_min
```

Double-peak mode:

```text
Cr, Cs, ks, f_res_1, S11_min_1, f_res_2, S11_min_2
```
