#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc2md —— 扫描版 PDF → Markdown（版面还原 + **表格识别**），完全离线。

与 pdfocr 的区别:
  * pdfocr  : 逐页 OCR，只输出文字（快，但表格会被打散成零散文本行）
  * doc2md  : RapidDoc 管线（版面分析 PP-DocLayout + RapidOCR + RapidTable
              表格结构识别），能把表格还原成 Markdown 表格 / HTML 表格

离线说明（关键）:
  模型不随 pip 包分发，默认会联网从 ModelScope 下载。
  本工具通过环境变量 RAPID_MODELS_DIR 指向随包携带的 models 目录，
  模型已存在时不会联网。模型清单（约 163MB，关闭公式识别时）:
    pp_doclayoutv3.onnx(124MB) / q_cls.onnx / unet.onnx /
    slanet-plus.onnx / paddle_cls.onnx / ch_ppocr_mobile_v2.0_cls_mobile.onnx
  OCR 的 det/rec 模型已内置在 rapid_doc 包内，无需下载。

用法示例:
  doc2md 扫描件.pdf                       # 输出到屏幕
  doc2md 扫描件.pdf -o 结果.md             # 写文件
  doc2md D:\\扫描件 -o D:\\MD -r            # 目录批量（含子目录）
  doc2md 扫描件.pdf --no-table            # 关闭表格识别（更快，纯文字）
  doc2md 扫描件.pdf --keep-html           # 表格保留 HTML 形式（信息最全）
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import time
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
PDF_EXTS = {".pdf"}

# ── 模型目录（离线核心）──────────────────────────────────────────


