#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pdfocr —— 用本地 RapidOCR 离线识别「扫描版 PDF / 图片」，输出文本或 Markdown。

完全离线、免费、无需 API Key。

用法示例：
  pdfocr 扫描件.pdf                     # 结果打印到屏幕
  pdfocr 扫描件.pdf -o 结果.md           # 写文件（.md 结尾自动用 Markdown 格式）
  pdfocr 扫描件.pdf --dpi 300           # 提高渲染分辨率（更准更慢，默认 200）
  pdfocr 扫描件.pdf --start 1 --end 3   # 只处理第 1~3 页
  pdfocr 扫描件.pdf --force-ocr         # 即使有文本层也强制走 OCR
  pdfocr 扫描件.pdf --text-only         # 只要 PDF 自带文本层，不做 OCR
  pdfocr 照片.jpg                       # 图片直接识别

依赖（已装在 eml2md\\.venv 里）：pymupdf、rapidocr-onnxruntime
"""
import argparse
import sys
import time
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


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


def main():
    ap = argparse.ArgumentParser(
        prog="pdfocr",
        description="本地 RapidOCR 离线识别扫描版 PDF / 图片（输出文本或 Markdown）")
    ap.add_argument("path", help="PDF 或图片文件路径")
    ap.add_argument("-o", "--output", help="输出文件；不填则打印到屏幕（.md 结尾自动用 Markdown）")
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

    fmt = "md" if (args.output and args.output.lower().endswith(".md")) else "text"
    is_pdf = path.suffix.lower() == ".pdf"
    if not is_pdf and path.suffix.lower() not in IMAGE_EXTS:
        print(f"[ERROR] 不支持的文件类型: {path.suffix}（支持 .pdf 与 {', '.join(sorted(IMAGE_EXTS))}）",
              file=sys.stderr)
        return 1

    try:
        engine = build_engine()
    except ImportError:
        print("[ERROR] 未安装 RapidOCR。请执行: pip install rapidocr-onnxruntime pymupdf",
              file=sys.stderr)
        return 1

    if is_pdf:
        text = process_pdf(path, args, engine, fmt)
    else:
        if args.start or args.end:
            print("[WARN] 图片模式忽略 --start/--end", file=sys.stderr)
        text = process_image(path, engine)

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
