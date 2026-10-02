# -*- mode: python ; coding: utf-8 -*-
"""eml2md.spec — eml2md 主程序打包配置（onedir）。

v3 架构说明：markitdown.exe / pdfocr.exe 由各自的 spec 独立构建
（markitdown.spec / pdfocr.spec），构建完成后把这两个 EXE 复制进
本 spec 产出的文件夹即可——三者共享同一份 _internal，体积几乎不变。
（不能用单个 spec 多 Analysis：PyInstaller 会在 Analysis 间重建
base_library.zip，与本机批量删除保护冲突。）
"""
from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = []
binaries = []
hiddenimports = []

# rapidocr 模型 + onnxruntime DLL + magika 模型：三件套整体收集
for pkg in ("rapidocr_onnxruntime", "onnxruntime", "magika"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# markitdown 转换器全量显式引入 + MSG 解析依赖
hiddenimports += [
    "extract_msg",
    "olefile",
    "markitdown.converters._audio_converter",
    "markitdown.converters._bing_serp_converter",
    "markitdown.converters._csv_converter",
    "markitdown.converters._doc_intel_converter",
    "markitdown.converters._docx_converter",
    "markitdown.converters._epub_converter",
    "markitdown.converters._html_converter",
    "markitdown.converters._image_converter",
    "markitdown.converters._ipynb_converter",
    "markitdown.converters._outlook_msg_converter",
    "markitdown.converters._pdf_converter",
    "markitdown.converters._plain_text_converter",
    "markitdown.converters._pptx_converter",
    "markitdown.converters._rss_converter",
    "markitdown.converters._wikipedia_converter",
    "markitdown.converters._xlsx_converter",
    "markitdown.converters._zip_converter",
]

a = Analysis(
    ["pdfocr_app.py"],
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
        "tensorflow",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pdfocr",
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
    name="pdfocr",
)
