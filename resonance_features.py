"""Utilities for extracting resonance features from wide-format S11 data."""

from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


_NUMBER_PATTERN = re.compile(r"[-+]?(?:\d+(?:[p.]\d*)?|[p.]\d+)(?:[eE][-+]?\d+)?")
LOCAL_VALLEY_COLUMN = "局部谷值"
SYMMETRIC_FREQ_DIFF_COLUMN = "双峰频率差"
SYMMETRIC_MIDDLE_PEAK_FREQ_COLUMN = "凸起频率"
SYMMETRIC_MIDDLE_PEAK_DELTA_COLUMN = "凸起幅值差"
MIN_DOUBLE_PEAK_SAMPLE_GAP = 2
MIN_DOUBLE_PEAK_LOCAL_VALLEY_PROMINENCE = 0.05
LOGGER = logging.getLogger(__name__)


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
    global_min_index = int(np.argmin(valid_values))

    selected_pair = _select_main_and_local_valley_pair(valid_values, global_min_index)
    if selected_pair is None:
        return (
            float(valid_frequency[global_min_index]),
            float(valid_values[global_min_index]),
            np.nan,
            np.nan,
        )

    selected_indices = sorted(selected_pair, key=lambda index: valid_frequency[index])
    first_index, second_index = selected_indices

    first = (float(valid_frequency[first_index]), float(valid_values[first_index]))
    second = (float(valid_frequency[second_index]), float(valid_values[second_index]))

    return first[0], first[1], second[0], second[1]


def _select_main_and_local_valley_pair(values: np.ndarray, main_index: int) -> tuple[int, int] | None:
    local_indices = [int(index) for index in _find_local_minima_indices(values) if int(index) != main_index]
    candidates: list[dict[str, float | int]] = []
    for valley_index in local_indices:
        if abs(valley_index - main_index) < MIN_DOUBLE_PEAK_SAMPLE_GAP:
            continue
        candidate = _measure_local_valley_by_shape(values, valley_index, main_index)
        if candidate is not None:
            candidates.append(candidate)

    if not candidates:
        return None

    best_candidate = max(candidates, key=lambda candidate: float(candidate["local_valley_s11"]))
    return int(best_candidate["valley_index"]), int(main_index)


def _measure_local_valley_by_shape(values: np.ndarray, valley_index: int, main_index: int) -> dict[str, float | int] | None:
    if valley_index < main_index:
        peak_candidates = np.flatnonzero((np.arange(len(values)) > valley_index) & (np.arange(len(values)) < main_index))
        peak_index = _highest_local_peak_index(values, peak_candidates)
    else:
        peak_candidates = np.flatnonzero((np.arange(len(values)) > main_index) & (np.arange(len(values)) < valley_index))
        peak_index = _highest_local_peak_index(values, peak_candidates)

    if peak_index is None:
        return None

    prominence = float(values[peak_index]) - float(values[valley_index])
    if prominence < MIN_DOUBLE_PEAK_LOCAL_VALLEY_PROMINENCE:
        return None

    return {
        "valley_index": int(valley_index),
        "peak_index": int(peak_index),
        "local_valley_s11": prominence,
    }


def _highest_local_peak_index(values: np.ndarray, candidates: np.ndarray) -> int | None:
    local_peaks: list[int] = []
    for index in candidates:
        index = int(index)
        left_ok = index == 0 or values[index] >= values[index - 1]
        right_ok = index + 1 == len(values) or values[index] >= values[index + 1]
        if left_ok and right_ok:
            local_peaks.append(index)

    if not local_peaks:
        return None

    return max(local_peaks, key=lambda index: float(values[index]))


