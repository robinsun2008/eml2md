# -*- coding: utf-8 -*-
"""gui_app.py — eml2md V4 图形界面（tkinter，免命令行操作）。

标签一【单文件转换】: 拖入或浏览选择一个文件 → 自动识别类型 → 调用
  对应引擎转换 → 弹出另存为对话框选择保存位置。
标签二【目录批量转换】: 指定输入目录 → 递归检索全部可转换文件 →
  按所选输出模式逐个转换，进度条显示进度/开始时间/预计剩余时间。
支持拖放（tkinterdnd2，缺失时自动降级为浏览选择，不影响其他功能）。
"""
import queue
import sys
import threading
import time
import traceback
from pathlib import Path

# 源码直接运行时补齐模块搜索路径（pdfocr.py 在上一级目录）；打包后无需处理
if not getattr(sys, "frozen", False):
    _HERE = Path(__file__).resolve().parent
    for _p in (str(_HERE), str(_HERE.parent)):
        if _p not in sys.path:
            sys.path.insert(0, _p)

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from router import Router, classify

try:
    from tkinterdnd2 import TkinterDnD
    _ROOT = TkinterDnD.Tk          # 支持拖放
    _DND = True
except Exception:
    _ROOT = tk.Tk                  # 降级：无拖放
    _DND = False