def _app_dir() -> Path:
    """打包后返回 exe 所在目录；源码运行返回项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _models_candidates() -> list[Path]:
    here = _app_dir()
    cands = [
        here / "models",                 # 交付包布局: eml2md/models/
        here / "models_v8",              # 开发期
        here / "packaging" / "models_v8",
        here.parent / "models",
        here.parent / "packaging" / "models_v8",
    ]
    return cands


def find_models_dir() -> Path | None:
    """定位随包携带的模型目录；找不到返回 None（会退化为联网下载）。"""
    env = os.environ.get("RAPID_MODELS_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    for c in _models_candidates():
        if c.is_dir() and any(c.glob("*.onnx")):
            return c
    return None


def setup_models_env(verbose: bool = False) -> Path | None:
    """把 RAPID_MODELS_DIR 指向本地模型目录（必须在 import rapid_doc 之前调用）。"""
    d = find_models_dir()
    if d is not None:
        os.environ["RAPID_MODELS_DIR"] = str(d)
        os.environ.setdefault("MINERU_DEVICE_MODE", "cpu")
        # 语言检测（fast_langdetect）缓存目录：优先用随包携带的 lid.176.ftz，
        # 避免默认回退到临时目录后联网下载。
        if (d / "lid.176.ftz").is_file():
            os.environ.setdefault("FTLANG_CACHE", str(d))
        if verbose:
            print(f"[i] 模型目录: {d}", file=sys.stderr, flush=True)
    elif verbose:
        print("[!] 未找到本地模型目录，将尝试联网下载模型（离线环境会失败）",
              file=sys.stderr, flush=True)
    return d


def _ensure_streams() -> None:
    """GUI（windowed）模式下 sys.stdout/stderr 可能为 None，库写入时会崩。

    同时把输出流转为 UTF-8：Windows 中文环境下若是重定向到文件/管道，
    默认 GBK 编码遇到 ✓ / ✗ 这类字符会抛 UnicodeEncodeError。
    （真实控制台走 WindowsConsoleIO，不受影响。）
    """
    for name in ("stdout", "stderr"):
        s = getattr(sys, name, None)
        if s is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except Exception:
                pass
            continue
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_ensure_streams()


def _quiet_logs() -> None:
    """压掉 rapid_doc 的 loguru INFO 噪音。"""
    try:
        from loguru import logger
        logger.remove()
    except Exception:
        pass


# ── 表格：HTML → Markdown（合并单元格自动回退 HTML）────────────
_TABLE_BLOCK_RE = re.compile(r"<table\b.*?</table>", re.I | re.S)
_SPAN_RE = re.compile(r'(?:row|col)span\s*=\s*["\']?\s*(\d+)', re.I)


def has_merged_cells(html: str) -> bool:
    """是否含跨行/跨列合并单元格（Markdown 表格无法表达）。"""
    return any(int(m) > 1 for m in _SPAN_RE.findall(html or ""))


def table_html_to_markdown(html: str, keep_html: bool = False) -> str:
    """单个 <table> → Markdown 表格；合并单元格或无 markdownify 时保留 HTML。"""
    if keep_html or not html:
        return html
    if has_merged_cells(html):
        return html  # 合并单元格：Markdown 无法表达，保留 HTML 以不丢信息
    try:
        from markdownify import markdownify as _md
    except ImportError:
        return html
    try:
        out = _md(html, heading_style="ATX", table_infer_header=True).strip()
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out or html
    except Exception:
        return html


_ROW_RE = re.compile(r"<tr\b.*?</tr>", re.I | re.S)
_CELL_RE = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def table_html_to_text(html: str) -> str:
    """表格 → 纯文本行（保留内容、不留表格结构）。

    用于「不要 Markdown 表格但也不想丢内容」的场景：
    每行单元格用 " | " 连接，单元格内换行压平。
    """
    rows = []
    for row in _ROW_RE.findall(html or ""):
        cells = [_TAG_RE.sub("", c) for c in _CELL_RE.findall(row)]
        cells = [re.sub(r"\s+", " ", c).strip() for c in cells]
        if any(cells):
            rows.append(" | ".join(cells).strip(" |"))
    return "\n".join(rows)


TABLE_MODES = ("md", "html", "text", "off")


def convert_tables(text: str, mode: str = "md") -> str:
    """按模式转换文本里的 HTML 表格。

    mode: md=Markdown 表格（合并单元格回退 HTML）／html=保留 HTML／
          text=纯文本行（保留内容无结构）／off=不处理
    """
    if not text or mode == "off" or "<table" not in text.lower():
        return text
    if mode == "html":
        return text
    fn = table_html_to_text if mode == "text" else table_html_to_markdown
    return _TABLE_BLOCK_RE.sub(lambda m: fn(m.group(0)), text)


# ── 引擎可用性 ─────────────────────────────────────────────────


def rapiddoc_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("rapid_doc") is not None


def rapidocr_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


# ── 引擎一：RapidDoc（版面 + 表格）─────────────────────────────
_ENGINE = None


def _get_engine(table: bool = True, formula: bool = False):
    """懒加载 RapidDoc 引擎（同配置复用实例，避免重复加载模型）。"""
    global _ENGINE
    if _ENGINE is None or _ENGINE[0] != (table, formula):
        setup_models_env()
        _ensure_streams()
        _quiet_logs()
        from rapid_doc import RapidDoc
        _ENGINE = ((table, formula), RapidDoc(formula_enable=formula,
                                              table_enable=table,
                                              lang="ch"))
    return _ENGINE[1]


def _md_from_content_list(items: list, mode: str, include_images: bool) -> str:
    """按 page_idx 逐页组装 Markdown（保留 `<!-- 第 N 页 -->` 分页标记）。"""
    pages: dict[int, list[str]] = {}
    for item in items or []:
        idx = int(item.get("page_idx") or 0)
        bucket = pages.setdefault(idx, [])
        kind = item.get("type")
        if kind == "text":
            body = (item.get("text") or "").strip()
            if not body:
                continue
            level = item.get("text_level") or 0
            bucket.append(("#" * int(level) + " " + body) if level else body)
        elif kind == "table":
            html = item.get("table_body") or ""
            if not html:
                continue
            cap = item.get("table_caption") or []
            cap_txt = " ".join(cap) if isinstance(cap, list) else str(cap)
            if mode == "off":
                block = html          # 不该发生（off 时引擎不出表格块）
            elif mode == "html":
                block = html
            elif mode == "text":
                block = table_html_to_text(html)
            else:
                block = table_html_to_markdown(html)
            bucket.append((cap_txt + "\n\n" if cap_txt else "") + block)
        elif kind in ("image", "figure") and include_images:
            img = item.get("img_path") or ""
            if img:
                bucket.append(f"![]({img})")
        elif kind == "equation":
            body = (item.get("text") or "").strip()
            if body:
                bucket.append(f"$$ {body} $$")

    parts = []
    for idx in sorted(pages):
        parts.append(f"<!-- 第 {idx + 1} 页 -->\n\n" + "\n\n".join(pages[idx]))
    return "\n\n".join(parts)


def ocr_pdf_rapiddoc(path: str | Path, *, table_mode: str = "md", formula: bool = False,
                     page_markers: bool = True,
                     include_images: bool = False, verbose: bool = False) -> str:
    """用 RapidDoc 解析 PDF → Markdown（含表格还原）。

    table_mode: md（默认，Markdown 表格）／html／text（纯文本行）／off（关表格模型，最快）
    """
    setup_models_env(verbose=verbose)
    engine = _get_engine(table=(table_mode != "off"), formula=formula)
    result = engine(str(path))

    items = getattr(result, "content_list_json", None)
    if page_markers and items:
        text = _md_from_content_list(items, table_mode, include_images)
    else:
        text = getattr(result, "markdown", "") or ""
        text = convert_tables(text, table_mode)

    if not include_images:
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def ocr_pdf_bytes_rapiddoc(data: bytes, *, table_mode: str = "md",
                           page_markers: bool = True) -> str:
    """内存中的 PDF bytes → Markdown（供邮件附件复用）。"""
    with tempfile.TemporaryDirectory(prefix="doc2md_") as tmp:
        tmp_pdf = Path(tmp) / "input.pdf"
        tmp_pdf.write_bytes(data)
        return ocr_pdf_rapiddoc(tmp_pdf, table_mode=table_mode,
                                page_markers=page_markers)


# ── 统一入口 ───────────────────────────────────────────────────


def convert_pdf(path: str | Path, *, table_mode: str = "md",
                page_markers: bool = True, verbose: bool = False) -> str:
    """PDF → Markdown（RapidDoc 引擎，含表格）。"""
    if not rapiddoc_available():
        raise RuntimeError("未安装 rapid-doc 引擎。请执行: pip install rapid-doc")
    return ocr_pdf_rapiddoc(path, table_mode=table_mode,
                            page_markers=page_markers, verbose=verbose)


def convert_image(path: str | Path) -> str:
    """图片 → 文本（走轻量 RapidOCR；RapidDoc 面向版面型 PDF）。"""
    import pdfocr
    engine = pdfocr.build_engine()
    return pdfocr.ocr_image(engine, str(path))


def convert(path: str | Path, *, table_mode: str = "md",
            page_markers: bool = True) -> str:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        return convert_pdf(p, table_mode=table_mode, page_markers=page_markers)
    if p.suffix.lower() in IMAGE_EXTS:
        return convert_image(p)
    raise ValueError(f"不支持的类型: {p.suffix}（doc2md 处理 PDF 与图片）")


# ── 命令行 ─────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="doc2md",
        description="扫描版 PDF → Markdown（版面还原 + 表格识别，全程离线）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  doc2md 扫描件.pdf                    输出到屏幕
  doc2md 扫描件.pdf -o 结果.md          写入文件
  doc2md D:\\扫描件 -o D:\\MD -r         目录批量转换（含子目录）
  doc2md 扫描件.pdf --no-table         关闭表格识别（更快，纯文字）
  doc2md 扫描件.pdf --keep-html        表格保留 HTML（合并单元格信息最全）
""")
    p.add_argument("input", nargs="+", help="PDF / 图片文件，或目录（可多个）")
    p.add_argument("-o", "--output-dir", default=None,
                   help="输出目录（平铺）或单文件时的输出 .md 路径；不给则与源文件同目录")
    p.add_argument("-r", "--recursive", action="store_true", help="目录递归（含子目录）")
    p.add_argument("--table-mode", choices=TABLE_MODES, default="md",
                   help="表格输出：md（默认，Markdown 表格，合并单元格自动回退 HTML）｜"
                        "html（一律保留 HTML）｜text（纯文本行，保留内容无结构）｜"
                        "off（关闭表格模型，最快，但表格区域内容会丢失）")
    p.add_argument("--no-table", action="store_true",
                   help="等价于 --table-mode off（快，但表格内容会丢，不推荐）")
    p.add_argument("--keep-html", action="store_true",
                   help="等价于 --table-mode html（表格保留 HTML，信息最全）")
    p.add_argument("--no-page-marks", action="store_true", help="不输出 <!-- 第 N 页 --> 标记")
    p.add_argument("--overwrite", action="store_true", help="覆盖已存在的 MD")
    p.add_argument("--delete", action="store_true", help="转换成功后删除源文件")
    p.add_argument("--verbose", action="store_true", help="打印引擎日志")
    return p


