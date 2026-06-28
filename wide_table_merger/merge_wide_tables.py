import argparse
import csv
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd


SUPPORTED_EXTS = {".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls"}
OUTPUT_DIR_NAME = "merged_output"
DIFF_OUTPUT_DIR_NAME = "diff_output"
MERGE_RULE_KEEP_FIRST_X = "keep_first_x_append_columns"
MERGE_RULES = {
    MERGE_RULE_KEEP_FIRST_X: "保留第一张X轴，后续表去掉X轴并横向追加",
}
FREQUENCY_COLUMN_NAMES = ["Frequency_MHz", "freq_MHz", "Frequency", "freq", "freq_Hz"]


def natural_key(text):
    parts = re.split(r"(\d+)", str(text).lower())
    return [int(part) if part.isdigit() else part for part in parts]


def sniff_delimiter(path):
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
        sample = f.read(8192)
    if not sample.strip():
        return ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        return dialect.delimiter
    except csv.Error:
        counts = {",": sample.count(","), "\t": sample.count("\t"), ";": sample.count(";")}
        return max(counts, key=counts.get)


def read_table(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path, sheet_name=0)

    delimiter = sniff_delimiter(path)
    return pd.read_csv(path, sep=delimiter, engine="python")


def discover_input_files(base_dir):
    input_dir = Path(base_dir) / "tables_to_merge"
    search_dir = input_dir if input_dir.exists() else Path(base_dir)

    files = []
    for path in search_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTS:
            continue
        if path.name.startswith("~$"):
            continue
        if path.name.startswith("merged_wide_"):
            continue
        if OUTPUT_DIR_NAME in path.parts or DIFF_OUTPUT_DIR_NAME in path.parts:
            continue
        files.append(path)

    return sorted(files, key=lambda p: natural_key(p.name))


def discover_table_files(folder):
    files = []
    for path in Path(folder).iterdir():
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS and not path.name.startswith("~$"):
            files.append(path)
    return sorted(files, key=lambda p: natural_key(p.name))


def normalize_columns(columns):
    normalized = []
    seen = {}
    for column in columns:
        name = str(column).strip()
        if not name:
            name = "Unnamed"
        count = seen.get(name, 0)
        seen[name] = count + 1
        normalized.append(name if count == 0 else f"{name}.{count + 1}")
    return normalized


def dedupe_against_existing(columns, existing, file_stem):
    result = []
    for column in columns:
        candidate = str(column).strip() or "Unnamed"
        if candidate in existing:
            candidate = f"{file_stem}_{candidate}"
        base = candidate
        i = 2
        while candidate in existing:
            candidate = f"{base}.{i}"
            i += 1
        existing.add(candidate)
        result.append(candidate)
    return result


def parse_number(value):
    text = str(value).replace("p", ".").replace("P", ".")
    try:
        return float(text)
    except ValueError:
        return text.lower()


PARAM_TOKEN_RE = re.compile(r"(?i)(?<![A-Za-z])(ks|cr|cs|k)\s*=?\s*(-?\d+(?:p\d+|\.\d+)?(?:e[-+]?\d+)?)")


def extract_sort_params(column):
    text = str(column)
    tokens = []
    for name, value in PARAM_TOKEN_RE.findall(text):
        tokens.append((name.lower(), parse_number(value)))
    return tokens


def infer_sort_param_order(columns):
    order = []
    seen = set()

    for column in columns:
        params = extract_sort_params(column)
        if params:
            for name, _value in params:
                if name not in seen:
                    seen.add(name)
                    order.append(name)
            break

    for column in columns:
        for name, _value in extract_sort_params(column):
            if name not in seen:
                seen.add(name)
                order.append(name)

    return order


def header_sort_key(column, param_order):
    params = {}
    for name, value in extract_sort_params(column):
        params.setdefault(name, value)

    if not params:
        return (1, natural_key(column))

    ordered_values = []
    for name in param_order:
        if name in params:
            ordered_values.append((0, params[name]))
        else:
            ordered_values.append((1, ""))
    return (0, ordered_values, natural_key(column))


def smart_sort_columns(df):
    if df.shape[1] <= 2:
        return df
    x_column = df.columns[0]
    data_columns = list(df.columns[1:])
    param_order = infer_sort_param_order(data_columns)
    if param_order:
        data_columns.sort(key=lambda column: header_sort_key(column, param_order))
    else:
        data_columns.sort(key=natural_key)
    return df[[x_column] + data_columns]