AV_MSG = "音视频文件无需转换，将自动跳过"


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.worker = None
        self.router = None

        root.title("eml2md 转换工具 V4 —— 邮件 / 文档 / 扫描件 → Markdown（离线）")
        root.geometry("760x560")
        root.minsize(680, 480)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.tab_file = ttk.Frame(nb)
        self.tab_dir = ttk.Frame(nb)
        nb.add(self.tab_file, text=" 单文件转换 ")
        nb.add(self.tab_dir, text=" 目录批量转换 ")
        self.nb = nb

        self._build_file_tab()
        self._build_dir_tab()
        self._build_log()
        root.after(100, self._poll)

    # ── 标签一：单文件 ──────────────────────────────────────────
    def _build_file_tab(self):
        f = self.tab_file
        pad = {"padx": 10, "pady": 6}

        ttk.Label(f, text="① 选择或拖入一个文件：").grid(row=0, column=0, sticky="w", **pad)
        self.file_var = tk.StringVar()
        ent = ttk.Entry(f, textvariable=self.file_var)
        ent.grid(row=1, column=0, sticky="ew", **pad)
        ttk.Button(f, text="浏览…", command=self._pick_file).grid(row=1, column=1, **pad)

        self.kind_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.kind_var, foreground="#06c").grid(
            row=2, column=0, sticky="w", **pad)
        ttk.Label(f, text="识别引擎：邮件(.eml/.msg)→eml2md｜扫描件/图片→pdfocr｜"
                          "其他文档→markitdown｜音视频→跳过",
                  foreground="#888").grid(row=3, column=0, columnspan=2, sticky="w", **pad)

        ttk.Button(f, text="② 转换并另存为…", command=self._convert_one).grid(
            row=4, column=0, columnspan=2, pady=14)
        self.btn_convert = f.winfo_children()[-1]

        f.columnconfigure(0, weight=1)

        if _DND:
            ent.drop_target_register("*")
            ent.dnd_bind("<<Drop>>", self._on_drop_file)
            tip = ttk.Label(f, text="（支持把文件直接拖到上面的输入框）", foreground="#888")
            tip.grid(row=5, column=0, sticky="w", **pad)

    def _on_drop_file(self, event):
        p = event.data.strip("{}")
        if p:
            self.file_var.set(p)
            self._show_kind()

    def _pick_file(self):
        p = filedialog.askopenfilename(title="选择要转换的文件")
        if p:
            self.file_var.set(p)
            self._show_kind()

    def _show_kind(self):
        p = Path(self.file_var.get()) if self.file_var.get() else None
        if p and p.exists():
            kind = classify(p)
            names = {"mail": "邮件 → eml2md 引擎", "ocr": "扫描件/图片 → pdfocr 引擎",
                     "ebook": "电子书 → 电子书引擎（插图不提取）",
                     "markitdown": "普通文档 → markitdown 引擎",
                     "skip": "音视频 → 跳过", "already_md": "已是 Markdown 文件"}
            self.kind_var.set(f"类型识别：{names.get(kind, kind)}")
        else:
            self.kind_var.set("")

    def _convert_one(self):
        p = self.file_var.get().strip()
        if not p:
            messagebox.showinfo("提示", "请先选择或拖入一个文件")
            return
        src = Path(p)
        if not src.exists():
            messagebox.showerror("错误", f"文件不存在：\n{p}")
            return
        kind = classify(src)
        if kind in ("skip", "already_md"):
            messagebox.showinfo("跳过", "音视频文件无需转换；.md 文件无需再转换。")
            return

        target = filedialog.asksaveasfilename(
            title="转换结果另存为", defaultextension=".md",
            initialfile=src.stem + ".md",
            filetypes=[("Markdown", "*.md"), ("所有文件", "*.*")])
        if not target:
            return
        self.btn_convert.config(state="disabled")

        def work():
            try:
                r = Router(log=self.log)
                kind, text = r.convert_text(src)
                Path(target).write_text(text, encoding="utf-8", newline="\n")
                self.q.put(("done_one", f"转换成功（{kind}）→ {target}"))
                if not self.keep_var.get():
                    try:
                        src.unlink()
                        self.q.put(("log", "源文件已删除"))
                    except Exception as exc:
                        self.q.put(("log", f"[WARN] 源文件删除失败: {exc}"))
            except Exception as exc:
                self.q.put(("error", f"转换失败：{type(exc).__name__}: {exc}"))
            finally:
                self.q.put(("enable", None))

        threading.Thread(target=work, daemon=True).start()

    # ── 标签二：目录批量 ────────────────────────────────────────
    def _build_dir_tab(self):
        f = self.tab_dir
        pad = {"padx": 10, "pady": 5}

        ttk.Label(f, text="输入目录（含子目录）：").grid(row=0, column=0, sticky="w", **pad)
        row1 = ttk.Frame(f); row1.grid(row=1, column=0, columnspan=3, sticky="ew", **pad)
        self.dir_var = tk.StringVar()
        e = ttk.Entry(row1, textvariable=self.dir_var)
        e.pack(side="left", fill="x", expand=True)
        ttk.Button(row1, text="浏览…", command=self._pick_dir).pack(side="left", padx=4)
        if _DND:
            e.drop_target_register("*")
            e.dnd_bind("<<Drop>>", self._on_drop_dir)

        ttk.Label(f, text="输出方式：").grid(row=2, column=0, sticky="w", **pad)
        self.mode_var = tk.StringVar(value="same")
        ttk.Radiobutton(f, text="MD 保留在源文件同一目录（子目录结构不变）",
                        variable=self.mode_var, value="same").grid(
            row=3, column=0, columnspan=3, sticky="w", **pad)
        ttk.Radiobutton(f, text="全部集中到指定输出目录（不分子目录，重名覆盖）",
                        variable=self.mode_var, value="flat").grid(
            row=4, column=0, columnspan=3, sticky="w", **pad)
        row2 = ttk.Frame(f); row2.grid(row=5, column=0, columnspan=3, sticky="ew", **pad)
        self.out_var = tk.StringVar()
        self._out_entry = ttk.Entry(row2, textvariable=self.out_var, state="disabled")
        self._out_entry.pack(side="left", fill="x", expand=True)
        self.btn_out = ttk.Button(row2, text="浏览…", command=self._pick_out,
                                  state="disabled")
        self.btn_out.pack(side="left", padx=4)
        self.mode_var.trace_add("write", self._toggle_out)

        self.keep_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="保留源文件（取消勾选 = 转换成功后自动删除源文件）",
                        variable=self.keep_var).grid(row=6, column=0,
                                                     columnspan=3, sticky="w", **pad)

        self.btn_start = ttk.Button(f, text="开始转换", command=self._start_dir)
        self.btn_start.grid(row=7, column=0, sticky="w", **pad)
        self.btn_stop = ttk.Button(f, text="停止", command=self._stop, state="disabled")
        self.btn_stop.grid(row=7, column=1, sticky="w", **pad)

        self.progress = ttk.Progressbar(f, maximum=100)
        self.progress.grid(row=8, column=0, columnspan=3, sticky="ew", **pad)
        self.stat_var = tk.StringVar(value="等待开始…")
        ttk.Label(f, textvariable=self.stat_var).grid(row=9, column=0,
                                                      columnspan=3, sticky="w", **pad)

        f.columnconfigure(0, weight=1)

    def _on_drop_dir(self, event):
        p = event.data.strip("{}")
        if p:
            self.dir_var.set(p)

    def _pick_dir(self):
        d = filedialog.askdirectory(title="选择输入目录")
        if d:
            self.dir_var.set(d)

    def _pick_out(self):
        d = filedialog.askdirectory(title="选择 MD 统一输出目录")
        if d:
            self.out_var.set(d)

    def _toggle_out(self, *args):
        if self.mode_var.get() == "flat":
            self._out_entry.config(state="normal")
            self.btn_out.config(state="normal")
        else:
            self._out_entry.config(state="disabled")
            self.btn_out.config(state="disabled")

    def _start_dir(self):
        src = self.dir_var.get().strip()
        if not src or not Path(src).exists():
            messagebox.showinfo("提示", "请先选择有效的输入目录")
            return
        mode = self.mode_var.get()
        out_dir = None
        if mode == "flat":
            out_dir = self.out_var.get().strip()
            if not out_dir:
                messagebox.showinfo("提示", "请选择统一输出目录")
                return
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.progress["value"] = 0
        t0 = time.strftime("%H:%M:%S")
        self.stat_var.set(f"开始时间 {t0}，正在扫描目录…")
        self.log_clear()
        self.log(f"输入目录: {src}")
        if mode == "flat":
            self.log(f"输出目录: {out_dir}")

        keep = self.keep_var.get()
        stop_flag = {"stop": False}

        def work():
            try:
                r = Router(log=self.log)
                files = r.scan_dir(Path(src))
                if mode == "flat":
                    Path(out_dir).mkdir(parents=True, exist_ok=True)
                total = len(files)
                self.q.put(("scan", (total, t0)))
                ok = fail = skip = 0
                start_t = time.time()
                for i, fpath in enumerate(files, 1):
                    if stop_flag["stop"]:
                        self.q.put(("log", "—— 已手动停止 ——"))
                        break
                    st, out, msg = r.convert(fpath, mode, out_dir, keep)
                    if st == "ok":
                        ok += 1
                        self.q.put(("log", f"[{i}/{total}] ✓ {fpath.name}"))
                    elif st == "skip":
                        skip += 1
                    else:
                        fail += 1
                        self.q.put(("log", f"[{i}/{total}] ✗ {fpath.name} → {msg}"))
                    elapsed = time.time() - start_t
                    done_n = i
                    eta = elapsed / done_n * (total - done_n) if done_n else 0
                    self.q.put(("progress", (i * 100 // total, elapsed, eta, ok, fail, skip)))
                self.q.put(("finished", (ok, fail, skip)))
            except Exception as exc:
                self.q.put(("error", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"))

        self._stop_flag = stop_flag
        threading.Thread(target=work, daemon=True).start()

    def _stop(self):
        if hasattr(self, "_stop_flag"):
            self._stop_flag["stop"] = True
        self.btn_stop.config(state="disabled")

    # ── 日志区 ──────────────────────────────────────────────────
    def _build_log(self):
        lf = ttk.LabelFrame(self.root, text="转换日志")
        lf.pack(fill="both", padx=8, pady=(0, 8))
        self.txt = tk.Text(lf, height=8, state="disabled", font=("Consolas", 9))
        sb = ttk.Scrollbar(lf, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(fill="both", expand=True)

    def log(self, msg):
        self.q.put(("log", msg))

    def log_clear(self):
        self.q.put(("clear", None))

    def _append_log(self, msg):
        self.txt.config(state="normal")
        self.txt.insert("end", msg + "\n")
        self.txt.see("end")
        self.txt.config(state="disabled")

    # ── 队列轮询（线程→UI）─────────────────────────────────────
    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "clear":
                    self.txt.config(state="normal")
                    self.txt.delete("1.0", "end")
                    self.txt.config(state="disabled")
                elif kind == "scan":
                    total, t0 = payload
                    self.stat_var.set(f"开始时间 {t0} ｜ 共找到 {total} 个可转换文件")
                elif kind == "progress":
                    pct, elapsed, eta, ok, fail, skip = payload
                    self.progress["value"] = pct
                    self.stat_var.set(
                        f"进度 {pct}% ｜ 已用 {int(elapsed)}s ｜ 预计还需 {int(eta)}s ｜ "
                        f"成功 {ok} 失败 {fail} 跳过 {skip}")
                elif kind == "finished":
                    ok, fail, skip = payload
                    self.stat_var.set(f"完成：成功 {ok}，失败 {fail}，跳过 {skip}")
                    self.btn_start.config(state="normal")
                    self.btn_stop.config(state="disabled")
                elif kind == "done_one":
                    self._append_log(str(payload))
                    messagebox.showinfo("完成", str(payload))
                elif kind == "enable":
                    self.btn_convert.config(state="normal")
                elif kind == "error":
                    self._append_log(f"[ERROR] {payload}")
                    messagebox.showerror("错误", str(payload))
                    self.btn_start.config(state="normal")
                    self.btn_stop.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(120, self._poll)


def main():
    root = _ROOT()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    sys.exit(main())
