# -*- coding: utf-8 -*-
"""router.py — V4 转换路由：统一调度 eml2md / markitdown / pdfocr 三大引擎。

分类规则:
  .eml / .msg          → 邮件引擎（eml2md 管线，含附件合并与 OCR 兜底）
  .pdf / 常见图片       → pdfocr 引擎（有文本层用文本层，扫描件自动 OCR）
  .epub / .mobi / .azw3 → 电子书引擎（epub 直转；Kindle 格式先解包再转）
  音视频                → 跳过（不转换）
  其余                  → markitdown 引擎（能转多少转多少，失败仅记录）

电子书说明:
  EPUB 由 markitdown 内置转换器直接处理（保留标题层级/列表/表格）；
  MOBI、AZW3 等 Kindle 格式先用 mobi 库解包（KF8 会还原成 epub），
  再走同一条通道。插图不参与转换，仅提取文字。

输出模式:
  same : MD 与源文件同目录（源在子目录，MD 也在该子目录）
  flat : 全部 MD 集中到指定输出目录（不分子目录，重名后到者覆盖）
"""
import re
import shutil
from argparse import Namespace
from pathlib import Path

import eml2md
import pdfocr

MAIL_EXTS = {".eml", ".msg"}
IMAGE_EXTS = set(pdfocr.IMAGE_EXTS)
BOOK_EXTS = {".epub", ".mobi", ".azw3", ".azw", ".kf8"}
AUDIO_VIDEO_EXTS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".wma", ".opus",
    ".mid", ".midi", ".amr", ".ape",
    ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg", ".3gp", ".ts", ".rm", ".rmvb", ".vob",
}

OPTS = Namespace(
    output_dir=None, suffix=".md", overwrite=True, keep_attachments=False,
    max_attachment_mb=50, include_inline=False, keep_nan=False,
    no_ocr=False, ocr_dpi=200, ocr_pdf_min_chars=20, ocr_office_min_chars=20,
    skip_keywords=[],
)


def classify(path: Path) -> str:
    """返回 mail / ocr / ebook / markitdown / skip / already_md"""
    ext = path.suffix.lower()
    if ext == ".md":
        return "already_md"
    if ext in MAIL_EXTS:
        return "mail"
    if ext == ".pdf" or ext in IMAGE_EXTS:
        return "ocr"
    if ext in BOOK_EXTS:
        return "ebook"
    if ext in AUDIO_VIDEO_EXTS:
        return "skip"
    return "markitdown"


