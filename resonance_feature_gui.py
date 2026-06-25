"""Tkinter GUI for S11 resonance feature extraction."""

from __future__ import annotations

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
        self._select_curve_for_result_row(row_index)
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
        self._refresh_selected_curve_plot_from_table()

    def _on_show_feature_points_changed(self) -> None:
        self._refresh_plot()
        self._refresh_selected_curve_plot_from_table()

    def _select_all_curves(self) -> None:
        self.curve_list.selection_set(0, tk.END)
        self.plot_scope.set("selected")
        self._refresh_plot()
        self._refresh_selected_curve_plot_from_table()

    def _clear_curve_selection(self) -> None:
        self.curve_list.selection_clear(0, tk.END)
        self.plot_scope.set("selected")
        self._refresh_plot()
        self._refresh_selected_curve_plot_from_table()

    def _select_single_curve(self) -> None:
        active = self.curve_list.index(tk.ACTIVE) if self.curve_columns else 0
        self.curve_list.selection_clear(0, tk.END)
        if self.curve_columns:
            self.curve_list.selection_set(active)
            self.curve_list.activate(active)
        self.plot_scope.set("selected")
        self._refresh_plot()
        self._refresh_selected_curve_plot_from_table()

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
