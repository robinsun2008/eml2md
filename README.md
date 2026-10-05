# eml2md — 邮件 / 文档 / 电子书 一键转 Markdown（离线工具箱）

把 Outlook 导出的 `.eml` / `.msg` 邮件（**含附件、含扫描件 OCR**）转换成**单一、无乱码**的 Markdown 文件；
同时提供一个通用文档转换器与图形界面，全部打包成**免安装 EXE**，可以在**没有 Python、也没有网络**的电脑上直接运行。

> **v8 新增**：扫描版 PDF 里的**表格能还原成 Markdown 表格**了
> （RapidDoc 管线：版面分析 + RapidOCR + RapidTable 表格结构识别），
> 并新增第 6 个工具 `doc2md.exe`。

## 为什么需要它

Outlook / Exchange 导出的中文邮件常见「多层编码叠加」：

| 层 | 编码 | 常见错误表现 |
| --- | --- | --- |
| 邮件头（Subject / From / To） | RFC 2047 `=?gb2312?B?...?=` | 头部显示 `=?gb2312?B?...?=` |
| 正文 text/plain | `gb2312` + base64 | 一堆 base64 字符 |
| 正文 text/html | `gb2312` + quoted-printable | `=3D`、`=D0=C5` 之类乱码 |

MarkItDown 直接处理 `.eml` 时不做这些解码，因此会乱码。本项目按正确顺序逐层解码，再调用 MarkItDown 把附件逐个转成 Markdown 并**合并进同一个文件**。

## 功能一览

| 工具 | 作用 |
| --- | --- |
| `eml2md` | 邮件转换：`.eml` / `.msg` → 单一 Markdown（附件内容合并，扫描件自动 OCR + 表格识别） |
| `doc2md` | **扫描版 PDF → Markdown（版面还原 + 表格识别）**（v8 新增） |
| `markitdown` | 通用文档转换：PDF / Word / Excel / PPT / HTML / 图片 / 音频 等 |
| `pdfocr` | 扫描版 PDF / 图片识别（`--engine rapiddoc` 含表格 / `rapidocr` 轻量） |
| `ebook2md` | 电子书转换：EPUB / MOBI / AZW3 / AZW / KF8 |
| `eml2md_gui` | 图形界面：单文件拖入自动判型 + 目录批量转换（进度条 / 完成率 / 预计剩余时间） |

## 下载即用

到 [Releases](../../releases) 下载 `eml2md_portable_v8.zip`（约 572 MB），解压后目录结构：

```
eml2md/
├── eml2md.exe          # 邮件转换
├── doc2md.exe          # 扫描版 PDF → Markdown（含表格识别）  ← v8 新增
├── markitdown.exe      # 通用文档转换
├── pdfocr.exe          # 扫描件 OCR / 表格
├── ebook2md.exe        # 电子书转换
├── eml2md_gui.exe      # 图形界面（双击即用）
├── manual_cn.md        # 使用手册
├── models/             # 离线模型（RapidDoc / RapidTable / 语言检测，164 MB）
├── test_samples/       # 精简测试样本（用于离线自检）
└── _internal/          # 运行时与依赖（六个 EXE 共享，请勿删除或拆分）
```

**无需安装 Python，无需联网。** 全 ASCII 文件名，解压到任意目录即可（路径不要包含特殊字符）。
`models/` 必须与 EXE 放在一起——程序启动时会在 EXE 同级目录查找模型，找不到才会尝试联网下载。

### 命令行示例

```cmd
:: 邮件 → Markdown（默认输出到源文件同目录）
eml2md.exe "D:\邮件\2026-08 周报.eml"

:: 批量转换目录（含子目录），统一输出
eml2md.exe "D:\邮件" -r -o "D:\输出"

:: 扫描版 PDF → Markdown（含表格还原，v8 新增）
doc2md.exe "D:\扫描件\验收报告.pdf" -o "D:\输出\验收报告.md"

:: 表格保留 HTML（合并单元格信息最全）
doc2md.exe "D:\扫描件\预算表.pdf" --keep-html

:: 扫描版 PDF 识别（可切换引擎）
pdfocr.exe "D:\扫描件\合同.pdf" -o "D:\输出\合同.md" --engine rapiddoc

:: 电子书批量转换
ebook2md.exe "D:\电子书" -r -o "D:\输出"

:: 通用文档转换
markitdown.exe "D:\资料\方案.docx" -o "D:\输出\方案.md"
```

