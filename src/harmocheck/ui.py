"""Windows desktop interface for HarmoCheck."""

from __future__ import annotations

import math
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict

import numpy as np
import pandas as pd

from .core import AnalysisResult, DEFAULT_TEA, TEaThreshold, analyze_workbook, display_coverage, display_table


class HarmoCheckApp(tk.Tk):
    """Green-themed Tkinter application for routine EQA harmonization assessment."""

    GREEN = "#0C5B38"
    GREEN_BRIGHT = "#118A54"
    INK = "#1B2A20"
    MUTED = "#5C6D62"
    CARD = "#FFFFFF"
    BACKGROUND = "#F4F8F5"

    def __init__(self) -> None:
        super().__init__()
        self.title("HarmoCheck | KEQAS Harmonization")
        self.geometry("1280x820")
        self.minsize(1060, 690)
        self.configure(background=self.BACKGROUND)
        self.tea_map: Dict[str, TEaThreshold] = dict(DEFAULT_TEA)
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar(value=str(Path.home() / "Documents" / "HarmoCheck Results"))
        self.status = tk.StringVar(value="분석할 EQA raw data 파일을 선택하세요.")
        self._result: AnalysisResult | None = None
        self._configure_style()
        self._build_ui()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=self.BACKGROUND)
        style.configure("Card.TFrame", background=self.CARD)
        style.configure("Header.TFrame", background=self.GREEN)
        style.configure("TLabel", background=self.BACKGROUND, foreground=self.INK, font=("Malgun Gothic", 10))
        style.configure("Card.TLabel", background=self.CARD, foreground=self.INK, font=("Malgun Gothic", 10))
        style.configure("Header.TLabel", background=self.GREEN, foreground="white", font=("Malgun Gothic", 10))
        style.configure("Title.TLabel", background=self.GREEN, foreground="white", font=("Malgun Gothic", 24, "bold"))
        style.configure("Subtitle.TLabel", background=self.GREEN, foreground="#D9F2E3", font=("Malgun Gothic", 10))
        style.configure("Section.TLabel", background=self.CARD, foreground=self.GREEN, font=("Malgun Gothic", 12, "bold"))
        style.configure("Metric.TLabel", background=self.CARD, foreground=self.GREEN, font=("Malgun Gothic", 20, "bold"))
        style.configure("Muted.TLabel", background=self.CARD, foreground=self.MUTED, font=("Malgun Gothic", 9))
        style.configure("TButton", font=("Malgun Gothic", 10), padding=(12, 7), background="#DCEBE1", foreground=self.INK, borderwidth=0)
        style.map("TButton", background=[("active", "#C5E1CF")])
        style.configure("Accent.TButton", background=self.GREEN_BRIGHT, foreground="white", font=("Malgun Gothic", 11, "bold"), padding=(16, 9))
        style.map("Accent.TButton", background=[("active", self.GREEN)], foreground=[("disabled", "#D6E7DB")])
        style.configure("Treeview", background="white", fieldbackground="white", foreground=self.INK, rowheight=28, font=("Malgun Gothic", 9))
        style.configure("Treeview.Heading", background=self.GREEN, foreground="white", font=("Malgun Gothic", 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", "#D7F0E1")], foreground=[("selected", self.INK)])
        style.configure("TNotebook", background=self.BACKGROUND, borderwidth=0)
        style.configure("TNotebook.Tab", background="#DDEBE1", foreground=self.INK, padding=(16, 9), font=("Malgun Gothic", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", self.GREEN)], foreground=[("selected", "white")])

    def _build_ui(self) -> None:
        header = ttk.Frame(self, style="Header.TFrame", padding=(30, 20))
        header.pack(fill="x")
        ttk.Label(header, text="HarmoCheck", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="KEQAS EQA raw data 기반 반기별 Harmonization 평가", style="Subtitle.TLabel").pack(anchor="w", pady=(4, 0))

        content = ttk.Frame(self, padding=(26, 18))
        content.pack(fill="both", expand=True)
        source_card = ttk.Frame(content, style="Card.TFrame", padding=18)
        source_card.pack(fill="x")
        ttk.Label(source_card, text="분석 설정", style="Section.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(source_card, text="EQA raw data (.xlsx)", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(15, 0))
        ttk.Entry(source_card, textvariable=self.input_path, width=85).grid(row=1, column=1, sticky="ew", padx=(12, 8), pady=(15, 0))
        ttk.Button(source_card, text="파일 선택", command=self._pick_input).grid(row=1, column=2, pady=(15, 0))
        ttk.Label(source_card, text="결과 폴더", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(source_card, textvariable=self.output_path, width=85).grid(row=2, column=1, sticky="ew", padx=(12, 8), pady=(10, 0))
        ttk.Button(source_card, text="폴더 선택", command=self._pick_output).grid(row=2, column=2, pady=(10, 0))
        ttk.Button(source_card, text="TEa 기준 설정", command=self._open_tea_editor).grid(row=3, column=2, sticky="e", pady=(12, 0))
        self.run_button = ttk.Button(source_card, text="Harmonization 분석 시작", style="Accent.TButton", command=self._run_analysis)
        self.run_button.grid(row=1, column=3, rowspan=2, sticky="nsew", padx=(18, 0), pady=(15, 0))
        source_card.columnconfigure(1, weight=1)

        status_card = ttk.Frame(content, style="Card.TFrame", padding=(18, 12))
        status_card.pack(fill="x", pady=(14, 0))
        self.progress = ttk.Progressbar(status_card, mode="indeterminate", length=150)
        self.progress.pack(side="right")
        ttk.Label(status_card, textvariable=self.status, style="Card.TLabel").pack(side="left")

        metrics = ttk.Frame(content)
        metrics.pack(fill="x", pady=(14, 0))
        self.metric_values: dict[str, tk.StringVar] = {key: tk.StringVar(value="—") for key in ("periods", "raw", "retained", "analytes")}
        for index, (key, caption) in enumerate((("periods", "평가 반기"), ("raw", "원시 결과"), ("retained", "필터 후 결과"), ("analytes", "평가 항목"))):
            card = ttk.Frame(metrics, style="Card.TFrame", padding=(18, 13))
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 10, 0))
            ttk.Label(card, textvariable=self.metric_values[key], style="Metric.TLabel").pack(anchor="w")
            ttk.Label(card, text=caption, style="Muted.TLabel").pack(anchor="w")
            metrics.columnconfigure(index, weight=1)

        notebook = ttk.Notebook(content)
        notebook.pack(fill="both", expand=True, pady=(16, 0))
        self.summary_tree = self._add_table_tab(notebook, "Survey validation")
        self.subpeer_tree = self._add_table_tab(notebook, "Sub-peer group level")
        self.peer_tree = self._add_table_tab(notebook, "Peer group level")
        self.analyte_tree = self._add_table_tab(notebook, "Analyte level")

    def _add_table_tab(self, notebook: ttk.Notebook, title: str) -> ttk.Treeview:
        frame = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        notebook.add(frame, text=title)
        tree = ttk.Treeview(frame, show="headings")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.tag_configure("optimal", background="#DCF3E5")
        tree.tag_configure("desirable", background="#EEF8D8")
        tree.tag_configure("minimum", background="#FFF3CC")
        tree.tag_configure("not_acceptable", background="#FBE2E2")
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    def _pick_input(self) -> None:
        path = filedialog.askopenfilename(title="KEQAS EQA raw data 선택", filetypes=[("Excel workbook", "*.xlsx")])
        if path:
            self.input_path.set(path)

    def _pick_output(self) -> None:
        path = filedialog.askdirectory(title="결과 폴더 선택")
        if path:
            self.output_path.set(path)

    def _run_analysis(self) -> None:
        source = Path(self.input_path.get().strip())
        destination = Path(self.output_path.get().strip())
        if not source.is_file():
            messagebox.showerror("파일 확인", "분석할 .xlsx 파일을 선택하세요.")
            return
        if not str(destination):
            messagebox.showerror("폴더 확인", "결과를 저장할 폴더를 선택하세요.")
            return
        self.run_button.configure(state="disabled")
        self.progress.start(12)
        self.status.set("Raw data를 확인하고 Year-Survey별 Harmonization을 계산하고 있습니다…")
        self._clear_tables()

        def work() -> None:
            try:
                result = analyze_workbook(source, destination, tea_map=self.tea_map)
                self.after(0, lambda: self._show_result(result))
            except Exception as exc:
                self.after(0, lambda: self._show_error(str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _show_result(self, result: AnalysisResult) -> None:
        self._result = result
        self.progress.stop()
        self.run_button.configure(state="normal")
        self.metric_values["periods"].set(str(len(result.periods)))
        self.metric_values["raw"].set(f"{result.raw_rows:,}")
        self.metric_values["retained"].set(f"{result.retained_rows:,}")
        self.metric_values["analytes"].set(str(result.analyte["analyte"].nunique()))
        self._fill_tree(self.summary_tree, display_coverage(result.coverage))
        self._fill_tree(self.subpeer_tree, display_table(result.subpeer, "subpeer"))
        self._fill_tree(self.peer_tree, display_table(result.peer, "peer"))
        self._fill_tree(self.analyte_tree, display_table(result.analyte, "analyte"))
        self.status.set(f"완료: {', '.join(result.periods)} | PDF, Excel 표, 추세 그래프가 저장되었습니다. 결과 폴더: {result.pdf_path.parent}")
        messagebox.showinfo("분석 완료", f"Year-Survey별 Harmonization 평가가 완료되었습니다.\n\nPDF: {result.pdf_path}\nExcel: {result.tables_path}\nCharts: {result.charts_dir}")

    def _show_error(self, detail: str) -> None:
        self.progress.stop()
        self.run_button.configure(state="normal")
        self.status.set("분석을 완료하지 못했습니다. 파일 형식과 PT 물질 코드를 확인하세요.")
        messagebox.showerror("분석 오류", detail)

    def _clear_tables(self) -> None:
        for tree in (self.summary_tree, self.subpeer_tree, self.peer_tree, self.analyte_tree):
            tree.delete(*tree.get_children())
            tree["columns"] = ()

    def _fill_tree(self, tree: ttk.Treeview, frame: pd.DataFrame) -> None:
        display = frame.copy().head(1000)
        columns = list(display.columns)
        tree["columns"] = columns
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=min(260, max(110, len(column) * 10)), anchor="w")
        for _, row in display.iterrows():
            values = []
            for column in columns:
                value = row[column]
                values.append(f"{float(value):.3f}" if isinstance(value, (float, np.floating)) and not math.isnan(value) else str(value))
            level = str(row.get("Harmonization Level", "")).lower().replace(" ", "_")
            tree.insert("", "end", values=values, tags=(level,))

    def _open_tea_editor(self) -> None:
        window = tk.Toplevel(self)
        window.title("TEa 기준 설정")
        window.transient(self)
        window.grab_set()
        window.configure(background=self.BACKGROUND)
        container = ttk.Frame(window, style="Card.TFrame", padding=20)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="TEa 기준 설정 (%)", style="Section.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(container, text="분석 항목", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(14, 4))
        for column, label in enumerate(("Optimal", "Desirable", "Minimum"), start=1):
            ttk.Label(container, text=label, style="Card.TLabel").grid(row=1, column=column, padx=5, pady=(14, 4))
        rows: list[tuple[tk.Entry, tk.Entry, tk.Entry, tk.Entry]] = []

        def add_row(name: str = "", threshold: TEaThreshold | None = None) -> None:
            row = len(rows) + 2
            name_entry = ttk.Entry(container, width=24)
            name_entry.insert(0, name)
            name_entry.grid(row=row, column=0, padx=(0, 5), pady=3)
            entries = [ttk.Entry(container, width=12) for _ in range(3)]
            if threshold:
                for entry, value in zip(entries, (threshold.optimal, threshold.desirable, threshold.minimum)):
                    entry.insert(0, str(value))
            for column, entry in enumerate(entries, start=1):
                entry.grid(row=row, column=column, padx=5, pady=3)
            rows.append((name_entry, *entries))

        for name, threshold in self.tea_map.items():
            add_row(name, threshold)
        ttk.Button(container, text="항목 추가", command=lambda: add_row()).grid(row=30, column=0, sticky="w", pady=(16, 0))

        def apply() -> None:
            updated: Dict[str, TEaThreshold] = {}
            try:
                for name_entry, optimal, desirable, minimum in rows:
                    name = name_entry.get().strip()
                    if name:
                        values = tuple(float(entry.get().strip()) for entry in (optimal, desirable, minimum))
                        if not 0 <= values[0] <= values[1] <= values[2]:
                            raise ValueError(f"{name}: Optimal <= Desirable <= Minimum 순서로 입력하세요.")
                        updated[name] = TEaThreshold(*values)
            except ValueError as exc:
                messagebox.showerror("TEa 기준", str(exc), parent=window)
                return
            self.tea_map = updated
            window.destroy()

        ttk.Button(container, text="적용", style="Accent.TButton", command=apply).grid(row=30, column=3, sticky="e", pady=(16, 0))


def main() -> None:
    HarmoCheckApp().mainloop()