def compare_x_axis(first, current, file_name):
    if len(first) != len(current):
        return f"{file_name}: X轴行数不同（第一张 {len(first)} 行，这张 {len(current)} 行）"

    first_values = first.reset_index(drop=True)
    current_values = current.reset_index(drop=True)
    both_numeric = pd.to_numeric(first_values, errors="coerce").notna().all() and pd.to_numeric(
        current_values, errors="coerce"
    ).notna().all()

    if both_numeric:
        a = pd.to_numeric(first_values, errors="coerce")
        b = pd.to_numeric(current_values, errors="coerce")
        if not a.equals(b):
            max_diff = (a - b).abs().max()
            return f"{file_name}: X轴数值和第一张不完全一致，最大差异 {max_diff}"
    elif not first_values.astype(str).equals(current_values.astype(str)):
        return f"{file_name}: X轴内容和第一张不完全一致"

    return None


def merge_tables(files, smart_sort=True):
    if len(files) < 2:
        raise ValueError("至少需要 2 个表格文件。")

    warnings = []
    frames = []
    existing_columns = set()
    first_x = None

    for index, path in enumerate(files):
        df = read_table(path)
        df = df.dropna(how="all").reset_index(drop=True)
        if df.shape[1] < 2:
            raise ValueError(f"{Path(path).name} 至少需要 2 列（X轴 + 数据列）。")

        df.columns = normalize_columns(df.columns)

        if index == 0:
            first_x = df.iloc[:, 0].copy()
            df.columns = dedupe_against_existing(df.columns, existing_columns, Path(path).stem)
            frames.append(df)
            continue

        warning = compare_x_axis(first_x, df.iloc[:, 0], Path(path).name)
        if warning:
            warnings.append(warning)

        data = df.iloc[:, 1:].copy()
        data.columns = dedupe_against_existing(data.columns, existing_columns, Path(path).stem)
        frames.append(data)

    merged = pd.concat(frames, axis=1)
    if smart_sort:
        merged = smart_sort_columns(merged)

    return merged, warnings


def write_outputs(merged, output_dir, prefix="merged_wide"):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"{prefix}_{stamp}.csv"
    xlsx_path = output_dir / f"{prefix}_{stamp}.xlsx"

    merged.to_csv(csv_path, index=False, encoding="utf-8-sig")
    xlsx_error = None
    try:
        merged.to_excel(xlsx_path, index=False)
    except Exception as exc:
        xlsx_error = exc
        xlsx_path = None

    return csv_path, xlsx_path, xlsx_error


def parse_cr_from_column(col_name):
    text = str(col_name)
    match = re.search(r"(?i)(?<![A-Za-z])Cr\s*=?\s*(-?\d+(?:[pP]\d+|\.\d+)?)", text)
    if not match:
        return None
    value = match.group(1).replace("p", ".").replace("P", ".")
    try:
        return float(value)
    except ValueError:
        return None


def canonical_cr_key(cr_value):
    try:
        decimal_value = Decimal(str(cr_value))
    except (InvalidOperation, ValueError):
        return str(cr_value)
    return format(decimal_value.normalize(), "f")


def find_frequency_column(df):
    exact = {str(col): col for col in df.columns}
    for name in FREQUENCY_COLUMN_NAMES:
        if name in exact:
            return exact[name]

    lowered = {str(col).strip().lower(): col for col in df.columns}
    for name in FREQUENCY_COLUMN_NAMES:
        key = name.lower()
        if key in lowered:
            return lowered[key]

    raise ValueError(f"未找到频率列。支持的列名：{', '.join(FREQUENCY_COLUMN_NAMES)}")


def normalize_frequency_to_mhz(df):
    result = df.copy()
    freq_col = find_frequency_column(result)
    freq = pd.to_numeric(result[freq_col], errors="raise")

    if str(freq_col).strip().lower() == "freq_hz":
        freq = freq / 1_000_000.0

    if freq_col != "Frequency_MHz":
        result = result.rename(columns={freq_col: "Frequency_MHz"})
    result["Frequency_MHz"] = freq
    return result, "Frequency_MHz"


def frequency_matches(reader_freq, sensor_freq):
    if len(reader_freq) != len(sensor_freq):
        return False, f"频率点数不同：Reader {len(reader_freq)} 点，Reader+Sensor {len(sensor_freq)} 点"

    reader_values = pd.to_numeric(reader_freq.reset_index(drop=True), errors="raise").astype(float)
    sensor_values = pd.to_numeric(sensor_freq.reset_index(drop=True), errors="raise").astype(float)
    if (reader_values == sensor_values).all():
        return True, ""

    max_diff = (reader_values - sensor_values).abs().max()
    return False, f"频率点不一致，最大差异 {max_diff} MHz。默认不插值，请检查输入文件。"