### 表格识别的四种输出模式（`--table-mode`）

| 模式 | 参数 | 效果 |
| --- | --- | --- |
| `md`（默认） | `--table-mode md` | Markdown 表格；遇到**合并单元格**自动回退 HTML（Markdown 语法无法表达） |
| `html` | `--table-mode html` / `--keep-html` | 一律保留 `<table>`，信息最全 |
| `text` | `--table-mode text` | 纯文本行（`单元格 \| 单元格`），保留内容不留结构 |
| `off` | `--table-mode off` / `--no-table` | 关闭表格模型（最快，⚠️ 表格区域内容会丢失） |

### 图形界面

双击 `eml2md_gui.exe`：

- **单文件标签页**：拖入任意文件 → 自动识别类型 → 另存为 Markdown
- **目录标签页**：拖入文件夹 → 递归转换，实时进度条 + 完成率 + 预计完成时间
- 输出模式：**源文件同目录** 或 **统一输出目录**
- 可选是否保留源文件
- **扫描件选项**（v8 新增）：识别表格开关 + 表格输出（md / html / text）+ 扫描件引擎（auto / rapiddoc / rapidocr）

## 支持的格式

| 类别 | 扩展名 |
| --- | --- |
| 邮件 | `.eml` `.msg` |
| 文档 | `.pdf` `.docx` `.doc` `.xlsx` `.xls` `.pptx` `.ppt` `.txt` `.md` `.csv` `.json` `.xml` |
| 网页 | `.html` `.htm` |
| 图片（OCR） | `.png` `.jpg` `.jpeg` `.bmp` `.tif` `.tiff` |
| 电子书 | `.epub` `.mobi` `.azw` `.azw3` `.kf8` |
| 其它 | `.zip`（列出内容） `.mp3` `.wav`（元数据） |

## 从源码运行

```bash
pip install markitdown==0.1.7 pdfplumber==0.11.10 rapidocr-onnxruntime pymupdf \
            rapid-doc extract-msg mobi tkinterdnd2 pillow beautifulsoup4 lxml markdownify

python eml2md.py  "mail.eml"      # 邮件转换
python doc2md.py  "scan.pdf"      # 扫描版 PDF → Markdown（含表格，v8 新增）
python ebook2md.py "book.epub"    # 电子书转换
python pdfocr.py  "scan.pdf"      # 扫描件识别（--engine rapiddoc|rapidocr）
python gui_app.py                 # 图形界面
```

> **注意**：`pdfplumber` 是 MarkItDown 的 PDF 转换器必需依赖（内部还需 `pdfminer.six`）。
> 缺失时邮件里的 PDF 附件会直接转换失败，且**不会触发 OCR 兜底**，务必安装。

> `rapid-doc` 是表格识别引擎（v8 新增）。首次运行会自动下载约 164 MB 模型；
> 离线环境请把模型放到 `models/` 目录（或用环境变量 `RAPID_MODELS_DIR` 指向模型目录），
> 程序检测到模型已存在就不会联网。

## 从源码构建 EXE

环境：Python 3.13 + PyInstaller 6.22.3（onedir 模式）。

```bash
cd packaging
pyinstaller eml2md.spec  --distpath dist_eml --workpath build_eml --noconfirm
pyinstaller doc2md.spec  --distpath dist_doc --workpath build_doc --noconfirm
pyinstaller markitdown.spec --distpath dist_md  --workpath build_md  --noconfirm
pyinstaller pdfocr.spec  --distpath dist_pdf --workpath build_pdf --noconfirm
pyinstaller ebook2md.spec --distpath dist_eb --workpath build_eb --noconfirm
pyinstaller gui.spec     --distpath dist_gui --workpath build_gui --noconfirm
```

