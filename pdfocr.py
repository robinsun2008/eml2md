#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pdfocr —— 本地离线识别「扫描版 PDF / 图片」，输出文本或 Markdown。

两个引擎（--engine 选择）:
  rapiddoc : 版面分析 + OCR + **表格识别**（RapidDoc 管线）。
             扫描件里的表格能还原成 Markdown 表格 —— 慢一些但内容完整。
  rapidocr : 逐页 OCR，只出文字（快）。表格会被打散成零散文本行。

  auto（默认）: 整份 PDF 是文本型 → 直接取文本层（最快）；
                只要含扫描页 → 走 rapiddoc（表格/版面完整）。
                未安装 rapiddoc 时自动退回 rapidocr。

完全离线、免费、无需 API Key。

用法示例：
  pdfocr 扫描件.pdf                     # 结果打印到屏幕（auto 引擎）
  pdfocr 扫描件.pdf -o 结果.md           # 写文件（.md 结尾自动用 Markdown 格式）
  pdfocr 扫描件.pdf --engine rapidocr    # 强制轻量引擎（快，无表格）
  pdfocr 扫描件.pdf --engine rapiddoc    # 强制表格引擎
  pdfocr 扫描件.pdf --no-table           # 表格引擎但关闭表格识别
  pdfocr 扫描件.pdf --keep-html          # 表格保留 HTML（合并单元格信息最全）
  pdfocr 扫描件.pdf --dpi 300           # 提高渲染分辨率（更准更慢，默认 200）
  pdfocr 扫描件.pdf --start 1 --end 3   # 只处理第 1~3 页
  pdfocr 扫描件.pdf --force-ocr         # 即使有文本层也强制走 OCR
  pdfocr 扫描件.pdf --text-only         # 只要 PDF 自带文本层，不做 OCR
  pdfocr 照片.jpg                       # 图片直接识别

