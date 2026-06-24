"""Utilities for extracting resonance features from wide-format S11 data."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:[p.]\d*)?|[p.]\d+)(?:[eE][-+]?\d+)?")


def _parse_number(value: str) -> float:
    """Parse numeric strings that may use 'p' as a decimal point."""
    return float(value.replace("p", "."))


def _parse_parameter(column_name: str, name: str, *, required: bool = True) -> float | str:
    pattern = re.compile(rf"(?:^|_){re.escape(name)}([^_]*)", flags=re.IGNORECASE)
    match = pattern.search(column_name)
    if match is None:
        if not required:
            return ""
        raise ValueError(f"Could not parse parameter '{name}' from column: {column_name!r}")

    number_match = _NUMBER_PATTERN.match(match.group(1))
    if number_match is None:
        if not required:
            return ""
        raise ValueError(f"Could not parse numeric value for '{name}' from column: {column_name!r}")

    return _parse_number(number_match.group(0))


def _parse_parameters(column_name: str) -> dict[str, float | str]:
    return {
        "Cr": _parse_parameter(column_name, "Cr", required=False),
        "Cs": _parse_parameter(column_name, "Cs"),
        "ks": _parse_parameter(column_name, "ks"),
    }


def _extract_curve_minimum(frequency: pd.Series, values: pd.Series) -> tuple[float, float]:
    valid = frequency.notna() & values.notna()
    if not valid.any():
        return np.nan, np.nan

    valid_values = values.loc[valid]
    min_index = valid_values.idxmin()
    return float(frequency.loc[min_index]), float(values.loc[min_index])


def _find_local_minima_indices(values: np.ndarray) -> np.ndarray:
    if len(values) == 0:
        return np.array([], dtype=int)
    if len(values) == 1:
        return np.array([0], dtype=int)

    indices: list[int] = []
    if values[0] < values[1]:
        indices.append(0)

    for index in range(1, len(values) - 1):
        if values[index] <= values[index - 1] and values[index] <= values[index + 1]:
            indices.append(index)

    if values[-1] < values[-2]:
        indices.append(len(values) - 1)

    return np.array(indices, dtype=int)


def _extract_curve_two_minima(frequency: pd.Series, values: pd.Series) -> tuple[float, float, float, float]:
    valid = frequency.notna() & values.notna()
    if not valid.any():
        return np.nan, np.nan, np.nan, np.nan

    valid_frequency = frequency.loc[valid].to_numpy(dtype=float)
    valid_values = values.loc[valid].to_numpy(dtype=float)
    local_indices = _find_local_minima_indices(valid_values)

    if len(local_indices) >= 2:
        candidate_indices = local_indices
    else:
        candidate_indices = np.arange(len(valid_values))

    ranked_indices = candidate_indices[np.argsort(valid_values[candidate_indices])]
    selected_indices = list(ranked_indices[:2])

    if len(selected_indices) < 2:
        selected_indices.extend([-1] * (2 - len(selected_indices)))

    selected_indices = sorted(selected_indices, key=lambda index: valid_frequency[index] if index >= 0 else np.inf)
    first_index, second_index = selected_indices

    first = (
        (float(valid_frequency[first_index]), float(valid_values[first_index]))
        if first_index >= 0
        else (np.nan, np.nan)
    )
    second = (
        (float(valid_frequency[second_index]), float(valid_values[second_index]))
        if second_index >= 0
        else (np.nan, np.nan)
    )

    return first[0], first[1], second[0], second[1]


def extract_resonance_features(csv_path: str | Path) -> pd.DataFrame:
    """Extract resonance frequency and minimum S11 from wide-format S11 CSV data.

    Parameters
    ----------
    csv_path:
        Path to a CSV file. The first column must contain frequency values, and
        every remaining column is treated as one S11 curve. S11 column names must
        include ``Cs`` and ``ks`` tokens, for example ``S11_Cs10_ks0p01``.

    Returns
    -------
    pandas.DataFrame
        A table with columns ``Cs``, ``ks``, ``f_res``, and ``S11_min``.
    """
    data = pd.read_csv(csv_path)
    if data.shape[1] < 2:
        raise ValueError("CSV must contain a frequency column and at least one S11 curve column.")

    frequency = pd.to_numeric(data.iloc[:, 0], errors="coerce")
    records: list[dict[str, Any]] = []

    for column_name in data.columns[1:]:
        parameters = _parse_parameters(str(column_name))
        values = pd.to_numeric(data[column_name], errors="coerce")
        f_res, s11_min = _extract_curve_minimum(frequency, values)

        records.append(
            {
                **parameters,
                "f_res": f_res,
                "S11_min": s11_min,
            }
        )

    return pd.DataFrame.from_records(records, columns=["Cr", "Cs", "ks", "f_res", "S11_min"])


def extract_double_resonance_features(csv_path: str | Path) -> pd.DataFrame:
    """Extract two resonance minima from each wide-format S11 curve.

    For each S11 curve, the function first looks for local minima and picks the
    two deepest minima. If fewer than two local minima are available, it falls
    back to the two lowest valid samples. The two reported resonances are ordered
    by frequency.
    """
    data = pd.read_csv(csv_path)
    if data.shape[1] < 2:
        raise ValueError("CSV must contain a frequency column and at least one S11 curve column.")

    frequency = pd.to_numeric(data.iloc[:, 0], errors="coerce")
    records: list[dict[str, Any]] = []

    for column_name in data.columns[1:]:
        parameters = _parse_parameters(str(column_name))
        values = pd.to_numeric(data[column_name], errors="coerce")
        f_res_1, s11_min_1, f_res_2, s11_min_2 = _extract_curve_two_minima(frequency, values)

        records.append(
            {
                **parameters,
                "f_res_1": f_res_1,
                "S11_min_1": s11_min_1,
                "f_res_2": f_res_2,
                "S11_min_2": s11_min_2,
            }
        )

    return pd.DataFrame.from_records(
        records,
        columns=["Cr", "Cs", "ks", "f_res_1", "S11_min_1", "f_res_2", "S11_min_2"],
    )