def extract_local_valley(
    freq: pd.Series | np.ndarray,
    s11_db: pd.Series | np.ndarray,
    f_res_1: float | None = None,
    f_res_2: float | None = None,
    search_start: float | None = None,
    search_stop: float | None = None,
    main_resonance_freq: float | None = None,
    local_valley_min_prominence: float | None = None,
) -> dict[str, float | bool | str]:
    """Measure the shallower double-peak valley depth against its local background."""
    frequency = pd.to_numeric(pd.Series(freq), errors="coerce")
    values = pd.to_numeric(pd.Series(s11_db), errors="coerce")
    valid = frequency.notna() & values.notna()
    if not valid.any():
        return {
            "local_valley_freq": np.nan,
            "local_valley_s11": np.nan,
            "success": False,
            "message": "No valid data for local valley detection.",
        }

    order = np.argsort(frequency.loc[valid].to_numpy(dtype=float))
    valid_frequency = frequency.loc[valid].to_numpy(dtype=float)[order]
    valid_values = values.loc[valid].to_numpy(dtype=float)[order]

    if f_res_2 is None or pd.isna(f_res_2):
        return {
            "local_valley_freq": np.nan,
            "local_valley_s11": np.nan,
            "success": False,
            "message": "Only one resonance peak detected.",
        }

    reference_frequencies = [
        value
        for value in (f_res_1, main_resonance_freq, f_res_2)
        if value is not None and not pd.isna(value)
    ]
    candidates: list[dict[str, float]] = []
    for valley_frequency in dict.fromkeys(reference_frequencies):
        candidate = _measure_local_valley_depth(
            valid_frequency,
            valid_values,
            float(valley_frequency),
            other_valley_frequencies=[
                float(other)
                for other in reference_frequencies
                if not np.isclose(float(other), float(valley_frequency))
            ],
            search_start=search_start,
            search_stop=search_stop,
        )
        if candidate is None:
            continue
        if local_valley_min_prominence is not None and candidate["local_valley_s11"] < local_valley_min_prominence:
            continue
        candidates.append(candidate)

    if not candidates:
        return {
            "local_valley_freq": np.nan,
            "local_valley_s11": np.nan,
            "success": False,
            "message": "No local valley detected.",
        }

    best_candidate = min(candidates, key=lambda candidate: candidate["local_valley_s11"])
    return {
        "local_valley_freq": best_candidate["local_valley_freq"],
        "local_valley_s11": best_candidate["local_valley_s11"],
        "success": True,
        "message": "Local valley detected.",
    }


def _measure_local_valley_depth(
    frequency: np.ndarray,
    values: np.ndarray,
    valley_frequency: float,
    *,
    other_valley_frequencies: list[float],
    search_start: float | None,
    search_stop: float | None,
) -> dict[str, float] | None:
    valley_index = int(np.argmin(np.abs(frequency - valley_frequency)))
    if valley_index == 0 or valley_index == len(values) - 1:
        return None
    other_valley_indices = [
        int(np.argmin(np.abs(frequency - other_frequency)))
        for other_frequency in other_valley_frequencies
        if not pd.isna(other_frequency)
    ]
    if not other_valley_indices:
        return None

    main_index = min(other_valley_indices, key=lambda index: float(values[index]))
    shape_candidate = _measure_local_valley_by_shape(values, valley_index, main_index)
    if shape_candidate is None:
        return None

    depth = float(shape_candidate["local_valley_s11"])
    if depth <= 0:
        return None

    return {
        "local_valley_freq": float(frequency[valley_index]),
        "local_valley_s11": float(depth),
    }


def _nearest_left_peak_top(values: np.ndarray, valley_index: int, candidates: np.ndarray) -> int:
    """Return the nearest local maximum immediately left of a valley."""
    candidate_set = set(int(index) for index in candidates)
    local_maxima: list[int] = []

    for index in candidates:
        index = int(index)
        left_ok = index == 0 or values[index] >= values[index - 1]
        right_ok = index + 1 == len(values) or values[index] >= values[index + 1]
        if left_ok and right_ok:
            local_maxima.append(index)

    if local_maxima:
        return max(local_maxima)

    previous_value = values[valley_index]
    best_index = int(candidates[-1])
    for index in range(valley_index - 1, int(candidates[0]) - 1, -1):
        if index not in candidate_set:
            continue
        if values[index] < previous_value:
            break
        best_index = index
        previous_value = values[index]

    return best_index


