# -*- coding: utf-8 -*-
"""pdfocr_app.py — pdfocr 独立 CLI 的打包入口。

用法与本地 pdfocr 完全一致（扫描版 PDF / 图片 → 文本或 Markdown）：
  pdfocr.exe 扫描件.pdf -o 结果.md [--dpi 300] [--force-ocr] ...
"""
import sys

import pdfocr

if __name__ == "__main__":
    sys.exit(pdfocr.main())
