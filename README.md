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

Double-peak mode with "Extract local valley / 提取局部谷值" enabled:

```text
Cr, Cs, ks, f_res_1, S11_min_1, f_res_2, S11_min_2, local_valley_freq, 局部谷值
```

"局部谷值" 用于在 Double peak 模式下量化双峰中较浅的那个小谷。它的频率来自 `f_res_1` / `f_res_2` 中局部下凹幅度较小的谷点，`局部谷值` 列保存该谷点相对周围背景曲线的下凹差值，单位 dB。这个值不是谷底的原始 S11，而是周围曲线背景与谷底 S11 之间的差值，适合比较不同参数或不同监测方式下的小谷读出响应。未能计算局部背景时输出 `NaN`。

Double-peak mode with "Symmetric peak / 对称峰" enabled adds:

```text
双峰频率差, 凸起频率, 凸起幅值差
```

"对称峰" 用于双峰中间存在向上凸起的情况。`双峰频率差` 为 `f_res_1` 和 `f_res_2` 的频率间隔；`凸起频率` 为两个谷之间 S11 最大的中间凸起点；`凸起幅值差` 为该凸起 S11 减去双峰谷底中更低的那个 S11，用于量化中间凸起相对深谷的高度差。