构建要点（踩坑总结）：

1. **每个 EXE 用独立 spec 独立构建**——一个 spec 里放多个 `Analysis` 会导致 `base_library.zip` 被反复重建，某些环境会构建失败；
2. 构建完成后，把五个小 EXE 复制进 GUI 产物目录，**以 GUI 的 `_internal` 为准**（它是超集，含 tkinter / tcl / tkinterdnd2 / rapid_doc）；
3. **纯 Python 模块编译进各自的 EXE 内部**，`_internal/` 只放二进制扩展与数据（共享）——因此改了某个模块的源码，必须重建**对应**的 EXE；
4. 交付 zip 使用**全 ASCII 文件名**——中文文件名经 Windows 压缩后跨机器易乱码；
5. `gui.spec` 的 `excludes` 中**不能**排除 `tkinter`；
6. `excludes` 里排掉 `openvino`（约 200 MB）：`rapid_doc` 内部惰性导入，CPU 走 onnxruntime；
7. **ONNX 模型不打包进 EXE**，而是放在交付包的 `models/` 目录，由 `RAPID_MODELS_DIR` 指向；
8. 构建依赖与运行依赖必须一致，特别注意 `pdfplumber`、`onnxruntime` 的版本。

## 目录结构

```
.
├── eml2md.py            # 邮件转换引擎（纯标准库解析 + 附件合并 + OCR 兜底）
├── doc2md.py            # 扫描版 PDF → Markdown（RapidDoc 管线：版面 + 表格）  v8 新增
├── router.py            # 类型路由：mail / ocr / ebook / markitdown / skip
├── ebook2md.py          # 电子书转换 CLI
├── pdfocr.py            # 扫描件 OCR 引擎（RapidOCR / RapidDoc 双引擎）
├── gui_app.py           # tkinter 图形界面
├── packaging/           # 六个 PyInstaller spec + 入口脚本
├── docs/manual_cn.md    # 使用手册
└── test_samples/        # 测试样本与标准答案（逐字比对用）
```

## 测试与验收

`test_samples/expected/` 存放每个样本的**标准答案**，转换结果应与之一致：

```cmd
eml2md.exe  test_samples\scan_test.eml -o out
fc /b out\scan_test.md test_samples\expected\scan_test.md
```

`test_samples/v8_tables/` 是 v8 的**表格识别专用样本**（图片型 PDF，无文本层）：

```cmd
:: 6 列表格 → 应还原为 Markdown 表格
doc2md.exe test_samples\v8_tables\table_scan.pdf

:: 含合并单元格 → 应回退为 <table> HTML（信息不丢）
doc2md.exe test_samples\v8_tables\merged_scan.pdf --keep-html
```

## 已知限制

- **带 DRM 的电子书**（如 Amazon 官方商店购买）无法处理，仅支持无 DRM 的 EPUB / MOBI / AZW3；
- 老版本 MOBI（非 KF8）**源文件本身没有标题层级**，转换结果同样平铺，属格式固有限制；
- 电子书插图按「只取文字」策略处理，Markdown 中不保留图片引用；
- 个别老旧 Windows 机器上，新构建的 EXE 可能被安全软件静默拦截而无法启动（表现为双击无反应、无任何报错）。排查思路：从 cmd 运行 `eml2md.exe --help > err.txt 2>&1`，检查 `err.txt`、退出码 `%ERRORLEVEL%`、以及事件查看器中的故障模块名，并确认杀毒软件信任区设置与解压文件完整性。

## 隐私说明

仓库中的 `test_samples/` 只包含**合成样本**（`scan_test.eml`）与**公版电子书**（Project Gutenberg）。
其余开发期使用的邮件样本含真实内部信息，未纳入本仓库。

## 第三方组件

本项目基于以下开源组件构建，各自遵循其原始许可：MarkItDown、**RapidDoc**（版面分析 PP-DocLayoutV3 + RapidTable 表格结构识别，本项目用于扫描件表格还原）、RapidOCR / ONNX Runtime、PyMuPDF、pdfplumber / pdfminer.six、extract-msg、mobi、tkinterdnd2 等。
