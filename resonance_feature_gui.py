"""Tkinter GUI for S11 resonance feature extraction."""

from __future__ import annotations

import json
import string
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from resonance_features import (
    LOCAL_VALLEY_COLUMN,
    SYMMETRIC_FREQ_DIFF_COLUMN,
    SYMMETRIC_MIDDLE_PEAK_DELTA_COLUMN,
    SYMMETRIC_MIDDLE_PEAK_FREQ_COLUMN,
    extract_double_resonance_features,
    extract_resonance_features,
)


class ResultProcessingDialog(tk.Toplevel):
    """Dialog for filtering extracted rows and rebuilding a derived result table."""

    def __init__(self, parent: tk.Tk, result: pd.DataFrame) -> None:
        super().__init__(parent)
        self.title("Export & Process / 导出结果再处理")
        self.geometry("1380x860")
        self.minsize(1120, 740)
        self.transient(parent)

        self.source = result.copy()
        self.current = self.source.copy()
        self.config_path = Path(__file__).with_name(".result_processing_settings.json")
        self.saved_settings = self._load_settings()
        self.formula_results: dict[str, pd.DataFrame] = {}
        self.aliases = self._build_aliases(list(self.source.columns))
        self.formula_tables = self._load_formula_tables()
        self.table_axis_labels = self._load_table_axis_labels()
        self.table_panels: dict[str, dict[str, object]] = {}
        self.active_formula_table = tk.StringVar(value=self._initial_active_formula_table())

        self.group_columns = tk.StringVar(value=self.saved_settings.get("group_columns", self._default_group_columns()))
        self.target_column = tk.StringVar(value=self.saved_settings.get("target_column", self._default_target_column()))
        self.operator = tk.StringVar(value=self.saved_settings.get("operator", ">"))
        self.threshold = tk.StringVar(value=self.saved_settings.get("threshold", "0.15"))
        self.pick_mode = tk.StringVar(value=self.saved_settings.get("pick_mode", "minimum"))
        if self.target_column.get() not in self.source.columns:
            self.target_column.set(self._default_target_column())
        self.status_text = tk.StringVar(value=f"Loaded {len(self.source)} extracted rows.")

        self._build_layout()
        self._refresh_input_preview()
        self._clear_all_formula_previews()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(3, weight=2)

        top = ttk.Frame(self, padding=10)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        alias_frame = ttk.LabelFrame(top, text="Parameter Names / 参数名", padding=8)
        alias_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        alias_text = tk.Text(alias_frame, height=7, width=34, wrap="none")
        alias_text.grid(row=0, column=0, sticky="nsew")
        alias_text.insert("1.0", "\n".join(f"{alias} = {column}" for alias, column in self.aliases.items()))
        alias_text.configure(state="disabled")

        filter_frame = ttk.LabelFrame(top, text="Threshold / 筛选", padding=8)
        filter_frame.grid(row=0, column=1, sticky="nsew")
        filter_frame.columnconfigure(1, weight=1)
        filter_frame.columnconfigure(3, weight=1)

        ttk.Label(filter_frame, text="Group by").grid(row=0, column=0, sticky="w")
        ttk.Entry(filter_frame, textvariable=self.group_columns).grid(row=0, column=1, sticky="ew", padx=(6, 12))
        ttk.Label(filter_frame, text="Target").grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            filter_frame,
            textvariable=self.target_column,
            values=list(self.source.columns),
            state="readonly",
        ).grid(row=0, column=3, sticky="ew", padx=(6, 0))

        ttk.Label(filter_frame, text="Condition").grid(row=1, column=0, sticky="w", pady=(8, 0))
        condition = ttk.Frame(filter_frame)
        condition.grid(row=1, column=1, sticky="ew", padx=(6, 12), pady=(8, 0))
        ttk.Combobox(condition, textvariable=self.operator, values=[">", ">=", "<", "<=", "==", "!="], width=5, state="readonly").pack(
            side="left"
        )
        ttk.Entry(condition, textvariable=self.threshold, width=12).pack(side="left", padx=(6, 0))

        ttk.Label(filter_frame, text="Pick in group").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Combobox(
            filter_frame,
            textvariable=self.pick_mode,
            values=["all matched", "minimum", "maximum", "first"],
            state="readonly",
        ).grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=(8, 0))

        filter_actions = ttk.Frame(filter_frame)
        filter_actions.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Button(filter_actions, text="Preview Filter / 预览筛选", command=self._preview_filter).grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Button(filter_actions, text="Apply Filter / 应用筛选", command=self._apply_filter).grid(
            row=0, column=1, sticky="w", padx=(0, 6)
        )
        ttk.Button(filter_actions, text="Reset / 重置", command=self._reset_filter).grid(
            row=0, column=2, sticky="w", padx=(0, 6)
        )
        ttk.Button(filter_actions, text="Export Current / 导出当前表", command=self._export_current).grid(
            row=0, column=3, sticky="w"
        )

        formula_frame = ttk.LabelFrame(self, text="Formula Tables / 多个公式制表", padding=10)
        formula_frame.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=10, pady=(0, 10))
        formula_frame.columnconfigure(0, weight=1)
        formula_frame.rowconfigure(1, weight=1)

        formula_actions = ttk.Frame(formula_frame)
        formula_actions.grid(row=0, column=0, sticky="ew")
        formula_actions.columnconfigure(9, weight=1)
        ttk.Label(
            formula_actions,
            text="Tables are shown in parallel. Select an active table, then build it here.",
        ).grid(row=0, column=0, columnspan=8, sticky="w")
        ttk.Label(formula_actions, text="Active / 当前表").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.active_table_combo = ttk.Combobox(
            formula_actions,
            textvariable=self.active_formula_table,
            values=list(self.formula_tables),
            state="readonly",
            width=12,
        )
        self.active_table_combo.grid(row=1, column=1, sticky="w", padx=(4, 8), pady=(8, 0))
        ttk.Button(formula_actions, text="Build Active / 生成当前表", command=self._build_active_formula_table).grid(
            row=1, column=2, sticky="w", padx=(0, 6), pady=(8, 0)
        )
        ttk.Button(formula_actions, text="Export Active / 导出当前表", command=self._export_active_formula_result).grid(
            row=1, column=3, sticky="w", padx=(0, 6), pady=(8, 0)
        )
        ttk.Button(formula_actions, text="Add Table / 新增表", command=self._add_formula_table).grid(
            row=1, column=4, sticky="w", padx=(0, 6), pady=(8, 0)
        )
        ttk.Button(formula_actions, text="Delete Active / 删除当前表", command=self._delete_active_formula_table).grid(
            row=1, column=5, sticky="w", padx=(0, 6), pady=(8, 0)
        )
        ttk.Button(formula_actions, text="Save Preset / 保存预设", command=self._save_preset).grid(
            row=1, column=6, sticky="w", padx=(0, 6), pady=(8, 0)
        )
        ttk.Button(formula_actions, text="Load Preset / 加载预设", command=self._load_preset).grid(
            row=1, column=7, sticky="w", padx=(0, 6), pady=(8, 0)
        )
        ttk.Button(formula_actions, text="Export All Built / 一键导出已生成", command=self._export_all_formula_results).grid(
            row=1, column=8, sticky="w", padx=(0, 6), pady=(8, 0)
        )
        ttk.Label(formula_actions, textvariable=self.status_text).grid(row=1, column=9, sticky="w", padx=(8, 0), pady=(8, 0))

        self.tables_paned = ttk.PanedWindow(formula_frame, orient="horizontal")
        self.tables_paned.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        for table_name in self.formula_tables:
            self._create_formula_table_panel(table_name)

        input_preview_frame = ttk.LabelFrame(self, text="Input Preview / 可操作数据预览", padding=8)
        input_preview_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
        input_preview_frame.columnconfigure(0, weight=1)
        input_preview_frame.rowconfigure(0, weight=1)
        self.input_preview = ttk.Treeview(input_preview_frame, show="headings", height=6)
        input_y_scroll = ttk.Scrollbar(input_preview_frame, orient="vertical", command=self.input_preview.yview)
        input_x_scroll = ttk.Scrollbar(input_preview_frame, orient="horizontal", command=self.input_preview.xview)
        self.input_preview.configure(yscrollcommand=input_y_scroll.set, xscrollcommand=input_x_scroll.set)
        self.input_preview.grid(row=0, column=0, sticky="nsew")
        input_y_scroll.grid(row=0, column=1, sticky="ns")
        input_x_scroll.grid(row=1, column=0, sticky="ew")

    def _load_settings(self) -> dict[str, object]:
        if not self.config_path.exists():
            return {}
        try:
            with self.config_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _load_formula_tables(self) -> dict[str, list[tuple[str, str]]]:
        raw_tables = self.saved_settings.get("formula_tables", {})
        tables: dict[str, list[tuple[str, str]]] = {}
        if isinstance(raw_tables, dict):
            for table_name, rows in raw_tables.items():
                if not isinstance(table_name, str) or not isinstance(rows, list):
                    continue
                parsed_rows: list[tuple[str, str]] = []
                for row in rows:
                    if isinstance(row, dict):
                        parsed_rows.append((str(row.get("title", "")), str(row.get("formula", ""))))
                if parsed_rows:
                    tables[table_name] = parsed_rows
        for table_name in ("Table 1", "Table 2"):
            tables.setdefault(table_name, self._default_formula_rows())
        return tables

    def _load_table_axis_labels(self) -> dict[str, dict[str, str]]:
        raw_labels = self.saved_settings.get("table_axis_labels", {})
        labels: dict[str, dict[str, str]] = {}
        if isinstance(raw_labels, dict):
            for table_name, values in raw_labels.items():
                if isinstance(table_name, str) and isinstance(values, dict):
                    labels[table_name] = {
                        "x": str(values.get("x", "")),
                        "y": str(values.get("y", "")),
                        "z": str(values.get("z", "")),
                    }
        for table_name in self.formula_tables:
            labels.setdefault(table_name, {"x": "", "y": "", "z": ""})
        return labels

    def _save_settings(self) -> None:
        self._save_all_formula_rows()
        data = {
            "group_columns": self.group_columns.get(),
            "target_column": self.target_column.get(),
            "operator": self.operator.get(),
            "threshold": self.threshold.get(),
            "pick_mode": self.pick_mode.get(),
            "active_formula_table": self.active_formula_table.get(),
            "formula_tables": {
                table_name: [
                    {"title": title, "formula": formula}
                    for title, formula in rows
                    if title or formula
                ]
                for table_name, rows in self.formula_tables.items()
            },
            "table_axis_labels": self.table_axis_labels,
        }
        try:
            with self.config_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.status_text.set(f"Settings save failed: {exc}")

    def _on_close(self) -> None:
        self._save_settings()
        self.destroy()

    def _preview_filter(self) -> None:
        try:
            target = self.target_column.get()
            filtered = self._pick_rows_by_group(self._filter_rows(self.source, target), target)
        except Exception as exc:
            messagebox.showerror("Filter preview failed", str(exc))
            return

        self._refresh_input_preview(filtered)
        self.status_text.set(f"Previewing {len(filtered)} filtered rows. Click Apply Filter to use them.")

    def _apply_filter(self) -> None:
        self._save_settings()
        target = self.target_column.get()
        if target not in self.source.columns:
            messagebox.showwarning("Missing target", "Please select a target column.")
            return

        try:
            filtered = self._filter_rows(self.source, target)
            self.current = self._pick_rows_by_group(filtered, target)
        except Exception as exc:
            messagebox.showerror("Filter failed", str(exc))
            return

        self.formula_results.clear()
        self._refresh_input_preview()
        self._clear_all_formula_previews()
        self.status_text.set(f"Filtered to {len(self.current)} rows.")

    def _reset_filter(self) -> None:
        self.current = self.source.copy()
        self.formula_results.clear()
        self._refresh_input_preview()
        self._clear_all_formula_previews()
        self.status_text.set(f"Reset to {len(self.current)} rows.")

    def _filter_rows(self, data: pd.DataFrame, target: str) -> pd.DataFrame:
        threshold_text = self.threshold.get().strip()
        if not threshold_text:
            return data.copy()

        threshold = float(threshold_text)
        values = pd.to_numeric(data[target], errors="coerce")
        op = self.operator.get()
        if op == ">":
            mask = values > threshold
        elif op == ">=":
            mask = values >= threshold
        elif op == "<":
            mask = values < threshold
        elif op == "<=":
            mask = values <= threshold
        elif op == "==":
            mask = values == threshold
        elif op == "!=":
            mask = values != threshold
        else:
            raise ValueError(f"Unsupported operator: {op}")
        return data.loc[mask.fillna(False)].copy()

    def _pick_rows_by_group(self, data: pd.DataFrame, target: str) -> pd.DataFrame:
        if data.empty:
            return data

        group_columns = [column.strip() for column in self.group_columns.get().split(",") if column.strip()]
        missing = [column for column in group_columns if column not in data.columns]
        if missing:
            raise ValueError(f"Group columns not found: {', '.join(missing)}")

        values = pd.to_numeric(data[target], errors="coerce")
        pick_mode = self.pick_mode.get()
        if pick_mode == "all matched":
            return data.reset_index(drop=True)
        if not group_columns:
            return self._pick_one(data, values, pick_mode)

        rows: list[pd.DataFrame] = []
        for _, group in data.assign(_target_value=values).groupby(group_columns, dropna=False, sort=False):
            rows.append(self._pick_one(group.drop(columns=["_target_value"]), group["_target_value"], pick_mode))
        return pd.concat(rows, ignore_index=True) if rows else data.iloc[0:0].copy()

    def _pick_one(self, data: pd.DataFrame, values: pd.Series, pick_mode: str) -> pd.DataFrame:
        valid_values = values.dropna()
        if pick_mode == "first" or valid_values.empty:
            return data.head(1)
        if pick_mode == "maximum":
            return data.loc[[valid_values.idxmax()]]
        return data.loc[[valid_values.idxmin()]]

    def _build_formula_table(self, table_name: str) -> None:
        self._save_formula_rows(table_name)
        formulas = self._collect_formula_rows(table_name)
        if not formulas:
            messagebox.showwarning("Missing formulas", "Please enter at least one formula.")
            return

        try:
            result = self._evaluate_formulas(self.current, formulas)
        except Exception as exc:
            messagebox.showerror("Formula failed", str(exc))
            return

        self.formula_results[table_name] = result
        self._save_settings()
        self._refresh_preview(result, self.table_panels[table_name]["preview"])
        self.status_text.set(f"Built {table_name} with {len(result)} rows.")

    def _apply_formula_table_to_preview(self, table_name: str) -> None:
        self._save_formula_rows(table_name)
        formulas = self._collect_formula_rows(table_name)
        if not formulas:
            messagebox.showwarning("Missing formulas", "Please enter at least one formula.")
            return

        try:
            new_columns = self._evaluate_formulas(self.current, formulas)
        except Exception as exc:
            messagebox.showerror("Formula failed", str(exc))
            return

        existing = self.formula_results.get(table_name)
        if existing is None or len(existing) != len(new_columns):
            result = new_columns
        else:
            result = existing.copy()
            for column in new_columns.columns:
                result[column] = new_columns[column].to_numpy()

        self.formula_results[table_name] = result
        self._save_settings()
        self._refresh_preview(result, self.table_panels[table_name]["preview"])
        self.status_text.set(f"Updated {table_name} preview with {len(new_columns.columns)} formula columns.")

    def _build_active_formula_table(self) -> None:
        table_name = self.active_formula_table.get()
        if table_name not in self.table_panels:
            messagebox.showwarning("Missing table", "Please select a valid active table.")
            return
        self._build_formula_table(table_name)

    def _evaluate_formulas(self, data: pd.DataFrame, formulas: list[tuple[str, str]] | list[str]) -> pd.DataFrame:
        alias_data = pd.DataFrame(index=data.index)
        for alias, column in self.aliases.items():
            if column in data.columns:
                alias_data[alias] = self._coerce_numeric_or_keep(data[column])

        output: dict[str, pd.Series] = {}
        for index, item in enumerate(formulas, start=1):
            if isinstance(item, tuple):
                name, expression = item
            else:
                line = item
                if "=" in line:
                    name, expression = [part.strip() for part in line.split("=", 1)]
                else:
                    name = f"formula_{index}"
                    expression = line
            name = name.strip() or f"column_{index}"
            expression = expression.strip()
            if not expression:
                raise ValueError(f"Formula row {index} is empty.")

            if expression in self.aliases and self.aliases[expression] in data.columns:
                output[name] = data[self.aliases[expression]]
            elif expression in data.columns:
                output[name] = data[expression]
            else:
                output[name] = alias_data.eval(expression, engine="python")

        return pd.DataFrame(output).reset_index(drop=True)

    def _default_formula_rows(self) -> list[tuple[str, str]]:
        return [("ratio", "(B-A)/A"), ("copy_C", "C")] if len(self.source.columns) >= 3 else [("value", "A")]

    def _initial_active_formula_table(self) -> str:
        saved = self.saved_settings.get("active_formula_table")
        if isinstance(saved, str) and saved in self.formula_tables:
            return saved
        return next(iter(self.formula_tables), "Table 1")

    def _create_formula_table_panel(self, table_name: str) -> None:
        panel = ttk.LabelFrame(self.tables_paned, text=table_name, padding=8)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(4, weight=1)

        grid = ttk.Frame(panel)
        grid.grid(row=0, column=0, sticky="ew")
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(2, weight=2)
        ttk.Label(grid, text="#").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Label(grid, text="Title / 标题").grid(row=0, column=1, sticky="ew", padx=(0, 6))
        ttk.Label(grid, text="Formula / 公式").grid(row=0, column=2, sticky="ew")

        axis_frame = ttk.Frame(panel)
        axis_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        axis_frame.columnconfigure(1, weight=1)
        axis_frame.columnconfigure(3, weight=1)
        axis_frame.columnconfigure(5, weight=1)
        axis_labels = self.table_axis_labels.setdefault(table_name, {"x": "", "y": "", "z": ""})
        x_label = tk.StringVar(value=axis_labels.get("x", ""))
        y_label = tk.StringVar(value=axis_labels.get("y", ""))
        z_label = tk.StringVar(value=axis_labels.get("z", ""))
        ttk.Label(axis_frame, text="X").grid(row=0, column=0, sticky="w")
        ttk.Entry(axis_frame, textvariable=x_label, width=12).grid(row=0, column=1, sticky="ew", padx=(4, 8))
        ttk.Label(axis_frame, text="Y").grid(row=0, column=2, sticky="w")
        ttk.Entry(axis_frame, textvariable=y_label, width=12).grid(row=0, column=3, sticky="ew", padx=(4, 8))
        ttk.Label(axis_frame, text="Z").grid(row=0, column=4, sticky="w")
        ttk.Entry(axis_frame, textvariable=z_label, width=12).grid(row=0, column=5, sticky="ew", padx=(4, 0))

        actions = ttk.Frame(panel)
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="Add Row / 加一行", command=lambda name=table_name: self._add_formula_row(name)).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            actions,
            text="Remove Row / 删一行",
            command=lambda name=table_name: self._remove_formula_row(name),
        ).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Button(
            actions,
            text="Apply to Preview / 追加到预览",
            command=lambda name=table_name: self._apply_formula_table_to_preview(name),
        ).grid(row=0, column=2, sticky="w", padx=(6, 0))
        ttk.Label(panel, text="Preview / 预览").grid(row=3, column=0, sticky="w", pady=(8, 2))
        preview = ttk.Treeview(panel, show="headings", height=8)
        y_scroll = ttk.Scrollbar(panel, orient="vertical", command=preview.yview)
        x_scroll = ttk.Scrollbar(panel, orient="horizontal", command=preview.xview)
        preview.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        preview.grid(row=4, column=0, sticky="nsew")
        y_scroll.grid(row=4, column=1, sticky="ns")
        x_scroll.grid(row=5, column=0, sticky="ew")

        self.table_panels[table_name] = {
            "frame": panel,
            "grid": grid,
            "rows": [],
            "preview": preview,
            "axis_vars": {"x": x_label, "y": y_label, "z": z_label},
        }
        self.tables_paned.add(panel, weight=1)
        for title, formula in self.formula_tables.get(table_name, self._default_formula_rows()):
            self._add_formula_row(table_name, title, formula, save=False)
        self._refresh_preview(pd.DataFrame(), preview, empty_message="Click Build to generate.")

    def _add_formula_table(self) -> None:
        existing_numbers = []
        for table_name in self.formula_tables:
            if table_name.startswith("Table "):
                suffix = table_name.removeprefix("Table ")
                if suffix.isdigit():
                    existing_numbers.append(int(suffix))
        next_number = max(existing_numbers, default=0) + 1
        table_name = f"Table {next_number}"
        self.formula_tables[table_name] = self._default_formula_rows()
        self.table_axis_labels[table_name] = {"x": "", "y": "", "z": ""}
        self._create_formula_table_panel(table_name)
        self._refresh_active_table_choices()
        self.active_formula_table.set(table_name)
        self._save_settings()
        self.status_text.set(f"Added {table_name}.")

    def _delete_active_formula_table(self) -> None:
        table_name = self.active_formula_table.get()
        if table_name not in self.table_panels:
            messagebox.showwarning("Missing table", "Please select a valid active table.")
            return
        if len(self.table_panels) <= 1:
            messagebox.showwarning("Cannot delete", "At least one table must remain.")
            return
        if not messagebox.askyesno("Delete table", f"Delete {table_name}?"):
            return

        panel = self.table_panels.pop(table_name)
        self.tables_paned.forget(panel["frame"])
        panel["frame"].destroy()
        self.formula_tables.pop(table_name, None)
        self.table_axis_labels.pop(table_name, None)
        self.formula_results.pop(table_name, None)

        next_table = next(iter(self.table_panels))
        self.active_formula_table.set(next_table)
        self._refresh_active_table_choices()
        self._save_settings()
        self.status_text.set(f"Deleted {table_name}.")

    def _save_preset(self) -> None:
        self._save_all_formula_rows()
        filename = filedialog.asksaveasfilename(
            title="Save table preset",
            initialfile="formula_table_preset.json",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not filename:
            return

        preset = {
            "formula_tables": {
                table_name: [
                    {"title": title, "formula": formula}
                    for title, formula in rows
                    if title or formula
                ]
                for table_name, rows in self.formula_tables.items()
            },
            "table_axis_labels": self.table_axis_labels,
        }
        try:
            with Path(filename).open("w", encoding="utf-8") as handle:
                json.dump(preset, handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            messagebox.showerror("Preset save failed", str(exc))
            return

        self.status_text.set(f"Saved preset: {filename}")

    def _load_preset(self) -> None:
        filename = filedialog.askopenfilename(
            title="Load table preset",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not filename:
            return

        try:
            with Path(filename).open("r", encoding="utf-8") as handle:
                preset = json.load(handle)
            formula_tables, axis_labels = self._parse_table_preset(preset)
        except Exception as exc:
            messagebox.showerror("Preset load failed", str(exc))
            return

        self._apply_table_configuration(formula_tables, axis_labels)
        self._save_settings()
        self.status_text.set(f"Loaded preset: {filename}")

    def _parse_table_preset(self, preset: object) -> tuple[dict[str, list[tuple[str, str]]], dict[str, dict[str, str]]]:
        if not isinstance(preset, dict):
            raise ValueError("Preset must be a JSON object.")

        raw_tables = preset.get("formula_tables", {})
        if not isinstance(raw_tables, dict):
            raise ValueError("Preset is missing formula_tables.")

        formula_tables: dict[str, list[tuple[str, str]]] = {}
        for table_name, rows in raw_tables.items():
            if not isinstance(table_name, str) or not isinstance(rows, list):
                continue
            parsed_rows: list[tuple[str, str]] = []
            for row in rows:
                if isinstance(row, dict):
                    parsed_rows.append((str(row.get("title", "")), str(row.get("formula", ""))))
            if parsed_rows:
                formula_tables[table_name] = parsed_rows

        if not formula_tables:
            raise ValueError("Preset has no formula rows.")

        raw_labels = preset.get("table_axis_labels", {})
        axis_labels: dict[str, dict[str, str]] = {}
        if isinstance(raw_labels, dict):
            for table_name, labels in raw_labels.items():
                if isinstance(table_name, str) and isinstance(labels, dict):
                    axis_labels[table_name] = {
                        "x": str(labels.get("x", "")),
                        "y": str(labels.get("y", "")),
                        "z": str(labels.get("z", "")),
                    }
        return formula_tables, axis_labels

    def _apply_table_configuration(
        self,
        formula_tables: dict[str, list[tuple[str, str]]],
        axis_labels: dict[str, dict[str, str]],
    ) -> None:
        for panel in list(self.table_panels.values()):
            self.tables_paned.forget(panel["frame"])
            panel["frame"].destroy()

        self.table_panels.clear()
        self.formula_results.clear()
        self.formula_tables = formula_tables
        self.table_axis_labels = {
            table_name: axis_labels.get(table_name, {"x": "", "y": "", "z": ""})
            for table_name in formula_tables
        }

        for table_name in self.formula_tables:
            self._create_formula_table_panel(table_name)

        self.active_formula_table.set(next(iter(self.formula_tables)))
        self._refresh_active_table_choices()

    def _refresh_active_table_choices(self) -> None:
        if hasattr(self, "active_table_combo"):
            self.active_table_combo.configure(values=list(self.formula_tables))

    def _clear_all_formula_previews(self) -> None:
        for panel in getattr(self, "table_panels", {}).values():
            self._refresh_preview(pd.DataFrame(), panel["preview"], empty_message="Click Build to generate.")

    def _add_formula_row(self, table_name: str, title: str = "", formula: str = "", *, save: bool = True) -> None:
        panel = self.table_panels[table_name]
        rows = panel["rows"]
        grid = panel["grid"]
        row_number = len(rows) + 1
        label = ttk.Label(grid, text=str(row_number))
        title_entry = ttk.Entry(grid)
        formula_entry = ttk.Entry(grid)
        title_entry.insert(0, title)
        formula_entry.insert(0, formula)
        label.grid(row=row_number, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        title_entry.grid(row=row_number, column=1, sticky="ew", padx=(0, 6), pady=(4, 0))
        formula_entry.grid(row=row_number, column=2, sticky="ew", pady=(4, 0))
        rows.append((label, title_entry, formula_entry))
        if save:
            self._save_formula_rows(table_name)

    def _remove_formula_row(self, table_name: str) -> None:
        rows = self.table_panels[table_name]["rows"]
        if not rows:
            return
        row = rows.pop()
        for widget in row:
            widget.destroy()
        self._save_formula_rows(table_name)

    def _collect_formula_rows(self, table_name: str) -> list[tuple[str, str]]:
        formulas: list[tuple[str, str]] = []
        for index, (_, title_entry, formula_entry) in enumerate(self.table_panels[table_name]["rows"], start=1):
            title = title_entry.get().strip() or f"column_{index}"
            formula = formula_entry.get().strip()
            if formula:
                formulas.append((title, formula))
        return formulas

    def _save_formula_rows(self, table_name: str) -> None:
        panel = self.table_panels.get(table_name)
        if not panel:
            return
        self.formula_tables[table_name] = [
            (title.get().strip(), formula.get().strip())
            for _, title, formula in panel["rows"]
        ]
        axis_vars = panel.get("axis_vars", {})
        self.table_axis_labels[table_name] = {
            "x": axis_vars["x"].get().strip(),
            "y": axis_vars["y"].get().strip(),
            "z": axis_vars["z"].get().strip(),
        }

    def _save_all_formula_rows(self) -> None:
        for table_name in list(self.table_panels):
            self._save_formula_rows(table_name)

    def _export_current(self) -> None:
        self._export_dataframe(self.current, "processed_filtered_result.csv")

    def _export_formula_result(self, table_name: str) -> None:
        if table_name not in self.formula_results:
            messagebox.showwarning("Not generated", f"Please build {table_name} before exporting it.")
            return
        safe_name = table_name.lower().replace(" ", "_")
        self._export_dataframe(self.formula_results[table_name], f"processed_{safe_name}.csv")

    def _export_active_formula_result(self) -> None:
        table_name = self.active_formula_table.get()
        if table_name not in self.table_panels:
            messagebox.showwarning("Missing table", "Please select a valid active table.")
            return
        self._export_formula_result(table_name)

    def _export_all_formula_results(self) -> None:
        self._save_all_formula_rows()
        if not self.formula_results:
            messagebox.showwarning("No built tables", "Please build at least one table before exporting all.")
            return

        directory = filedialog.askdirectory(title="Choose folder for all formula tables")
        if not directory:
            return

        try:
            for table_name, data in self.formula_results.items():
                safe_name = table_name.lower().replace(" ", "_")
                data.to_csv(Path(directory) / f"processed_{safe_name}.csv", index=False)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return

        self._save_settings()
        self.status_text.set(f"Saved {len(self.formula_results)} built tables to: {directory}")
        messagebox.showinfo("Export complete", f"Saved {len(self.formula_results)} built tables to:\n{directory}")

    def _export_dataframe(self, data: pd.DataFrame, default_name: str) -> None:
        filename = filedialog.asksaveasfilename(
            title="Export processed result",
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not filename:
            return

        try:
            data.to_csv(filename, index=False)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return

        self.status_text.set(f"Saved: {filename}")
        messagebox.showinfo("Export complete", f"Saved result to:\n{filename}")

    def _refresh_preview(self, data: pd.DataFrame, preview: ttk.Treeview, empty_message: str = "") -> None:
        for item in preview.get_children():
            preview.delete(item)

        columns = list(data.columns)
        if not columns and empty_message:
            columns = ["Status"]
            preview.configure(columns=columns)
            preview.heading("Status", text="Status")
            preview.column("Status", anchor="center", width=220, stretch=True)
            preview.insert("", "end", values=[empty_message])
            return

        preview.configure(columns=columns)
        for column in columns:
            preview.heading(column, text=column)
            preview.column(column, anchor="center", width=130, stretch=True)

        for row in data.head(500).itertuples(index=False, name=None):
            preview.insert("", "end", values=[self._format_value(value) for value in row])

    def _refresh_input_preview(self, data: pd.DataFrame | None = None) -> None:
        if not hasattr(self, "input_preview"):
            return
        self._refresh_preview(self.current if data is None else data, self.input_preview)

    def _default_group_columns(self) -> str:
        defaults = [column for column in ("Cr", "Cs") if column in self.source.columns]
        return ",".join(defaults)

    def _default_target_column(self) -> str:
        if SYMMETRIC_FREQ_DIFF_COLUMN in self.source.columns:
            return SYMMETRIC_FREQ_DIFF_COLUMN
        return self.source.columns[-1] if len(self.source.columns) else ""

    @staticmethod
    def _build_aliases(columns: list[str]) -> dict[str, str]:
        return {ResultProcessingDialog._column_alias(index): column for index, column in enumerate(columns)}

    @staticmethod
    def _column_alias(index: int) -> str:
        letters = string.ascii_uppercase
        alias = ""
        index += 1
        while index:
            index, remainder = divmod(index - 1, len(letters))
            alias = letters[remainder] + alias
        return alias

    @staticmethod
    def _coerce_numeric_or_keep(series: pd.Series) -> pd.Series:
        return pd.to_numeric(series, errors="coerce")

    @staticmethod
    def _format_value(value: object) -> str:
        if pd.isna(value):
            return "NaN"
        if isinstance(value, float):
            return f"{value:.10g}"
        return str(value)


class ResonanceFeatureApp(tk.Tk):
    """Small desktop interface for selecting input CSV and saving output CSV."""

    def __init__(self) -> None:
        super().__init__()
        self.title("S11 Resonance Feature Extractor")
        self.geometry("1180x780")
        self.minsize(920, 620)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.detection_mode = tk.StringVar(value="single")
        self.extract_local_valley = tk.BooleanVar(value=False)
        self.extract_symmetric_peak = tk.BooleanVar(value=False)
        self.plot_scope = tk.StringVar(value="all")
        self.show_feature_points = tk.BooleanVar(value=True)
        self.status_text = tk.StringVar(value="Select a wide-format S11 CSV file.")
        self.result: pd.DataFrame | None = None
        self.input_data: pd.DataFrame | None = None
        self.frequency: pd.Series | None = None
        self.curve_columns: list[str] = []

        self._build_layout()

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        controls = ttk.Frame(self, padding=12)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Input CSV").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(controls, textvariable=self.input_path).grid(row=0, column=1, sticky="ew")
        ttk.Button(controls, text="Browse", command=self._choose_input).grid(row=0, column=2, padx=(8, 0))

        ttk.Label(controls, text="Output CSV").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(controls, textvariable=self.output_path).grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Save As", command=self._choose_output).grid(
            row=1, column=2, padx=(8, 0), pady=(8, 0)
        )

        mode_frame = ttk.LabelFrame(controls, text="Detection mode", padding=(8, 4))
        mode_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Radiobutton(
            mode_frame,
            text="Single peak",
            value="single",
            variable=self.detection_mode,
            command=self._on_mode_changed,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_frame,
            text="Double peak",
            value="double",
            variable=self.detection_mode,
            command=self._on_mode_changed,
        ).pack(side="left", padx=(16, 0))
        self.local_valley_check = ttk.Checkbutton(
            mode_frame,
            text="Extract local valley / 提取局部谷值",
            variable=self.extract_local_valley,
            command=self._on_double_option_changed,
        )
        self.local_valley_check.pack(side="left", padx=(20, 0))
        self.symmetric_peak_check = ttk.Checkbutton(
            mode_frame,
            text="Symmetric peak / 对称峰",
            variable=self.extract_symmetric_peak,
            command=self._on_double_option_changed,
        )
        self.symmetric_peak_check.pack(side="left", padx=(16, 0))
        self._update_double_option_state()

        actions = ttk.Frame(controls)
        actions.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Run Extraction", command=self._run_extraction).pack(side="left")
        ttk.Button(actions, text="Export Result", command=self._export_result).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Export & Process / 导出结果再处理", command=self._open_processing_dialog).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(actions, textvariable=self.status_text).pack(side="left", padx=(16, 0))

        content = ttk.PanedWindow(self, orient="vertical")
        content.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        plot_frame = ttk.Frame(content)
        plot_frame.columnconfigure(1, weight=1)
        plot_frame.rowconfigure(0, weight=1)

        selector = ttk.LabelFrame(plot_frame, text="Curves", padding=8)
        selector.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        selector.rowconfigure(2, weight=1)

        scope_frame = ttk.Frame(selector)
        scope_frame.grid(row=0, column=0, sticky="ew")
        ttk.Radiobutton(
            scope_frame,
            text="All",
            value="all",
            variable=self.plot_scope,
            command=self._refresh_plot,
        ).pack(side="left")
        ttk.Radiobutton(
            scope_frame,
            text="Selected",
            value="selected",
            variable=self.plot_scope,
            command=self._refresh_plot,
        ).pack(side="left", padx=(10, 0))

        ttk.Checkbutton(
            selector,
            text="Show extracted points",
            variable=self.show_feature_points,
            command=self._on_show_feature_points_changed,
        ).grid(row=1, column=0, sticky="w", pady=(8, 6))

        list_frame = ttk.Frame(selector)
        list_frame.grid(row=2, column=0, sticky="nsew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        self.curve_list = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=12, exportselection=False)
        self.curve_list.grid(row=0, column=0, sticky="nsew")
        self.curve_list.bind("<<ListboxSelect>>", self._on_curve_selection_changed)
        curve_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.curve_list.yview)
        curve_scroll.grid(row=0, column=1, sticky="ns")
        self.curve_list.configure(yscrollcommand=curve_scroll.set)

        list_actions = ttk.Frame(selector)
        list_actions.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(list_actions, text="Select All", command=self._select_all_curves).pack(side="left")
        ttk.Button(list_actions, text="Clear", command=self._clear_curve_selection).pack(side="left", padx=(6, 0))
        ttk.Button(list_actions, text="Single", command=self._select_single_curve).pack(side="left", padx=(6, 0))

        figure_frame = ttk.Frame(plot_frame)
        figure_frame.grid(row=0, column=1, sticky="nsew")
        figure_frame.columnconfigure(0, weight=1)
        figure_frame.rowconfigure(0, weight=1)

        self.figure = Figure(figsize=(7, 4), dpi=100)
        self.axes = self.figure.add_subplot(111)
        self.axes.set_title("S11 curves")
        self.axes.set_xlabel("Frequency")
        self.axes.set_ylabel("S11")
        self.canvas = FigureCanvasTkAgg(self.figure, master=figure_frame)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        toolbar = NavigationToolbar2Tk(self.canvas, figure_frame, pack_toolbar=False)
        toolbar.update()
        toolbar.grid(row=1, column=0, sticky="ew")

        table_frame = ttk.Frame(content)
        table_frame.columnconfigure(0, weight=1)
        table_frame.columnconfigure(2, weight=0)
        table_frame.rowconfigure(0, weight=1)

        self.table = ttk.Treeview(table_frame, show="headings")
        self._set_table_columns(self._current_columns())
        self.table.bind("<<TreeviewSelect>>", self._on_result_row_selected)

        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.table.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        detail_frame = ttk.LabelFrame(table_frame, text="Selected Curve / 选中曲线", padding=6)
        detail_frame.grid(row=0, column=2, rowspan=2, sticky="nsew", padx=(10, 0))
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)

        self.detail_figure = Figure(figsize=(3.2, 2.2), dpi=100)
        self.detail_axes = self.detail_figure.add_subplot(111)
        self.detail_canvas = FigureCanvasTkAgg(self.detail_figure, master=detail_frame)
        self.detail_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self._clear_selected_curve_plot()

        content.add(plot_frame, weight=3)
        content.add(table_frame, weight=2)

    def _choose_input(self) -> None:
        filename = filedialog.askopenfilename(
            title="Select S11 wide CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not filename:
            return

        input_file = Path(filename)
        self.input_path.set(str(input_file))
        if not self.output_path.get():
            self.output_path.set(str(input_file.with_name(self._default_output_name(input_file))))
        self._load_input_data()
        self._refresh_plot()

    def _choose_output(self) -> None:
        filename = filedialog.asksaveasfilename(
            title="Save extracted resonance features",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if filename:
            self.output_path.set(filename)

    def _run_extraction(self) -> None:
        if not self.input_path.get():
            messagebox.showwarning("Missing input", "Please select an input CSV file.")
            return

        try:
            self._load_input_data()
            if self.detection_mode.get() == "double":
                self.result = extract_double_resonance_features(
                    self.input_path.get(),
                    include_local_valley=self.extract_local_valley.get(),
                    include_symmetric_peak=self.extract_symmetric_peak.get(),
                )
            else:
                self.result = extract_resonance_features(self.input_path.get())
        except Exception as exc:
            self.result = None
            self._clear_table()
            self.status_text.set("Extraction failed.")
            messagebox.showerror("Extraction failed", str(exc))
            return

        self._show_result(self.result)
        self._refresh_plot()
        mode_label = "double-peak" if self.detection_mode.get() == "double" else "single-peak"
        status = f"Extracted {len(self.result)} S11 curves in {mode_label} mode."
        if self._should_extract_local_valley() and LOCAL_VALLEY_COLUMN in self.result.columns:
            detected_count = int(self.result[LOCAL_VALLEY_COLUMN].notna().sum())
            missing_count = len(self.result) - detected_count
            if missing_count:
                status += f" Local valley detected: {detected_count}; missing: {missing_count}."
                print("No local valley detected.")
            else:
                status += f" Local valley detected: {detected_count}."
        if self._should_extract_symmetric_peak() and SYMMETRIC_MIDDLE_PEAK_FREQ_COLUMN in self.result.columns:
            detected_count = int(self.result[SYMMETRIC_MIDDLE_PEAK_FREQ_COLUMN].notna().sum())
            status += f" Symmetric peak detected: {detected_count}."
        self.status_text.set(status)

    def _export_result(self) -> None:
        if self.result is None:
            self._run_extraction()
            if self.result is None:
                return

        if not self.output_path.get():
            self._choose_output()
            if not self.output_path.get():
                return

        try:
            self.result.to_csv(self.output_path.get(), index=False)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return

        self.status_text.set(f"Saved: {self.output_path.get()}")
        messagebox.showinfo("Export complete", f"Saved result to:\n{self.output_path.get()}")

    def _open_processing_dialog(self) -> None:
        if self.result is None:
            self._run_extraction()
            if self.result is None:
                return

        ResultProcessingDialog(self, self.result)

    def _show_result(self, result: pd.DataFrame) -> None:
        self._clear_table()
        self._set_table_columns(list(result.columns))
        for row_index, row in enumerate(result.itertuples(index=False, name=None)):
            self.table.insert("", "end", iid=f"row_{row_index}", values=[self._format_value(value) for value in row])

    def _clear_table(self) -> None:
        for item in self.table.get_children():
            self.table.delete(item)
        self._clear_selected_curve_plot()

    def _clear_selected_curve_plot(self) -> None:
        self.detail_axes.clear()
        self.detail_axes.set_title("Selected curve", fontsize=9)
        self.detail_axes.set_xlabel("Frequency", fontsize=8)
        self.detail_axes.set_ylabel("S11", fontsize=8)
        self.detail_axes.grid(True, alpha=0.25)
        self.detail_axes.text(0.5, 0.5, "Select a result row.", ha="center", va="center", fontsize=8)
        self.detail_axes.tick_params(labelsize=8)
        self.detail_figure.tight_layout()
        self.detail_canvas.draw_idle()

    def _on_result_row_selected(self, _event: tk.Event) -> None:
        selected = self.table.selection()
        if not selected:
            self._clear_selected_curve_plot()
            return

        row_index = self.table.index(selected[0])
        self._show_selected_curve_plot(row_index)

    def _show_selected_curve_plot(self, row_index: int) -> None:
        self.detail_axes.clear()
        self.detail_axes.set_title("Selected curve", fontsize=9)
        self.detail_axes.set_xlabel("Frequency", fontsize=8)
        self.detail_axes.set_ylabel("S11", fontsize=8)
        self.detail_axes.grid(True, alpha=0.25)
        self.detail_axes.tick_params(labelsize=8)

        if (
            self.result is None
            or self.input_data is None
            or self.frequency is None
            or row_index >= len(self.result)
            or row_index >= len(self.curve_columns)
        ):
            self._clear_selected_curve_plot()
            return

        column_name = self.curve_columns[row_index]
        values = pd.to_numeric(self.input_data[column_name], errors="coerce")
        valid = self.frequency.notna() & values.notna()
        if not valid.any():
            self._clear_selected_curve_plot()
            return

        line = self.detail_axes.plot(
            self.frequency.loc[valid],
            values.loc[valid],
            linewidth=1.2,
            label=column_name,
        )[0]
        if self.show_feature_points.get():
            self._draw_feature_points(row_index, line.get_color(), axes=self.detail_axes)
        self.detail_axes.legend(loc="best", fontsize=7)
        self.detail_figure.tight_layout()
        self.detail_canvas.draw_idle()

    def _select_curve_for_result_row(self, row_index: int) -> None:
        if row_index >= len(self.curve_columns):
            return

        self.curve_list.selection_clear(0, tk.END)
        self.curve_list.selection_set(row_index)
        self.curve_list.activate(row_index)
        self.curve_list.see(row_index)
        self.plot_scope.set("selected")
        self._refresh_plot()

    def _on_mode_changed(self) -> None:
        self.result = None
        if self.detection_mode.get() != "double":
            self.extract_local_valley.set(False)
            self.extract_symmetric_peak.set(False)
        self._update_double_option_state()
        self._clear_table()
        self._set_table_columns(self._current_columns())
        if self.input_path.get():
            input_file = Path(self.input_path.get())
            self.output_path.set(str(input_file.with_name(self._default_output_name(input_file))))
        self._refresh_plot()
        self.status_text.set("Mode changed. Run extraction again.")

    def _on_double_option_changed(self) -> None:
        self.result = None
        self._clear_table()
        self._set_table_columns(self._current_columns())
        self._refresh_plot()
        self.status_text.set("Double-peak option changed. Run extraction again.")

    def _update_double_option_state(self) -> None:
        state = "normal" if self.detection_mode.get() == "double" else "disabled"
        self.local_valley_check.configure(state=state)
        self.symmetric_peak_check.configure(state=state)

    def _should_extract_local_valley(self) -> bool:
        return self.detection_mode.get() == "double" and self.extract_local_valley.get()

    def _should_extract_symmetric_peak(self) -> bool:
        return self.detection_mode.get() == "double" and self.extract_symmetric_peak.get()

    def _load_input_data(self) -> None:
        data = pd.read_csv(self.input_path.get())
        if data.shape[1] < 2:
            raise ValueError("CSV must contain a frequency column and at least one S11 curve column.")

        self.input_data = data
        self.frequency = pd.to_numeric(data.iloc[:, 0], errors="coerce")
        self.curve_columns = [str(column) for column in data.columns[1:]]
        self._populate_curve_list()

    def _populate_curve_list(self) -> None:
        existing_selection = {self.curve_list.get(index) for index in self.curve_list.curselection()}
        self.curve_list.delete(0, tk.END)

        for column in self.curve_columns:
            self.curve_list.insert(tk.END, column)
            if column in existing_selection:
                self.curve_list.selection_set(tk.END)

        if not self.curve_list.curselection() and self.curve_columns:
            self.curve_list.selection_set(0, tk.END)

    def _selected_curve_indices(self) -> list[int]:
        if self.plot_scope.get() == "all":
            return list(range(len(self.curve_columns)))

        selected = list(self.curve_list.curselection())
        if selected:
            return selected
        return []

    def _refresh_plot(self) -> None:
        self.axes.clear()
        self.axes.set_title("S11 curves")
        self.axes.set_xlabel("Frequency")
        self.axes.set_ylabel("S11")
        self.axes.grid(True, alpha=0.25)

        if self.input_data is None or self.frequency is None or not self.curve_columns:
            self.axes.text(0.5, 0.5, "Select an input CSV to preview curves.", ha="center", va="center")
            self.canvas.draw_idle()
            return

        selected_indices = self._selected_curve_indices()
        if not selected_indices:
            self.axes.text(0.5, 0.5, "Select one or more curves to display.", ha="center", va="center")
            self.canvas.draw_idle()
            return

        for curve_index in selected_indices:
            column_name = self.curve_columns[curve_index]
            values = pd.to_numeric(self.input_data[column_name], errors="coerce")
            valid = self.frequency.notna() & values.notna()
            if not valid.any():
                continue

            line = self.axes.plot(
                self.frequency.loc[valid],
                values.loc[valid],
                linewidth=1.4,
                label=column_name,
            )[0]

            if self.show_feature_points.get() and self.result is not None and curve_index < len(self.result):
                self._draw_feature_points(curve_index, line.get_color())

        if len(selected_indices) <= 12:
            self.axes.legend(loc="best", fontsize=8)

        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _draw_feature_points(self, curve_index: int, color: str, axes=None) -> None:
        row = self.result.iloc[curve_index]
        target_axes = axes if axes is not None else self.axes

        if self.detection_mode.get() == "double":
            points = [(row.get("f_res_1"), row.get("S11_min_1")), (row.get("f_res_2"), row.get("S11_min_2"))]
            self._annotate_points(points, color, target_axes)
            if LOCAL_VALLEY_COLUMN in row.index:
                self._annotate_local_valley(curve_index, row, color, target_axes)
            if SYMMETRIC_MIDDLE_PEAK_FREQ_COLUMN in row.index:
                self._annotate_symmetric_peak(curve_index, row, color, target_axes)
        else:
            self._annotate_points([(row.get("f_res"), row.get("S11_min"))], color, target_axes)

    def _annotate_points(self, points: list[tuple[object, object]], color: str, axes) -> None:
        for frequency, amplitude in points:
            if pd.isna(frequency) or pd.isna(amplitude):
                continue
            axes.scatter([frequency], [amplitude], color=color, edgecolors="black", zorder=5)
            axes.annotate(
                f"f={self._format_value(frequency)}\nS11={self._format_value(amplitude)}",
                xy=(frequency, amplitude),
                xytext=(6, 8),
                textcoords="offset points",
                fontsize=8,
                color=color,
                bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": color, "alpha": 0.75},
            )

    def _annotate_local_valley(self, curve_index: int, row: pd.Series, color: str, axes) -> None:
        frequency = row.get("local_valley_freq")
        depth = row.get(LOCAL_VALLEY_COLUMN)
        if pd.isna(frequency) or pd.isna(depth) or self.input_data is None or self.frequency is None:
            return

        column_name = self.curve_columns[curve_index]
        values = pd.to_numeric(self.input_data[column_name], errors="coerce")
        valid = self.frequency.notna() & values.notna()
        if not valid.any():
            return

        nearest_index = (self.frequency.loc[valid] - float(frequency)).abs().idxmin()
        amplitude = float(values.loc[nearest_index])
        axes.scatter([frequency], [amplitude], color=color, edgecolors="black", zorder=6)
        axes.annotate(
            f"local valley\nf={self._format_value(frequency)}\ndelta S11={self._format_value(depth)}",
            xy=(frequency, amplitude),
            xytext=(6, -32),
            textcoords="offset points",
            fontsize=8,
            color=color,
            bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": color, "alpha": 0.75},
        )

    def _annotate_symmetric_peak(self, curve_index: int, row: pd.Series, color: str, axes) -> None:
        frequency = row.get(SYMMETRIC_MIDDLE_PEAK_FREQ_COLUMN)
        delta = row.get(SYMMETRIC_MIDDLE_PEAK_DELTA_COLUMN)
        if pd.isna(frequency) or pd.isna(delta) or self.input_data is None or self.frequency is None:
            return

        column_name = self.curve_columns[curve_index]
        values = pd.to_numeric(self.input_data[column_name], errors="coerce")
        valid = self.frequency.notna() & values.notna()
        if not valid.any():
            return

        nearest_index = (self.frequency.loc[valid] - float(frequency)).abs().idxmin()
        amplitude = float(values.loc[nearest_index])
        axes.scatter([frequency], [amplitude], marker="^", color=color, edgecolors="black", zorder=7)
        axes.annotate(
            f"symmetric peak\nf={self._format_value(frequency)}\ndelta S11={self._format_value(delta)}",
            xy=(frequency, amplitude),
            xytext=(8, 18),
            textcoords="offset points",
            fontsize=8,
            color=color,
            bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": color, "alpha": 0.75},
        )

    def _on_curve_selection_changed(self, _event: tk.Event) -> None:
        if self.plot_scope.get() == "selected":
            self._refresh_plot()

    def _on_show_feature_points_changed(self) -> None:
        self._refresh_plot()
        self._refresh_selected_curve_plot_from_table()

    def _select_all_curves(self) -> None:
        self.curve_list.selection_set(0, tk.END)
        self.plot_scope.set("selected")
        self._refresh_plot()

    def _clear_curve_selection(self) -> None:
        self.curve_list.selection_clear(0, tk.END)
        self.plot_scope.set("selected")
        self._refresh_plot()

    def _select_single_curve(self) -> None:
        active = self.curve_list.index(tk.ACTIVE) if self.curve_columns else 0
        self.curve_list.selection_clear(0, tk.END)
        if self.curve_columns:
            self.curve_list.selection_set(active)
            self.curve_list.activate(active)
        self.plot_scope.set("selected")
        self._refresh_plot()

    def _refresh_selected_curve_plot_from_table(self) -> None:
        selected = self.table.selection()
        if selected:
            self._show_selected_curve_plot(self.table.index(selected[0]))

    def _current_columns(self) -> list[str]:
        if self.detection_mode.get() == "double":
            columns = ["Cr", "Cs", "ks", "f_res_1", "S11_min_1", "f_res_2", "S11_min_2"]
            if self.extract_local_valley.get():
                columns.extend(["local_valley_freq", LOCAL_VALLEY_COLUMN])
            if self.extract_symmetric_peak.get():
                columns.extend(
                    [
                        SYMMETRIC_FREQ_DIFF_COLUMN,
                        SYMMETRIC_MIDDLE_PEAK_FREQ_COLUMN,
                        SYMMETRIC_MIDDLE_PEAK_DELTA_COLUMN,
                    ]
                )
            return columns
        return ["Cr", "Cs", "ks", "f_res", "S11_min"]

    def _set_table_columns(self, columns: list[str]) -> None:
        self.table.configure(columns=columns)
        width = 130 if len(columns) > 4 else 150
        for column in columns:
            self.table.heading(column, text=column)
            self.table.column(column, anchor="center", width=width, stretch=True)

    def _default_output_name(self, input_file: Path) -> str:
        suffix = "double_resonance_features" if self.detection_mode.get() == "double" else "resonance_features"
        return f"{input_file.stem}_{suffix}.csv"

    @staticmethod
    def _format_value(value: object) -> str:
        if pd.isna(value):
            return "NaN"
        if isinstance(value, float):
            return f"{value:.10g}"
        return str(value)


def main() -> None:
    app = ResonanceFeatureApp()
    app.mainloop()


if __name__ == "__main__":
    main()