def build_reader_cr_map(reader_df):
    reader_df, freq_col = normalize_frequency_to_mhz(reader_df)
    cr_map = {}
    duplicate_cr = []

    for col in reader_df.columns:
        if col == freq_col:
            continue
        cr = parse_cr_from_column(col)
        if cr is None:
            continue
        key = canonical_cr_key(cr)
        if key in cr_map:
            duplicate_cr.append(str(col))
            continue
        cr_map[key] = {"column": col, "cr": cr}

    if not cr_map:
        raise ValueError("Reader 背景表中没有识别到 Cr 列。")

    return reader_df, freq_col, cr_map, duplicate_cr


def make_diff_column_name(column):
    text = str(column)
    if re.search(r"(?i)S11dB", text):
        return re.sub(r"(?i)S11dB", "DiffS11dB", text, count=1)
    if re.search(r"(?i)S11", text):
        return re.sub(r"(?i)S11", "DiffS11", text, count=1)
    return f"{text}_DiffS11dB"


def diff_single_reader_sensor_by_cr(reader_df, reader_sensor_df, interpolate=False):
    if interpolate:
        raise NotImplementedError("interpolate=True 已预留，但当前版本默认不插值。")

    reader_df, reader_freq_col, reader_cr_map, duplicate_reader_cr = build_reader_cr_map(reader_df)
    sensor_df, sensor_freq_col = normalize_frequency_to_mhz(reader_sensor_df)

    ok, message = frequency_matches(reader_df[reader_freq_col], sensor_df[sensor_freq_col])
    if not ok:
        raise ValueError(message)

    output = pd.DataFrame({"Frequency_MHz": sensor_df[sensor_freq_col]})
    matched_cr = []
    unmatched_columns = []

    for col in sensor_df.columns:
        if col == sensor_freq_col:
            continue
        cr = parse_cr_from_column(col)
        if cr is None:
            unmatched_columns.append(str(col))
            continue
        key = canonical_cr_key(cr)
        reader_info = reader_cr_map.get(key)
        if reader_info is None:
            unmatched_columns.append(str(col))
            continue

        out_col = make_diff_column_name(col)
        output[out_col] = pd.to_numeric(sensor_df[col], errors="coerce") - pd.to_numeric(
            reader_df[reader_info["column"]], errors="coerce"
        )
        matched_cr.append(cr)

    if not matched_cr:
        raise ValueError("没有任何 Reader+Sensor 列按 Cr 匹配到 Reader 背景列。")

    report_info = {
        "frequency_points": len(output),
        "matched_cr_values": matched_cr,
        "matched_cr_min": min(matched_cr),
        "matched_cr_max": max(matched_cr),
        "output_diff_columns": output.shape[1] - 1,
        "unmatched_count": len(unmatched_columns),
        "unmatched_examples": unmatched_columns[:20],
        "duplicate_reader_cr_columns": duplicate_reader_cr,
        "reader_cr_count": len(reader_cr_map),
    }
    return output, report_info


def write_origin_txt(df, path):
    df.to_csv(path, sep="\t", index=False, encoding="utf-8-sig")


def write_diff_report(report_info, path):
    lines = [
        "S11dB Reader 背景差分处理说明",
        "",
        f"Reader 背景文件名: {report_info['reader_file']}",
        f"Reader+Sensor 文件名: {report_info['reader_sensor_file']}",
        "计算方式: Reader+Sensor - Reader",
        "匹配规则: 只按 Cr 匹配，忽略 Cs 和 ks",
        f"频率点数: {report_info['frequency_points']}",
        f"匹配到的 Cr 范围: {report_info['matched_cr_min']} - {report_info['matched_cr_max']}",
        f"输出差分列数: {report_info['output_diff_columns']}",
        f"未匹配列数量: {report_info['unmatched_count']}",
        f"Reader 可用 Cr 数量: {report_info['reader_cr_count']}",
    ]
    if report_info.get("duplicate_reader_cr_columns"):
        lines.append(f"Reader 重复 Cr 列（已忽略后出现的列）: {len(report_info['duplicate_reader_cr_columns'])}")
    lines.extend(["", "未匹配列名前 20 个示例:"])
    examples = report_info.get("unmatched_examples") or []
    if examples:
        lines.extend(f"- {name}" for name in examples)
    else:
        lines.append("- 无")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def batch_diff_reader_sensor_by_cr(reader_path, reader_sensor_paths, output_dir, interpolate=False):
    reader_path = Path(reader_path).resolve()
    reader_sensor_paths = [Path(path).resolve() for path in reader_sensor_paths]
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    reader_df = read_table(reader_path)
    results = []

    for sensor_path in reader_sensor_paths:
        sensor_df = read_table(sensor_path)
        diff_df, report_info = diff_single_reader_sensor_by_cr(reader_df, sensor_df, interpolate=interpolate)

        base = f"{sensor_path.stem}_diff_by_reader_cr"
        csv_path = output_dir / f"{base}.csv"
        origin_path = output_dir / f"{base}_Origin.txt"
        xlsx_path = output_dir / f"{base}.xlsx"
        report_path = output_dir / f"{base}_report.txt"

        diff_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        write_origin_txt(diff_df, origin_path)
        xlsx_error = None
        try:
            diff_df.to_excel(xlsx_path, index=False)
        except Exception as exc:
            xlsx_error = exc
            xlsx_path = None

        report_info.update(
            {
                "reader_file": reader_path.name,
                "reader_sensor_file": sensor_path.name,
                "csv_path": csv_path,
                "origin_path": origin_path,
                "xlsx_path": xlsx_path,
                "xlsx_error": xlsx_error,
                "report_path": report_path,
            }
        )
        write_diff_report(report_info, report_path)
        results.append(report_info)

    return results


