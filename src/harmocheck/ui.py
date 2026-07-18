"""Windows desktop interface for HarmoCheck."""

from __future__ import annotations

import math
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict

import numpy as np
import pandas as pd
from PIL import Image, ImageTk

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
        self._year_bars: dict[str, ttk.Frame] = {}
        self._tree_year_positions: dict[str, dict[str, tuple[int, str]]] = {}
        self._trend_images: list[ImageTk.PhotoImage] = []
        self._trend_anchors: dict[str, ttk.Widget] = {}
        self._trend_buttons: dict[str, ttk.Button] = {}
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
        # A selected row must remain clearly distinct from the pale green
        # "Optimal" category rows.
        style.map("Treeview", background=[("selected", "#82C39A")], foreground=[("selected", self.INK)])
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

        self.notebook = ttk.Notebook(content)
        self.notebook.pack(fill="both", expand=True, pady=(16, 0))
        self.summary_tree = self._add_table_tab(self.notebook, "Survey validation")
        self.subpeer_tree = self._add_table_tab(self.notebook, "Sub-peer group level")
        self.peer_tree = self._add_table_tab(self.notebook, "Peer group level")
        self.analyte_tree = self._add_table_tab(self.notebook, "Analyte level")
        self._add_trend_tab(self.notebook)

    def _add_table_tab(self, notebook: ttk.Notebook, title: str) -> ttk.Treeview:
        frame = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        notebook.add(frame, text=title)
        year_bar = ttk.Frame(frame, style="Card.TFrame")
        year_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        tree = ttk.Treeview(frame, show="headings")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.tag_configure("optimal", background="#DCF3E5")
        tree.tag_configure("desirable", background="#EEF8D8")
        tree.tag_configure("minimum", background="#FFF3CC")
        tree.tag_configure("not_acceptable", background="#FBE2E2")
        tree.grid(row=1, column=0, sticky="nsew")
        vertical.grid(row=1, column=1, sticky="ns")
        horizontal.grid(row=2, column=0, sticky="ew")
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        self._year_bars[str(tree)] = year_bar
        self._tree_year_positions[str(tree)] = {}
        return tree

    def _add_trend_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        notebook.add(frame, text="Harmonization trend")
        button_bar = ttk.Frame(frame, style="Card.TFrame")
        button_bar.pack(fill="x", pady=(0, 8))
        for metric, caption in (("bias", "Bias trend"), ("cv", "CV trend"), ("tae", "TAE trend")):
            button = ttk.Button(button_bar, text=caption, command=lambda key=metric: self._scroll_to_trend(key), state="disabled")
            button.pack(side="left", padx=(0, 8))
            self._trend_buttons[metric] = button

        self._trend_canvas = tk.Canvas(frame, background=self.CARD, highlightthickness=0, borderwidth=0)
        trend_scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self._trend_canvas.yview)
        self._trend_canvas.configure(yscrollcommand=trend_scrollbar.set)
        trend_scrollbar.pack(side="right", fill="y")
        self._trend_canvas.pack(side="left", fill="both", expand=True)
        self._trend_frame = ttk.Frame(self._trend_canvas, style="Card.TFrame", padding=(12, 6, 12, 20))
        self._trend_window = self._trend_canvas.create_window((0, 0), window=self._trend_frame, anchor="nw")
        self._trend_frame.bind("<Configure>", self._refresh_trend_scrollregion)
        self._trend_canvas.bind("<Configure>", self._resize_trend_frame)
        # Mouse-wheel events are delivered to chart labels as well as the
        # canvas itself, so bind at the application level and scroll only
        # while the pointer is over the trend viewport.
        self.bind_all("<MouseWheel>", self._on_trend_mousewheel, add="+")
        self.bind_all("<Button-4>", self._on_trend_mousewheel, add="+")
        self.bind_all("<Button-5>", self._on_trend_mousewheel, add="+")
        self._clear_trends()

    def _refresh_trend_scrollregion(self, _event: tk.Event | None = None) -> None:
        self._trend_canvas.configure(scrollregion=self._trend_canvas.bbox("all"))

    def _resize_trend_frame(self, event: tk.Event) -> None:
        self._trend_canvas.itemconfigure(self._trend_window, width=event.width)

    def _pointer_is_over_trend_canvas(self) -> bool:
        pointer_x, pointer_y = self.winfo_pointerx(), self.winfo_pointery()
        left, top = self._trend_canvas.winfo_rootx(), self._trend_canvas.winfo_rooty()
        return left <= pointer_x < left + self._trend_canvas.winfo_width() and top <= pointer_y < top + self._trend_canvas.winfo_height()

    def _on_trend_mousewheel(self, event: tk.Event) -> str | None:
        if not self._pointer_is_over_trend_canvas():
            return None
        delta = getattr(event, "delta", 0)
        if delta:
            steps = max(1, abs(int(delta / 120)))
            self._scroll_trend_by_pixels(-steps if delta > 0 else steps)
        elif getattr(event, "num", None) == 4:
            self._scroll_trend_by_pixels(-1)
        elif getattr(event, "num", None) == 5:
            self._scroll_trend_by_pixels(1)
        return "break"

    def _scroll_trend_by_pixels(self, direction: int) -> None:
        """Scroll the graph canvas by a reliable fixed pixel distance."""

        bounds = self._trend_canvas.bbox("all")
        if bounds is None:
            return
        _left, top, _right, bottom = bounds
        content_height = max(1, bottom - top)
        viewport_height = self._trend_canvas.winfo_height()
        current_top = self._trend_canvas.canvasy(0)
        target_top = max(top, min(bottom - viewport_height, current_top + direction * 72))
        self._trend_canvas.yview_moveto((target_top - top) / content_height)

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
        self.status.set("Raw data를 확인하고 Year-Survey별 Harmonization을 계산하고 있습니다.")
        self._clear_tables()
        self._clear_trends()

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
        tables = (
            (self.summary_tree, display_coverage(result.coverage)),
            (self.subpeer_tree, display_table(result.subpeer, "subpeer")),
            (self.peer_tree, display_table(result.peer, "peer")),
            (self.analyte_tree, display_table(result.analyte, "analyte")),
        )
        for tree, table in tables:
            self._fill_tree(tree, table)
            self._set_year_navigation(tree, result.years)
        self._populate_trends(result)
        self.status.set(
            f"완료: {', '.join(result.periods)} | PDF, Excel 표, 추세 그래프가 저장되었습니다. 결과 폴더: {result.pdf_path.parent}"
        )
        messagebox.showinfo(
            "분석 완료",
            f"Year-Survey별 Harmonization 평가가 완료되었습니다.\n\nPDF: {result.pdf_path}\nExcel: {result.tables_path}\nCharts: {result.charts_dir}",
        )

    def _show_error(self, detail: str) -> None:
        self.progress.stop()
        self.run_button.configure(state="normal")
        self.status.set("분석을 완료하지 못했습니다. 파일 형식과 PT 물질 코드를 확인하세요.")
        messagebox.showerror("분석 오류", detail)

    def _clear_tables(self) -> None:
        for tree in (self.summary_tree, self.subpeer_tree, self.peer_tree, self.analyte_tree):
            tree.delete(*tree.get_children())
            tree["columns"] = ()
            self._tree_year_positions[str(tree)] = {}
            for child in self._year_bars[str(tree)].winfo_children():
                child.destroy()

    def _fill_tree(self, tree: ttk.Treeview, frame: pd.DataFrame) -> None:
        display = frame.copy()
        columns = list(display.columns)
        tree["columns"] = columns
        positions: dict[str, tuple[int, str]] = {}
        for column in columns:
            tree.heading(column, text=column)
            width = 145 if column in {"Pooled Bias (%)", "Pooled CV (%)", "TAE (%)"} else min(260, max(110, len(column) * 10))
            tree.column(column, width=width, anchor="w")
        for row_index, (_, row) in enumerate(display.iterrows()):
            values = []
            for column in columns:
                value = row[column]
                values.append(f"{float(value):.3f}" if isinstance(value, (float, np.floating)) and not math.isnan(value) else str(value))
            level = str(row.get("Harmonization Level", "")).lower().replace(" ", "_")
            item = tree.insert("", "end", values=values, tags=(level,))
            period = str(row.get("Year-Survey", ""))
            match = re.match(r"^(\d{4})", period)
            if match:
                positions.setdefault(match.group(1), (row_index, item))
        self._tree_year_positions[str(tree)] = positions

    def _set_year_navigation(self, tree: ttk.Treeview, years: tuple[int, ...]) -> None:
        bar = self._year_bars[str(tree)]
        for child in bar.winfo_children():
            child.destroy()
        positions = self._tree_year_positions[str(tree)]
        for year in years:
            label = str(year)
            button = ttk.Button(bar, text=f"{label}년", command=lambda value=label, target=tree: self._scroll_tree_to_year(target, value))
            if label not in positions:
                button.configure(state="disabled")
            button.pack(side="left", padx=(0, 8))

    def _scroll_tree_to_year(self, tree: ttk.Treeview, year: str) -> None:
        position = self._tree_year_positions[str(tree)].get(year)
        if position is None:
            return
        row_index, item = position
        count = max(1, len(tree.get_children()))
        tree.yview_moveto(row_index / count)
        tree.selection_set(item)
        tree.focus(item)

    def _clear_trends(self) -> None:
        for child in self._trend_frame.winfo_children():
            child.destroy()
        self._trend_images.clear()
        self._trend_anchors.clear()
        for button in self._trend_buttons.values():
            button.configure(state="disabled")
        ttk.Label(
            self._trend_frame,
            text="분석을 완료하면 Bias, CV, TAE 추세 그래프가 이곳에 표시됩니다.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(8, 0))
        self._trend_canvas.yview_moveto(0)

    def _populate_trends(self, result: AnalysisResult) -> None:
        for child in self._trend_frame.winfo_children():
            child.destroy()
        self._trend_images.clear()
        self._trend_anchors.clear()
        names = {"bias": "Bias trend", "cv": "CV trend", "tae": "TAE trend"}
        resample = getattr(Image, "Resampling", Image).LANCZOS
        for metric in ("bias", "cv", "tae"):
            section = ttk.Label(self._trend_frame, text=names[metric], style="Section.TLabel")
            section.pack(anchor="w", pady=(8 if metric == "bias" else 24, 8))
            self._trend_anchors[metric] = section
            chart_paths = result.chart_paths.get(metric, ())
            if not chart_paths:
                ttk.Label(self._trend_frame, text="표시할 추세 그래프가 없습니다.", style="Muted.TLabel").pack(anchor="w")
                continue
            for chart_path in chart_paths:
                try:
                    with Image.open(chart_path) as source:
                        image = source.convert("RGB")
                    image.thumbnail((1040, 680), resample)
                    photo = ImageTk.PhotoImage(image)
                    self._trend_images.append(photo)
                    tk.Label(self._trend_frame, image=photo, background=self.CARD, borderwidth=0).pack(anchor="w", pady=(0, 14))
                except Exception as exc:
                    ttk.Label(self._trend_frame, text=f"그래프를 표시할 수 없습니다: {chart_path.name} ({exc})", style="Muted.TLabel").pack(anchor="w")
        for metric, button in self._trend_buttons.items():
            button.configure(state="normal" if metric in self._trend_anchors else "disabled")
        self.update_idletasks()
        self._refresh_trend_scrollregion()
        self._trend_canvas.yview_moveto(0)

    def _scroll_to_trend(self, metric: str) -> None:
        anchor = self._trend_anchors.get(metric)
        if anchor is None:
            return
        self.update_idletasks()
        # Canvas fractions use the entire scrollable content height.  Using
        # only the remaining scroll distance overshoots CV/TAE and hides each
        # section title above the visible area.
        content_height = max(1, self._trend_frame.winfo_height())
        self._trend_canvas.yview_moveto(min(1.0, anchor.winfo_y() / content_height))

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