_MD_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def strip_images(text: str) -> str:
    """去掉 Markdown 图片引用。

    电子书插图按「只取文字」策略处理：转换后图片指向包内相对路径，
    在独立 MD 文件里是死链，故一并清除并压缩多余空行。
    """
    text = _MD_IMG_RE.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class Router:
    """懒加载引擎的统一转换器。一个实例处理一批任务。"""

    def __init__(self, ocr_dpi: int = 200, log=None):
        self.ocr_dpi = ocr_dpi
        self._md = None          # MarkItDown 引擎
        self._ocr = None         # RapidOCR 引擎
        self._log = log or (lambda msg: None)

    # ── 引擎懒加载 ──────────────────────────────────────────────
    def _md_engine(self):
        if self._md is None:
            self._log("初始化 MarkItDown 引擎…")
            self._md = eml2md.MarkItDown(enable_plugins=False)
        return self._md

    def _ocr_engine(self):
        if self._ocr is None:
            self._log("初始化 RapidOCR 引擎…（首次较慢）")
            self._ocr = pdfocr.build_engine()
        return self._ocr

    # ── 电子书（epub / mobi / azw3）────────────────────────────
    def _convert_ebook(self, path: Path) -> str:
        """电子书 → Markdown 文本。

        EPUB：markitdown 内置转换器直接处理。
        MOBI / AZW3 / KF8：mobi 库解包（KF8 还原为 epub），再走同一通道。
        插图不提取，避免产生指向包内资源的死链。
        """
        if path.suffix.lower() == ".epub":
            result = self._md_engine().convert(str(path))
            return strip_images(result.text_content or "")

        try:
            import mobi as mobi_unpack
        except ImportError as exc:  # 理论上不会发生（已打包）
            raise ValueError("解包组件缺失，无法处理 Kindle 格式") from exc

        tmpdir = None
        try:
            self._log("  解包 Kindle 格式…")
            tmpdir, mainfile = mobi_unpack.extract(str(path))
            main = Path(mainfile)
            if not main.exists() or main.stat().st_size == 0:
                raise ValueError("解包后未找到正文内容")
            self._log(f"  解包结果：{main.name}")
            result = self._md_engine().convert(str(main))
            return strip_images(result.text_content or "")
        except Exception as exc:
            low = str(exc).lower()
            if "drm" in low or "encrypt" in low or "encryption" in low:
                raise ValueError("该电子书带有 DRM 版权保护，无法解析") from exc
            raise
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)

    # ── 单文件转换 ──────────────────────────────────────────────
    def convert_text(self, path: Path):
        """把单个文件转换为 Markdown 文本（不落盘）。返回 (kind, text)。

        kind: mail / ocr / ebook / markitdown。异常向上抛出，由调用方处理。
        """
        path = Path(path)
        kind = classify(path)
        if kind in ("already_md", "skip"):
            raise ValueError("音视频文件无需转换；.md 文件无需再转换")

        if kind == "mail":
            raw = None
            if path.suffix.lower() == ".msg":
                raw = eml2md.msg_to_eml_bytes(path)
            text = eml2md.eml_to_markdown(path, self._md_engine(), OPTS, raw=raw)
        elif kind == "ocr":
            engine = self._ocr_engine()
            args = Namespace(dpi=self.ocr_dpi, start=None, end=None,
                             min_chars=20, force_ocr=False, text_only=False)
            if path.suffix.lower() == ".pdf":
                text = pdfocr.process_pdf(path, args, engine, "md")
            else:
                text = pdfocr.process_image(path, engine)
        elif kind == "ebook":
            text = self._convert_ebook(path)
        else:  # markitdown
            result = self._md_engine().convert(str(path))
            text = (result.text_content or "").strip()

        if not (text or "").strip():
            raise ValueError("转换结果为空（未提取到内容）")
        return kind, text

    def convert(self, path: Path, output_mode: str = "same",
                output_dir: Path | None = None, keep_source: bool = True):
        """转换单个文件。返回 (状态, 输出MD路径或None, 说明)。

        状态: ok / skip / fail
        """
        path = Path(path)
        kind = classify(path)

        if kind in ("already_md", "skip"):
            return ("skip", None, "音视频/已是MD，跳过" if kind == "skip" else "已是MD")

        # 计算输出路径
        if output_mode == "flat" and output_dir is not None:
            out = Path(output_dir) / (path.stem + ".md")
        else:
            out = path.with_suffix(".md")

        try:
            kind, text = self.convert_text(path)
        except ValueError as exc:
            return ("fail", None, str(exc))
        except Exception as exc:
            return ("fail", None, f"{type(exc).__name__}: {exc}")

        if not (text or "").strip():
            return ("fail", None, "转换结果为空")

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")

        if not keep_source:
            try:
                path.unlink()
                self._log(f"  源文件已删除: {path.name}")
            except Exception as exc:
                self._log(f"  [WARN] 源文件删除失败: {exc}")

        return ("ok", out, kind)

    # ── 目录批量转换 ────────────────────────────────────────────
    def scan_dir(self, root: Path) -> list[Path]:
        """递归检索目录下所有可转换文件（排除 .md 产物与音视频）。"""
        root = Path(root)
        files = []
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if classify(p) in ("skip", "already_md"):
                continue
            files.append(p)
        return files


def clean_flat_dir(output_dir: Path):
    """确保输出目录存在。"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
