"""Tkinter GUI for S11 resonance feature extraction."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from resonance_features import extract_double_resonance_features, extract_resonance_features


class ResonanceFeatureApp(tk.Tk):
    """Small desktop interface for selecting input CSV and saving output CSV."""

    def __init__(self) -> None:
        super().__init__()
        self.title("S11 Resonance Feature Extractor")
        self.geometry("820x520")
        self.minsize(720, 460)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.detection_mode = tk.StringVar(value="single")
        self.status_text = tk.StringVar(value="Select a wide-format S11 CSV file.")
        self.result: pd.DataFrame | None = None

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

        actions = ttk.Frame(controls)
        actions.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Run Extraction", command=self._run_extraction).pack(side="left")
        ttk.Button(actions, text="Export Result", command=self._export_result).pack(side="left", padx=(8, 0))
        ttk.Label(actions, textvariable=self.status_text).pack(side="left", padx=(16, 0))

        table_frame = ttk.Frame(self, padding=(12, 0, 12, 12))
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.table = ttk.Treeview(table_frame, show="headings")
        self._set_table_columns(self._current_columns())

        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.table.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

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
            if self.detection_mode.get() == "double":
                self.result = extract_double_resonance_features(self.input_path.get())
            else:
                self.result = extract_resonance_features(self.input_path.get())
        except Exception as exc:
            self.result = None
            self._clear_table()
            self.status_text.set("Extraction failed.")
            messagebox.showerror("Extraction failed", str(exc))
            return

        self._show_result(self.result)
        mode_label = "double-peak" if self.detection_mode.get() == "double" else "single-peak"
        self.status_text.set(f"Extracted {len(self.result)} S11 curves in {mode_label} mode.")

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
        for row in result.itertuples(index=False, name=None):
            self.table.insert("", "end", values=[self._format_value(value) for value in row])

    def _clear_table(self) -> None:
        for item in self.table.get_children():
            self.table.delete(item)

    def _on_mode_changed(self) -> None:
        self.result = None
        self._clear_table()
        self._set_table_columns(self._current_columns())
        if self.input_path.get():
            input_file = Path(self.input_path.get())
            self.output_path.set(str(input_file.with_name(self._default_output_name(input_file))))
        self.status_text.set("Mode changed. Run extraction again.")

    def _current_columns(self) -> list[str]:
        if self.detection_mode.get() == "double":
            return ["Cr", "Cs", "ks", "f_res_1", "S11_min_1", "f_res_2", "S11_min_2"]
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
