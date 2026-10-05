# -*- mode: python ; coding: utf-8 -*-
"""doc2md.spec — 表格识别 CLI（RapidDoc 管线）打包配置（onedir）。

V8 新增：扫描版 PDF → Markdown（版面分析 + OCR + 表格结构识别）。

要点：
  * collect_all("rapid_doc") 收全子模块与 resources（内含 PP-OCRv6 det/rec ONNX）
  * rapidocr（新版）也要收，RapidDoc 的 OCR 走它
  * **不收集 openvino**（约 200MB）：rapid_doc 内部惰性导入，缺省时自动用 onnxruntime
  * 模型目录（163MB，pp_doclayoutv3 等）不在此打包，而是随交付包放在
    eml2md/models/ ，由 doc2md.setup_models_env() 通过环境变量 RAPID_MODELS_DIR 指向
"""
from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = []
binaries = []
hiddenimports = []

# OCR / 版面 / 表格三套引擎整体收集
for pkg in ("rapidocr_onnxruntime", "onnxruntime", "magika", "rapid_doc", "rapidocr"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# RapidDoc 的依赖链（显式列出，避免动态导入被漏掉）
hiddenimports += [
    "doc2md",
    "markdownify",
    "bs4", "soupsieve", "lxml",
    "shapely", "tokenizers", "omegaconf", "antlr4", "json_repair",
    "pdftext", "pypdfium2", "pypdf", "reportlab", "cv2",
    "ftfy", "loguru", "robust_downloader", "fasttext",
    "openai", "httpx", "httpcore", "h11", "anyio", "huggingface_hub", "pydantic",
    "docx", "pptx", "mammoth", "openpyxl", "pylatexenc", "yaml", "PIL",
]

a = Analysis(
    ["doc2md_app.py"],
    pathex=["..", "../.."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "PyQt5",
        "PyQt6",
        "torch",
        "torchvision",
        "tensorflow",
        "openvino",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="doc2md",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="doc2md",
)
