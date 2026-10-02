# -*- coding: utf-8 -*-
"""markitdown_app.py — MarkItDown 独立 CLI 的打包入口。

用法与 pip 安装的 markitdown 完全一致：
  markitdown.exe <file> [-o out.md]
支持 pdf/docx/xlsx/pptx/csv/html/图片(文本提取) 等所有格式。
"""
import sys

from markitdown.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
