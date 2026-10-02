# eml2md 使用手册（速查版）

> 把邮件（EML / MSG）、电子书（EPUB / MOBI / AZW3）等文档转换成 Markdown。
> 扫描版 PDF / 图片自动走本地 RapidOCR 识别，全程离线免费。
> MSG（Outlook 格式）会先在内存中转为标准 EML，再走同一套管线，用法完全相同。

## 〇、V5 新增：电子书格式（EPUB / MOBI / AZW3）

三种电子书格式现在都能转成 MD。图形界面里直接拖入即可，命令行用法：

```bat
ebook2md "D:\电子书\某本书.epub"                :: 单本，MD 生成在同目录
ebook2md "D:\电子书库" -o "D:\MD"               :: 整个目录（含子目录）
ebook2md "D:\电子书库" -o "D:\MD" --flat        :: 全部平铺到输出目录，重名覆盖
ebook2md "D:\电子书库" --delete --overwrite     :: 转换后删源文件、覆盖旧 MD
```

| 格式 | 处理方式 | 结构保留 |
| --- | --- | --- |
| **EPUB** | markitdown 内置转换器直接解析 | 标题层级 / 列表 / 表格 / 引用完整保留 |
| **AZW3 / KF8** | mobi 库解包，直接还原为 EPUB | **标题层级完整保留**（推荐来源） |
| **MOBI**（旧版） | mobi 库解包出 HTML 再转换 | 文字完整；老式电子书本身无标题标签，层级较弱 |
| **AZW** | 同 MOBI | 同上 |

三点说明：

1. **插图不提取**——电子书插图不参与转换，只保留文字（否则会生成指向包内图片的死链）
2. **带 DRM 的书无法转换**——Amazon 商店购买的正版电子书有加密保护，任何离线工具都解不开；自制、格式转换而来、公有领域的电子书不受影响
3. 已存在同名 MD 时默认**跳过**，加 `--overwrite` 才覆盖（方便增量收纳新书）

## 〇、V4 新增：图形界面（推荐日常使用）

双击 **`eml2md_gui.exe`** 打开窗口，无需任何命令行：

**单文件转换标签**：把任意文件拖入输入框（或点"浏览"选择）→ 自动识别类型并显示将调用的引擎 → 点"转换并另存为"选择保存位置即可。音视频文件会提示跳过。

**目录批量转换标签**：
1. 选择输入目录（自动递归检索全部子目录）
2. 选择输出方式：
   - **MD 保留在源文件同一目录**——源文件在哪个子目录，MD 就生成在哪
   - **全部集中到指定输出目录**——所有 MD 平铺在一个目录，重名时后转换的覆盖先前的
3. 选择是否保留源文件（默认保留；取消勾选则每生成一个 MD 就自动删除对应源文件）
4. 点"开始转换"：进度条显示完成率、已用时间、预计剩余时间，日志区逐个显示结果

可转换的文件类型：.eml/.msg（邮件）、.pdf/图片（自动 OCR）、**电子书 .epub/.mobi/.azw3（插图不提取）**、docx/xlsx/pptx/xls/csv/html/txt 等文档；音视频自动跳过；已转换过的 .md 自动忽略。

五个命令行工具（eml2md.exe / markitdown.exe / pdfocr.exe / ebook2md.exe / eml2md_gui.exe）继续保留，见下文。

## 〇、V3 新增：包内命令行工具

解压后的文件夹里有五个 EXE，共享同一套依赖（无需分别安装）：

| 命令 | 用途 | 示例 |
| --- | --- | --- |
| `eml2md.exe` | EML/MSG 邮件 → 完整 MD（本手册主题） | `eml2md 邮件.eml -o 输出` |
| `markitdown.exe` | **任意单文件** → MD（pdf/docx/xlsx/pptx/csv/html/epub/msg...） | `markitdown 报告.docx -o 报告.md` |
| `pdfocr.exe` | **扫描版 PDF / 图片** → 文本或 MD（纯 OCR） | `pdfocr 扫描件.pdf -o 结果.md --dpi 300` |
| `ebook2md.exe` | **电子书** EPUB/MOBI/AZW3 → MD（V5 新增） | `ebook2md 书库 -o MD --flat` |
| `eml2md_gui.exe` | 图形界面（不弹命令行窗口） | 双击即可 |

markitdown.exe 用法与 pip 安装的 markitdown 完全一致；pdfocr.exe 常用参数：
`--dpi 300`（更准更慢）、`--start 1 --end 3`（指定页）、`--force-ocr`（有文本层也强制 OCR）、`--text-only`（只取文本层不 OCR）。

---

## 一、最常用：三种典型场景

