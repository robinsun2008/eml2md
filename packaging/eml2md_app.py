# -*- coding: utf-8 -*-
"""eml2md_app.py — PyInstaller 打包入口。

仅做一件事：加载 eml2md 主模块并执行其 main()。
所有业务逻辑都在 eml2md.py（与 packaging 目录平级），此处不复制代码，
保证"源码只有一份，打包时通过 pathex 引用"。
"""
import sys

from eml2md import main

if __name__ == "__main__":
    sys.exit(main())
