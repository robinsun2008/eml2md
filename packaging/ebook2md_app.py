# -*- coding: utf-8 -*-
"""ebook2md_app.py — ebook2md 独立 CLI 的打包入口。

用法：
  ebook2md.exe 书.epub
  ebook2md.exe "D:\\电子书" -o "D:\\MD" --flat
"""
import sys

import ebook2md

if __name__ == "__main__":
    sys.exit(ebook2md.main())