def run_merge_cli(argv):
    parser = argparse.ArgumentParser(description="Merge multiple wide-format tables by keeping the first X-axis column.")
    parser.add_argument("files", nargs="*", help="Files to merge. If empty, auto-detect files beside this script.")
    parser.add_argument("--no-smart-sort", action="store_true", help="Do not sort data columns by parameters in headers.")
    parser.add_argument("--output-dir", help="Output folder. Defaults to merged_output beside this script.")
    args = parser.parse_args(argv)

    base_dir = Path(__file__).resolve().parent
    files = [Path(item).resolve() for item in args.files] if args.files else discover_input_files(base_dir)
    files = [path for path in files if path.exists() and path.suffix.lower() in SUPPORTED_EXTS]

    print("将要合并的文件：")
    for i, path in enumerate(files, start=1):
        print(f"  {i}. {path.name}")
    print()

    merged, warnings = merge_tables(files, smart_sort=not args.no_smart_sort)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else base_dir / OUTPUT_DIR_NAME
    csv_path, xlsx_path, xlsx_error = write_outputs(merged, output_dir)
    xlsx_note = str(xlsx_path) if xlsx_path else f"Excel 输出失败：{xlsx_error}"

    print(f"完成：{merged.shape[0]} 行 x {merged.shape[1]} 列")
    print(f"CSV : {csv_path}")
    print(f"XLSX: {xlsx_note}")
    if warnings:
        print()
        print("注意：")
        for warning in warnings:
            print(f"  - {warning}")
    print()


def run_diff_by_cr_cli(argv):
    parser = argparse.ArgumentParser(description="按相同 Cr 做 Reader 背景差分。")
    parser.add_argument("--reader", required=True, help="Reader / Background table.")
    parser.add_argument("--reader-sensor", nargs="*", help="One or more Reader+Sensor tables.")
    parser.add_argument("--reader-sensor-dir", help="Folder containing Reader+Sensor tables.")
    parser.add_argument("--out", required=True, help="Output folder.")
    parser.add_argument("--interpolate", action="store_true", help="Reserved. Default is disabled.")
    args = parser.parse_args(argv)

    sensor_paths = []
    if args.reader_sensor:
        sensor_paths.extend(Path(path) for path in args.reader_sensor)
    if args.reader_sensor_dir:
        sensor_paths.extend(discover_table_files(args.reader_sensor_dir))
    if not sensor_paths:
        raise ValueError("请通过 --reader-sensor 或 --reader-sensor-dir 指定 Reader+Sensor 表。")

    results = batch_diff_reader_sensor_by_cr(args.reader, sensor_paths, args.out, interpolate=args.interpolate)

    print(f"Reader 背景文件: {Path(args.reader).resolve()}")
    print(f"Reader+Sensor 文件数量: {len(sensor_paths)}")
    for info in results:
        print()
        print(f"Reader+Sensor: {info['reader_sensor_file']}")
        print(f"匹配到 Cr 列数: {info['output_diff_columns']}")
        print(f"输出差分列数: {info['output_diff_columns']}")
        print(f"CSV : {info['csv_path']}")
        print(f"Origin TXT: {info['origin_path']}")
        print(f"XLSX: {info['xlsx_path'] if info['xlsx_path'] else 'Excel 输出失败: ' + str(info['xlsx_error'])}")
        print(f"Report: {info['report_path']}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "diff-by-cr":
        run_diff_by_cr_cli(argv[1:])
    else:
        run_merge_cli(argv)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"错误：{exc}")
        sys.exit(1)