def extract_symmetric_peak_features(
    freq: pd.Series | np.ndarray,
    s11_db: pd.Series | np.ndarray,
    f_res_1: float | None,
    s11_min_1: float | None,
    f_res_2: float | None,
    s11_min_2: float | None,
) -> dict[str, float | bool | str]:
    """Measure symmetric double-peak spacing and the upward bump between the two valleys."""
    if f_res_1 is None or f_res_2 is None or pd.isna(f_res_1) or pd.isna(f_res_2):
        return {
            "frequency_diff": np.nan,
            "middle_peak_freq": np.nan,
            "middle_peak_delta": np.nan,
            "success": False,
            "message": "Missing double-peak frequencies.",
        }

    frequency = pd.to_numeric(pd.Series(freq), errors="coerce")
    values = pd.to_numeric(pd.Series(s11_db), errors="coerce")
    valid = frequency.notna() & values.notna()
    if not valid.any():
        return {
            "frequency_diff": np.nan,
            "middle_peak_freq": np.nan,
            "middle_peak_delta": np.nan,
            "success": False,
            "message": "No valid data for symmetric peak detection.",
        }

    order = np.argsort(frequency.loc[valid].to_numpy(dtype=float))
    valid_frequency = frequency.loc[valid].to_numpy(dtype=float)[order]
    valid_values = values.loc[valid].to_numpy(dtype=float)[order]

    left_frequency = min(float(f_res_1), float(f_res_2))
    right_frequency = max(float(f_res_1), float(f_res_2))
    frequency_diff = right_frequency - left_frequency
    between = (valid_frequency > left_frequency) & (valid_frequency < right_frequency)
    between_indices = np.flatnonzero(between)
    if len(between_indices) == 0:
        return {
            "frequency_diff": frequency_diff,
            "middle_peak_freq": np.nan,
            "middle_peak_delta": np.nan,
            "success": False,
            "message": "No samples between double peaks.",
        }

    peak_index = int(between_indices[np.argmax(valid_values[between_indices])])
    lower_valley = min(
        value
        for value in (s11_min_1, s11_min_2)
        if value is not None and not pd.isna(value)
    )
    peak_delta = float(valid_values[peak_index]) - float(lower_valley)
    return {
        "frequency_diff": float(frequency_diff),
        "middle_peak_freq": float(valid_frequency[peak_index]),
        "middle_peak_delta": float(peak_delta),
        "success": True,
        "message": "Symmetric peak detected.",
    }


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


def extract_double_resonance_features(
    csv_path: str | Path,
    *,
    include_local_valley: bool = False,
    include_symmetric_peak: bool = False,
) -> pd.DataFrame:
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

        record = {
            **parameters,
            "f_res_1": f_res_1,
            "S11_min_1": s11_min_1,
            "f_res_2": f_res_2,
            "S11_min_2": s11_min_2,
        }

        if include_local_valley:
            local_valley = extract_local_valley(
                frequency,
                values,
                f_res_1=f_res_1,
                f_res_2=f_res_2,
                main_resonance_freq=f_res_1,
            )
            if not local_valley["success"]:
                LOGGER.warning("%s %s", column_name, local_valley["message"])
            record["local_valley_freq"] = local_valley["local_valley_freq"]
            record[LOCAL_VALLEY_COLUMN] = local_valley["local_valley_s11"]

        if include_symmetric_peak:
            symmetric_peak = extract_symmetric_peak_features(
                frequency,
                values,
                f_res_1,
                s11_min_1,
                f_res_2,
                s11_min_2,
            )
            if not symmetric_peak["success"]:
                LOGGER.warning("%s %s", column_name, symmetric_peak["message"])
            record[SYMMETRIC_FREQ_DIFF_COLUMN] = symmetric_peak["frequency_diff"]
            record[SYMMETRIC_MIDDLE_PEAK_FREQ_COLUMN] = symmetric_peak["middle_peak_freq"]
            record[SYMMETRIC_MIDDLE_PEAK_DELTA_COLUMN] = symmetric_peak["middle_peak_delta"]

        records.append(record)

    columns = ["Cr", "Cs", "ks", "f_res_1", "S11_min_1", "f_res_2", "S11_min_2"]
    if include_local_valley:
        columns.extend(["local_valley_freq", LOCAL_VALLEY_COLUMN])
    if include_symmetric_peak:
        columns.extend(
            [
                SYMMETRIC_FREQ_DIFF_COLUMN,
                SYMMETRIC_MIDDLE_PEAK_FREQ_COLUMN,
                SYMMETRIC_MIDDLE_PEAK_DELTA_COLUMN,
            ]
        )

    return pd.DataFrame.from_records(records, columns=columns)