依赖：pymupdf、rapidocr-onnxruntime、rapid-doc（表格引擎）
"""
import argparse
import sys
from pathlib import Path

# 控制台编码：Windows 中文环境下重定向到文件/管道时，默认 GBK 会把 ✓ / ✗ / → 写崩
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 源码直接运行时补齐模块搜索路径（doc2md.py 在 eml2md/ 下，本文件在其上一级）；打包后无需处理
if not getattr(sys, "frozen", False):
    _HERE = Path(__file__).resolve().parent
    for _p in (str(_HERE), str(_HERE / "eml2md")):
        if Path(_p).is_dir() and _p not in sys.path:
            sys.path.insert(0, _p)

import time  # noqa: E402

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

ENGINES = ("auto", "rapiddoc", "rapidocr")


# ── 轻量引擎（RapidOCR）────────────────────────────────────────
def build_engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def ocr_image(engine, data):
    """data: 图片路径(str) 或 bytes"""
    res, _ = engine(data)
    if not res:
        return ""
    out = []
    for item in res:
        txt = item[1] if len(item) > 1 else ""
        if txt:
            out.append(txt.strip())
    return "\n".join(out)


def render_pdf_page(doc, index, dpi):
    """把第 index 页(0-based)渲染成 PNG bytes"""
    page = doc.load_page(index)
    pix = page.get_pixmap(dpi=dpi)
    return pix.tobytes("png")


def process_pdf(path, args, engine, fmt):
    """轻量引擎：逐页 OCR / 取文本层。"""
    import pymupdf

    doc = pymupdf.open(str(path))
    total = doc.page_count
    start = max(1, args.start or 1)
    end = min(total, args.end or total)
    chunks = []
    n_ocr = n_text = 0

    for i in range(start - 1, end):
        page = doc.load_page(i)
        native = page.get_text("text") or ""
        use_ocr = args.force_ocr or (len(native.strip()) < args.min_chars and not args.text_only)
        if args.text_only:
            use_ocr = False

        t0 = time.time()
        if use_ocr:
            png = render_pdf_page(doc, i, args.dpi)
            text = ocr_image(engine, png)
            mode = f"OCR @{args.dpi}dpi"
            n_ocr += 1
        else:
            text = native.strip()
            mode = "文本层"
            n_text += 1
        dt = time.time() - t0
        print(f"  [第 {i+1}/{total} 页] {mode} → {len(text)} 字符 ({dt:.1f}s)",
              file=sys.stderr, flush=True)

        if fmt == "md":
            chunks.append(f"## 第 {i+1} 页\n\n{text}")
        else:
            chunks.append(text)

    doc.close()
    print(f"完成：{end-start+1} 页（OCR {n_ocr} 页 / 文本层 {n_text} 页）",
          file=sys.stderr, flush=True)
    return "\n\n".join(chunks)


def process_image(path, engine):
    t0 = time.time()
    text = ocr_image(engine, str(path))
    print(f"  图片识别 → {len(text)} 字符 ({time.time()-t0:.1f}s)", file=sys.stderr, flush=True)
    return text


# ── 表格引擎（RapidDoc）───────────────────────────────────────
def doc2md_available() -> bool:
    try:
        import doc2md  # noqa: F401
        return doc2md.rapiddoc_available()
    except Exception:
        return False


def _pages_with_text(path, min_chars: int) -> tuple[int, int]:
    """返回 (有文本层的页数, 总页数)。"""
    import pymupdf
    doc = pymupdf.open(str(path))
    try:
        total = doc.page_count
        n = sum(1 for p in doc if len((p.get_text("text") or "").strip()) >= min_chars)
    finally:
        doc.close()
    return n, total


def _should_use_table_engine(path, args) -> bool:
    """auto 判定：文本型 PDF 走文本层；含扫描页则交给表格引擎。"""
    if args.text_only:
        return False
    if args.force_ocr:
        return True
    n_text, total = _pages_with_text(path, max(1, args.min_chars))
    return total > 0 and (n_text / total) < 0.9


def process_pdf_tables(path, args, fmt):
    """表格引擎：RapidDoc 管线（版面 + 表格 + OCR）。"""
    import doc2md

    mode = resolve_table_mode(args)
    t0 = time.time()
    print(f"  引擎: RapidDoc（表格模式 {mode}），首次运行需加载模型…",
          file=sys.stderr, flush=True)
    text = doc2md.convert_pdf(
        path,
        table_mode=mode,
        page_markers=not args.no_page_marks,
    )
    print(f"完成：{len(text)} 字符（{time.time()-t0:.1f}s）", file=sys.stderr, flush=True)
    if fmt == "text":
        # 纯文本模式：去掉分页标记与 Markdown 装饰
        import re
        text = re.sub(r"<!--[^>]*-->", "", text)
        text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
        text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def resolve_table_mode(args) -> str:
    """解析表格模式：md（默认）/ html / text / off。"""
    if getattr(args, "no_table", False):
        return "off"
    if getattr(args, "keep_html", False):
        return "html"
    return getattr(args, "table_mode", "md")


# ── 统一分派 ───────────────────────────────────────────────────
def convert_pdf_dispatch(path, args, fmt, engine_factory=None) -> str:
    """按 --engine 选择引擎处理 PDF。

    engine_factory: 返回轻量 OCR 引擎的可调用对象（便于批量转换时复用引擎）。
    """
    build = engine_factory or build_engine
    if args.engine == "rapiddoc" or (args.engine == "auto" and _should_use_table_engine(path, args)):
        if doc2md_available():
            return process_pdf_tables(path, args, fmt)
        print("[WARN] 未安装 rapid-doc，退回轻量引擎（无表格识别）", file=sys.stderr, flush=True)
    engine = build()
    return process_pdf(path, args, engine, fmt)


def main():
    ap = argparse.ArgumentParser(
        prog="pdfocr",
        description="本地离线识别扫描版 PDF / 图片（支持表格识别）")
    ap.add_argument("path", help="PDF 或图片文件路径")
    ap.add_argument("-o", "--output", help="输出文件；不填则打印到屏幕（.md 结尾自动用 Markdown）")
    ap.add_argument("--engine", choices=ENGINES, default="auto",
                    help="auto（默认）: 文本型取文本层、扫描件走表格引擎；"
                         "rapiddoc: 强制表格引擎；rapidocr: 强制轻量引擎")
    ap.add_argument("--table-mode", choices=("md", "html", "text", "off"), default="md",
                    help="表格输出：md（默认，Markdown 表格）｜html（保留 HTML）｜"
                         "text（纯文本行）｜off（关闭表格模型，最快但表格内容会丢）")
    ap.add_argument("--no-table", action="store_true",
                    help="等价于 --table-mode off（快，但表格区域内容会丢失，不推荐）")
    ap.add_argument("--keep-html", action="store_true",
                    help="等价于 --table-mode html（表格保留 HTML，信息最全）")
    ap.add_argument("--no-page-marks", action="store_true", help="不输出 <!-- 第 N 页 --> 标记")
    ap.add_argument("--dpi", type=int, default=200, help="PDF 渲染 DPI（默认 200，越高越准越慢）")
    ap.add_argument("--start", type=int, default=None, help="起始页（1 起，默认第 1 页）")
    ap.add_argument("--end", type=int, default=None, help="结束页（含，默认最后一页）")
    ap.add_argument("--min-chars", type=int, default=20,
                    help="页内可提取文本少于该值才走 OCR（默认 20）")
    ap.add_argument("--force-ocr", action="store_true", help="强制对每页做 OCR")
    ap.add_argument("--text-only", action="store_true", help="只提取 PDF 文本层，不做 OCR")
    args = ap.parse_args()

    path = Path(args.path).expanduser()
    if not path.exists():
        print(f"[ERROR] 文件不存在: {path}", file=sys.stderr)
        return 1

    is_pdf = path.suffix.lower() == ".pdf"
    if not is_pdf and path.suffix.lower() not in IMAGE_EXTS:
        print(f"[ERROR] 不支持的文件类型: {path.suffix}（支持 .pdf 与 {', '.join(sorted(IMAGE_EXTS))}）",
              file=sys.stderr)
        return 1

    fmt = "md" if (args.output and args.output.lower().endswith(".md")) else "text"

    try:
        if is_pdf:
            text = convert_pdf_dispatch(path, args, fmt)
        else:
            if args.start or args.end:
                print("[WARN] 图片模式忽略 --start/--end", file=sys.stderr)
            engine = build_engine()
            text = process_image(path, engine)
    except ImportError as exc:
        print(f"[ERROR] 依赖缺失: {exc}\n请执行: pip install rapidocr-onnxruntime pymupdf",
              file=sys.stderr)
        return 1

    if args.output:
        out = Path(args.output).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"已写入: {out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