```bat
:: 1. 转换单封邮件（EML 或 MSG，MD 生成在邮件同目录）
eml2md "D:\邮件\某邮件.eml"
eml2md "D:\邮件\某邮件.msg"

:: 2. 转换整个文件夹（含子目录，.eml 与 .msg 混放也没问题）
eml2md "D:\邮件归档" -o "D:\转换结果"

:: 3. 只转一层、不进子目录
eml2md "D:\邮件归档" -o "D:\转换结果" --no-recursive
```

转换完成后，每封 `.eml` 对应一个同名 `.md`，内含：邮件头表格 → 正文 → 附件清单 → 各附件内容。

## 二、常用参数

| 参数 | 作用 | 默认 |
| --- | --- | --- |
| `-o 目录` | 输出到指定目录（不加则生成在源邮件旁边） | 同目录 |
| `--overwrite` | 覆盖已存在的 MD（不加则跳过同名） | 跳过 |
| `--no-ocr` | 禁用 OCR | 启用 |
| `--ocr-dpi 300` | 扫描件渲染精度，越高越准越慢 | 200 |
| `--keep-attachments` | 同时把附件原文件存到 `<输出>/<邮件名>_attachments/` | 不保存 |
| `--skip-keywords 关键词1 关键词2` | 文件名命中关键词的附件跳过转换（如发票原件） | 无 |
| `--max-attachment-mb 100` | 单附件大小上限，超出只记录不转换 | 50 |
| `--include-inline` | 把内嵌图片（签名图标等）也当附件转换 | 跳过 |

## 三、输出长什么样

每封邮件生成一个 MD，结构如下：

```markdown
# 邮件主题
| 字段 | 内容 |        ← 发件人/收件人/抄送/日期（已正确解码中文）
## 正文                 ← 自动挑选更干净的一份（纯文本 vs HTML）
## 附件清单
1. 方案.pdf ...
## 附件 1: xxx.pdf      ← 文字型 PDF 直接提取；扫描件标注 [OCR 识别]
```

- 文字型附件（docx/xlsx/pptx/文字PDF）→ MarkItDown 直接提取
- **扫描版 PDF / 纯图片 / 图片型 Office** → 自动检测并调用本地 RapidOCR，结果以 `> **[OCR 识别 · 本地 RapidOCR]**` 开头
- 无法识别的附件会如实标注，不会丢

## 四、智能行为（不用你操心）

1. **双格式支持**：.eml 与 .msg 自动识别，同一目录混放一次转完；MSG 的中文主题/收发件人自动解码
2. **编码自适应**：GB2312/GBK/Big5/UTF-8 邮件头与正文自动解码，乱码自动回退修复
2. **正文择优**：纯文本正文损坏（含 �）时自动改用 HTML 正文
3. **OCR 触发条件**：PDF 提取文字 < 20 字符才 OCR（参数 `--ocr-pdf-min-chars` 可调），文字型 PDF 不会白跑 OCR
4. **转发邮件**：嵌套的 .eml 附件会递归转换，标题自动降一级
5. **重复保护**：同名 MD 已存在自动跳过，适合增量追加新邮件

## 五、日常使用建议（工作流）

1. Outlook 里把邮件"另存为 .eml"（可多选批量拖出）丢进一个收集文件夹
2. 执行 `eml2md "收集文件夹" -o "输出文件夹"`
3. 新邮件来了 → 重复第 2 步，已转过的自动跳过，只处理新的
4. MD 文件进 Obsidian / 知识库归档；需要原件时加 `--keep-attachments`

## 六、常见问题

| 现象 | 处理 |
| --- | --- |
| 提示 `No Python at ...` | venv 坏了（如 QClaw 卸载导致），需重建 venv |
| 扫描件识别差 | 加 `--ocr-dpi 300`（更慢但更准） |
| 清华镜像装不上包 | 用 `-i https://mirrors.aliyun.com/pypi/simple` |
| 大附件卡住 | `--max-attachment-mb 50` 控制上限，或 `--skip-keywords` 过滤 |
| 电子书报"带有 DRM 版权保护" | 商店购买的正版电子书有加密，离线工具无法处理；改用无 DRM 版本 |
| 电子书转出来没有插图 | 按设计只提取文字，插图不参与转换 |
| MOBI 转出来没有标题层级 | 旧版 MOBI 本身缺少标题标签（源文件限制）；优先用 AZW3 或 EPUB 来源 |
| 同名 MD 没被更新 | 默认跳过已存在的 MD，加 `--overwrite` |

---

*环境：C:\Users\RS\.qclaw\workspace\eml2md\.venv314（Python 3.14 + markitdown 0.1.7 + RapidOCR + PyMuPDF + mobi 解包库）*
*入口：C:\Users\RS\bin\eml2md.cmd（另有 markitdown / rocr / ocr / pdfocr 辅助命令）*
*离线包：packaging\dist_v5\eml2md\（五个 EXE 共享一份 _internal）*