def _resolve_table_mode(args) -> str:
    if args.no_table:
        return "off"
    if args.keep_html:
        return "html"
    return args.table_mode


def _collect(src: Path, recursive: bool) -> list[Path]:
    exts = PDF_EXTS | IMAGE_EXTS
    if src.is_file():
        return [src] if src.suffix.lower() in exts else []
    pattern = "**/*" if recursive else "*"
    return sorted(p for p in src.glob(pattern) if p.is_file() and p.suffix.lower() in exts)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    files: list[Path] = []
    for item in args.input:
        src = Path(item).expanduser()
        if not src.exists():
            print(f"[错误] 路径不存在：{src}", file=sys.stderr)
            return 2
        files.extend(_collect(src, args.recursive))
    if not files:
        print("[提示] 未找到可处理的 PDF / 图片")
        return 0

    # 去重
    seen, uniq = set(), []
    for f in files:
        key = f.resolve()
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    files = uniq

    if not rapiddoc_available():
        print("[错误] 未安装 rapid-doc 引擎。请执行: pip install rapid-doc", file=sys.stderr)
        return 1
    if find_models_dir() is None:
        print("[警告] 未找到本地模型目录，将尝试联网下载模型（离线环境会失败）", file=sys.stderr)

    out_arg = Path(args.output_dir).expanduser() if args.output_dir else None
    single_out = (out_arg if out_arg and len(files) == 1
                  and out_arg.suffix.lower() == ".md" else None)
    out_dir = None if single_out else out_arg

    table_mode = _resolve_table_mode(args)
    if table_mode == "off":
        print("[警告] 表格模型已关闭：转换更快，但**表格区域的内容会丢失**。"
              "如需保留表格文字，请用 --table-mode text 或改用 pdfocr --engine rapidocr",
              file=sys.stderr)

    print(f"共 {len(files)} 个文件，引擎：RapidDoc（表格模式：{table_mode}）\n")
    ok = skip = fail = 0
    t0 = time.time()
    for i, f in enumerate(files, 1):
        target = single_out or ((out_dir / (f.stem + ".md")) if out_dir else f.with_suffix(".md"))
        if target.exists() and not args.overwrite and not single_out:
            print(f"[{i}/{len(files)}] 跳过（MD 已存在）{f.name}")
            skip += 1
            continue
        try:
            ti = time.time()
            text = convert(f, table_mode=table_mode,
                           page_markers=not args.no_page_marks)
            dt = time.time() - ti
            if not text.strip():
                raise ValueError("未提取到内容")
            if single_out and args.output_dir is None:
                print(text)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8", newline="\n")
                print(f"[{i}/{len(files)}] ✓ {f.name} → {target.name} "
                      f"({len(text)} 字符, {dt:.1f}s)")
            if args.delete:
                f.unlink()
            ok += 1
        except Exception as exc:
            print(f"[{i}/{len(files)}] ✗ 失败 {f.name}：{type(exc).__name__}: {exc}",
                  file=sys.stderr)
            fail += 1

    print(f"\n完成：成功 {ok}，跳过 {skip}，失败 {fail}，耗时 {time.time() - t0:.1f} 秒")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
