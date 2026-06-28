import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from merge_wide_tables import (
    DIFF_OUTPUT_DIR_NAME,
    MERGE_RULE_KEEP_FIRST_X,
    MERGE_RULES,
    OUTPUT_DIR_NAME,
    SUPPORTED_EXTS,
    batch_diff_reader_sensor_by_cr,
    discover_input_files,
    discover_table_files,
    merge_tables,
    natural_key,
    write_outputs,
)


SCRIPT_DIR = Path(__file__).resolve().parent
FILE_TYPES = [
    ("Supported tables", "*.csv *.tsv *.txt *.xlsx *.xlsm *.xls"),
    ("CSV/TXT/TSV", "*.csv *.txt *.tsv"),
    ("Excel", "*.xlsx *.xlsm *.xls"),
    ("All files", "*.*"),
]


class MergeWideTablesApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Wide 表格处理工具")
        self.geometry("960x700")
        self.minsize(820, 600)

        self.merge_files = []
        self.merge_output_dir = tk.StringVar(value=str(SCRIPT_DIR / OUTPUT_DIR_NAME))
        self.rule_label_to_id = {label: rule_id for rule_id, label in MERGE_RULES.items()}
        self.merge_rule = tk.StringVar(value=MERGE_RULES[MERGE_RULE_KEEP_FIRST_X])
        self.smart_sort = tk.BooleanVar(value=True)
        self.merge_status = tk.StringVar(value="请选择输入文件或文件夹。第一行文件会作为第一张表。")

        self.reader_path = tk.StringVar()
        self.sensor_files = []
        self.diff_output_dir = tk.StringVar(value=str(SCRIPT_DIR / DIFF_OUTPUT_DIR_NAME))
        self.diff_status = tk.StringVar(value="请选择 Reader 背景表和 Reader+Sensor 表。")

        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(self)
        notebook.grid(row=0, column=0, sticky="nsew")

        merge_tab = ttk.Frame(notebook)
        diff_tab = ttk.Frame(notebook)
        notebook.add(merge_tab, text="合并多列")
        notebook.add(diff_tab, text="按相同 Cr 做 Reader 背景差分")

        self._build_merge_tab(merge_tab)
        self._build_diff_tab(diff_tab)

    def _build_merge_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        top = ttk.Frame(parent, padding=(16, 14, 16, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="合并规则").grid(row=0, column=0, sticky="w", padx=(0, 8))
        rule_box = ttk.Combobox(
            top,
            textvariable=self.merge_rule,
            values=list(self.rule_label_to_id.keys()),
            state="readonly",
            width=42,
        )
        rule_box.grid(row=0, column=1, sticky="w")

        ttk.Checkbutton(top, text="根据首行参数智能排列数据列", variable=self.smart_sort).grid(
            row=1, column=1, sticky="w", pady=(10, 0)
        )

        body = ttk.Frame(parent, padding=(16, 8, 16, 8))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(body)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(toolbar, text="选择文件", command=self.add_merge_files).pack(side="left")
        ttk.Button(toolbar, text="选择文件夹", command=self.choose_merge_folder).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="上移", command=lambda: self.move_merge_selected(-1)).pack(side="left", padx=(18, 0))
        ttk.Button(toolbar, text="下移", command=lambda: self.move_merge_selected(1)).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="移除", command=self.remove_merge_selected).pack(side="left", padx=(18, 0))
        ttk.Button(toolbar, text="清空", command=self.clear_merge_files).pack(side="left", padx=(8, 0))

        self.merge_tree = self._make_tree(body)
        self.merge_tree.grid(row=1, column=0, sticky="nsew")
        scroll_y = ttk.Scrollbar(body, orient="vertical", command=self.merge_tree.yview)
        scroll_y.grid(row=1, column=1, sticky="ns")
        self.merge_tree.configure(yscrollcommand=scroll_y.set)

        output = ttk.Frame(parent, padding=(16, 8, 16, 8))
        output.grid(row=2, column=0, sticky="ew")
        output.columnconfigure(1, weight=1)
        ttk.Label(output, text="输出目录").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(output, textvariable=self.merge_output_dir).grid(row=0, column=1, sticky="ew")
        ttk.Button(output, text="浏览", command=self.choose_merge_output_dir).grid(row=0, column=2, padx=(8, 0))

        bottom = ttk.Frame(parent, padding=(16, 8, 16, 16))
        bottom.grid(row=3, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.merge_status).grid(row=0, column=0, sticky="w")
        self.merge_run_button = ttk.Button(bottom, text="开始合并", command=self.start_merge)
        self.merge_run_button.grid(row=0, column=1, sticky="e")

        self.merge_log = self._make_log(parent)
        self.merge_log.grid(row=4, column=0, sticky="nsew", padx=16, pady=(0, 16))

    def _build_diff_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        reader = ttk.Frame(parent, padding=(16, 14, 16, 8))
        reader.grid(row=0, column=0, sticky="ew")
        reader.columnconfigure(1, weight=1)
        ttk.Label(reader, text="Reader 背景表").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(reader, textvariable=self.reader_path).grid(row=0, column=1, sticky="ew")
        ttk.Button(reader, text="选择", command=self.choose_reader_file).grid(row=0, column=2, padx=(8, 0))

        toolbar = ttk.Frame(parent, padding=(16, 8, 16, 8))
        toolbar.grid(row=1, column=0, sticky="ew")
        ttk.Button(toolbar, text="选择 Reader+Sensor 文件", command=self.add_sensor_files).pack(side="left")
        ttk.Button(toolbar, text="选择 Reader+Sensor 文件夹", command=self.choose_sensor_folder).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="移除", command=self.remove_sensor_selected).pack(side="left", padx=(18, 0))
        ttk.Button(toolbar, text="清空", command=self.clear_sensor_files).pack(side="left", padx=(8, 0))

        table_frame = ttk.Frame(parent, padding=(16, 0, 16, 8))
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.sensor_tree = self._make_tree(table_frame)
        self.sensor_tree.grid(row=0, column=0, sticky="nsew")
        scroll_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.sensor_tree.yview)
        scroll_y.grid(row=0, column=1, sticky="ns")
        self.sensor_tree.configure(yscrollcommand=scroll_y.set)

        output = ttk.Frame(parent, padding=(16, 8, 16, 8))
        output.grid(row=3, column=0, sticky="ew")
        output.columnconfigure(1, weight=1)
        ttk.Label(output, text="输出目录").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(output, textvariable=self.diff_output_dir).grid(row=0, column=1, sticky="ew")
        ttk.Button(output, text="浏览", command=self.choose_diff_output_dir).grid(row=0, column=2, padx=(8, 0))

        bottom = ttk.Frame(parent, padding=(16, 8, 16, 16))
        bottom.grid(row=4, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.diff_status).grid(row=0, column=0, sticky="w")
        self.diff_run_button = ttk.Button(bottom, text="执行差分", command=self.start_diff)
        self.diff_run_button.grid(row=0, column=1, sticky="e")

        self.diff_log = self._make_log(parent)
        self.diff_log.grid(row=5, column=0, sticky="nsew", padx=16, pady=(0, 16))

    def _make_tree(self, parent):
        columns = ("index", "name", "folder")
        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="extended")
        tree.heading("index", text="顺序")
        tree.heading("name", text="文件名")
        tree.heading("folder", text="路径")
        tree.column("index", width=54, anchor="center", stretch=False)
        tree.column("name", width=300, anchor="w")
        tree.column("folder", width=520, anchor="w")
        return tree

    def _make_log(self, parent):
        log = tk.Text(parent, height=8, wrap="word")
        return log

    def add_merge_files(self):
        selected = filedialog.askopenfilenames(title="选择要合并的表格", filetypes=FILE_TYPES)
        self._add_paths(self.merge_files, selected)
        self.refresh_merge_tree()

    def choose_merge_folder(self):
        folder = filedialog.askdirectory(title="选择包含表格的文件夹")
        if folder:
            self.merge_files = discover_table_files(folder)
            self.refresh_merge_tree()

    def choose_merge_output_dir(self):
        folder = filedialog.askdirectory(title="选择输出目录", initialdir=self.merge_output_dir.get())
        if folder:
            self.merge_output_dir.set(folder)

    def _add_paths(self, target, paths):
        existing = {path.resolve() for path in target}
        for item in paths:
            path = Path(item).resolve()
            if path.exists() and path.suffix.lower() in SUPPORTED_EXTS and path not in existing:
                target.append(path)
                existing.add(path)

    def refresh_merge_tree(self):
        self._refresh_tree(self.merge_tree, self.merge_files, first_label="第一张")
        self.merge_status.set(f"已选择 {len(self.merge_files)} 个文件。第一张表决定 X轴/Frequency。")

    def _refresh_tree(self, tree, files, first_label=None):
        tree.delete(*tree.get_children())
        for index, path in enumerate(files, start=1):
            label = first_label if first_label and index == 1 else str(index)
            tree.insert("", "end", iid=str(index - 1), values=(label, path.name, str(path.parent)))

    def move_merge_selected(self, direction):
        indices = sorted(int(item) for item in self.merge_tree.selection())
        if not indices:
            return
        iterator = indices if direction < 0 else reversed(indices)
        for index in iterator:
            new_index = index + direction
            if 0 <= new_index < len(self.merge_files):
                self.merge_files[index], self.merge_files[new_index] = self.merge_files[new_index], self.merge_files[index]
        new_selection = [str(i + direction) for i in indices if 0 <= i + direction < len(self.merge_files)]
        self.refresh_merge_tree()
        for item in new_selection:
            self.merge_tree.selection_add(item)

    def remove_merge_selected(self):
        for index in sorted((int(item) for item in self.merge_tree.selection()), reverse=True):
            del self.merge_files[index]
        self.refresh_merge_tree()

    def clear_merge_files(self):
        self.merge_files = []
        self.refresh_merge_tree()

    def start_merge(self):
        if self.rule_label_to_id.get(self.merge_rule.get()) != MERGE_RULE_KEEP_FIRST_X:
            messagebox.showerror("不支持的规则", "当前版本只实现了第一个合并规则。")
            return
        if len(self.merge_files) < 2:
            messagebox.showwarning("文件不足", "请至少选择 2 个表格文件。")
            return

        output_dir = Path(self.merge_output_dir.get()).expanduser()
        self.merge_run_button.configure(state="disabled")
        self.merge_status.set("正在合并，请稍等...")
        self.merge_log.delete("1.0", "end")
        threading.Thread(target=self.merge_worker, args=(list(self.merge_files), output_dir), daemon=True).start()

    def merge_worker(self, files, output_dir):
        try:
            merged, warnings = merge_tables(files, smart_sort=self.smart_sort.get())
            csv_path, xlsx_path, xlsx_error = write_outputs(merged, output_dir)
            lines = [f"完成：{merged.shape[0]} 行 x {merged.shape[1]} 列", f"CSV : {csv_path}"]
            lines.append(f"XLSX: {xlsx_path}" if xlsx_path else f"XLSX 输出失败：{xlsx_error}")
            if warnings:
                lines.extend(["", "注意："])
                lines.extend(f"- {warning}" for warning in warnings)
            self.after(0, self.merge_done, "\n".join(lines), True)
        except Exception as exc:
            self.after(0, self.merge_done, f"错误：{exc}", False)

    def merge_done(self, text, ok):
        self.merge_log.insert("1.0", text)
        self.merge_status.set("合并完成。" if ok else "合并失败。")
        self.merge_run_button.configure(state="normal")
        messagebox.showinfo("完成", "合并完成，结果已输出。") if ok else messagebox.showerror("失败", text)

    def choose_reader_file(self):
        selected = filedialog.askopenfilename(title="选择 Reader 背景表", filetypes=FILE_TYPES)
        if selected:
            self.reader_path.set(selected)

    def add_sensor_files(self):
        selected = filedialog.askopenfilenames(title="选择 Reader+Sensor 表", filetypes=FILE_TYPES)
        self._add_paths(self.sensor_files, selected)
        self.refresh_sensor_tree()

    def choose_sensor_folder(self):
        folder = filedialog.askdirectory(title="选择 Reader+Sensor 表所在文件夹")
        if folder:
            self.sensor_files = discover_table_files(folder)
            self.refresh_sensor_tree()

    def choose_diff_output_dir(self):
        folder = filedialog.askdirectory(title="选择输出目录", initialdir=self.diff_output_dir.get())
        if folder:
            self.diff_output_dir.set(folder)

    def refresh_sensor_tree(self):
        self._refresh_tree(self.sensor_tree, self.sensor_files)
        self.diff_status.set(f"已选择 {len(self.sensor_files)} 个 Reader+Sensor 文件。")

    def remove_sensor_selected(self):
        for index in sorted((int(item) for item in self.sensor_tree.selection()), reverse=True):
            del self.sensor_files[index]
        self.refresh_sensor_tree()

    def clear_sensor_files(self):
        self.sensor_files = []
        self.refresh_sensor_tree()

    def start_diff(self):
        reader = Path(self.reader_path.get()).expanduser()
        if not reader.exists():
            messagebox.showwarning("缺少 Reader 背景表", "请先选择 Reader / Background 表。")
            return
        if not self.sensor_files:
            messagebox.showwarning("缺少 Reader+Sensor 表", "请至少选择 1 个 Reader+Sensor 表。")
            return

        output_dir = Path(self.diff_output_dir.get()).expanduser()
        self.diff_run_button.configure(state="disabled")
        self.diff_status.set("正在执行 Reader+Sensor - Reader 差分...")
        self.diff_log.delete("1.0", "end")
        threading.Thread(
            target=self.diff_worker,
            args=(reader, list(self.sensor_files), output_dir),
            daemon=True,
        ).start()

    def diff_worker(self, reader, sensor_files, output_dir):
        try:
            results = batch_diff_reader_sensor_by_cr(reader, sensor_files, output_dir)
            lines = [f"Reader 背景文件: {reader}", f"Reader+Sensor 文件数量: {len(sensor_files)}"]
            for info in results:
                lines.extend(
                    [
                        "",
                        f"Reader+Sensor: {info['reader_sensor_file']}",
                        f"匹配到 Cr 列数: {info['output_diff_columns']}",
                        f"输出差分列数: {info['output_diff_columns']}",
                        f"CSV : {info['csv_path']}",
                        f"Origin TXT: {info['origin_path']}",
                        f"XLSX: {info['xlsx_path'] if info['xlsx_path'] else 'Excel 输出失败: ' + str(info['xlsx_error'])}",
                        f"Report: {info['report_path']}",
                    ]
                )
            self.after(0, self.diff_done, "\n".join(lines), True)
        except Exception as exc:
            self.after(0, self.diff_done, f"错误：{exc}", False)

    def diff_done(self, text, ok):
        self.diff_log.insert("1.0", text)
        self.diff_status.set("差分完成。" if ok else "差分失败。")
        self.diff_run_button.configure(state="normal")
        messagebox.showinfo("完成", "差分完成，结果已输出。") if ok else messagebox.showerror("失败", text)


if __name__ == "__main__":
    app = MergeWideTablesApp()
    if not discover_input_files(SCRIPT_DIR):
        app.merge_status.set("请选择输入文件或文件夹。第一行文件会作为第一张表。")
    app.mainloop()
