# -*- coding: utf-8 -*-
"""doc2md_app.py — doc2md 独立 CLI 的打包入口。

用法与本地 doc2md 完全一致（扫描版 PDF → Markdown，含表格识别）：
  doc2md.exe 扫描件.pdf -o 结果.md [--no-table] [--keep-html] ...
"""
import sys

import doc2md

if __name__ == "__main__":
    sys.exit(doc2md.main())
