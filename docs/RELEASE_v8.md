# eml2md v8.0 — 扫描件表格识别

## 本次重点：扫描版 PDF 里的表格能还原了 ⭐

v6 及以前，扫描版 PDF 只能逐页 OCR 成**散乱的文本行**，表格结构完全丢失。
例如一份采购验收表的型号列 `S5731-H48T4XC` 会被打散成 `S5731-H 48T 4X C`。

v8 引入 **RapidDoc 管线**（版面分析 PP-DocLayoutV3 + RapidOCR + RapidTable 表格结构识别），
把扫描件里的表格**还原成真正的 Markdown 表格**。

| | v6 | v8 |
| --- | --- | --- |
| 表格结构 | ❌ 打散成文本行 | ✅ 完整 Markdown 表格 |
| 标题层级 | ❌ 无 | ✅ 自动识别 `#` 级别 |
| 分页标记 | ❌ 无 | ✅ `<!-- 第 N 页 -->` |
| 合并单元格 | — | ✅ 自动回退 HTML，不丢信息 |

## 新增第 6 个命令行工具：`doc2md.exe`

```bat
doc2md 扫描件.pdf                    :: 转 Markdown（含表格），打印到屏幕
doc2md 扫描件.pdf -o 结果.md          :: 写入文件
doc2md "D:\扫描件" -o "D:\MD" -r      :: 目录批量（含子目录）
doc2md 扫描件.pdf --table-mode html   :: 表格保留 HTML
doc2md 扫描件.pdf --table-mode text   :: 表格转纯文本行
```

### 表格输出四种模式

| 模式 | 参数 | 说明 |
| --- | --- | --- |
| `md`（默认） | `--table-mode md` | Markdown 表格；遇合并单元格自动回退 HTML |
| `html` | `--table-mode html` / `--keep-html` | 一律保留 `<table>`，信息最全 |
| `text` | `--table-mode text` | 纯文本行，保留内容不留结构 |
| `off` | `--table-mode off` / `--no-table` | 关闭表格模型（最快，⚠️ 表格内容会丢） |

## 其它改动

- **`pdfocr.exe`** 新增 `--engine auto|rapiddoc|rapidocr`：
  `auto`（默认）下文本型 PDF 直接取文本层，含扫描页才走表格引擎。
- **`eml2md.exe`** 邮件附件里的扫描版 PDF 默认优先走表格引擎，
  新增 `--ocr-engine` / `--ocr-table-mode` / `--no-ocr-tables` / `--ocr-keep-html`。
- **图形界面**新增「扫描版 PDF / 扫描件选项」区：识别表格开关 + 表格输出 + 引擎选择。
- 修复：Windows 中文环境下输出重定向（管道/文件）时，`✓` 等字符触发
  `UnicodeEncodeError` 导致转换被误判为失败。

## 完全离线

- 模型（164 MB）随包携带在 `models/` 目录，通过 `RAPID_MODELS_DIR` 指向，**不联网**。
- OCR det/rec 模型内置于 `rapid_doc/resources`。
- 语言检测用包内 `lid.176.ftz`，不回退到联网下载。
- 已裁掉 openvino（约 200 MB），CPU 走 onnxruntime。

## 下载

解压后六个 EXE 共享一份 `_internal`：

```
eml2md.exe         邮件 EML/MSG → 完整 MD
doc2md.exe         扫描版 PDF → MD（含表格识别）  ← v8 新增
pdfocr.exe         扫描版 PDF / 图片 → 文本或 MD
markitdown.exe     任意单文件 → MD
ebook2md.exe       电子书 EPUB/MOBI/AZW3 → MD
eml2md_gui.exe     图形界面
models\            RapidDoc / RapidTable / 语言检测 模型（164 MB）
```

## 性能

| 项目 | 数值 |
| --- | --- |
| 首次加载模型 | 约 20 秒（同一次运行内复用） |
| 单页解析 | 约 2~4 秒 |
| 纯文本型 PDF | auto 模式直接取文本层，不跑 OCR |
