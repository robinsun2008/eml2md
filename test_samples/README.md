eml2md Test Samples / 测试样本 (v8: EML + MSG + 电子书 + 扫描件表格)
====================================================================

【邮件样本】用 eml2md.exe 测试
  scan_test.eml     带扫描版 PDF 附件的邮件（核心测试：离线 OCR + 表格引擎）
  test_gb2312.eml   GB2312 编码的中文邮件（编码解码测试）
  _test_office.eml  混合附件：文字 PDF + 扫描 PDF + PPTX + 图片
  test_reply.msg    真实 Outlook MSG（中文主题/正文解码测试）
  test_report.msg   真实 Outlook MSG（含 xlsx 附件 + 内嵌图片 OCR）

【扫描件表格样本】v8 新增，用 doc2md.exe 测试 —— v8_tables\ 目录
  table_scan.pdf    图片型 PDF（无文本层），含一张 6 列采购验收表
  merged_scan.pdf   图片型 PDF，含跨行/跨列合并单元格的预算表
  table_scan.md     标准答案：6 列表格完整还原为 Markdown 表格
  merged_scan.md    标准答案：合并单元格自动回退 HTML（Markdown 语法无法表达）

【电子书样本】用 ebook2md.exe 或图形界面测试 —— ebooks\ 目录
  sample_book.epub      自制中文 EPUB（含标题层级/列表/表格）
  sample_with_img.epub  含插图的 EPUB（验证插图被丢弃、不产生死链）
  pg25332.epub          中文公版书（鲁迅《阿Ｑ正傳》）177 个标题层级
  pg25332_mobi.mobi     同一本书的旧版 MOBI 格式
  pg11.mobi             英文旧版 MOBI
  pg11-images-kf8.mobi  KF8 / AZW3 格式（标题结构最完整，20 个标题）

  expected\    本机生成的标准答案（.md），供逐字比对
  manual_cn.md 完整使用手册（中文）

离线电脑上的测试步骤
--------------------
1. 解压 eml2md_portable_v8.zip 到任意目录，例如 D:\eml2md\

2. 扫描件表格（v8 核心能力，先用这个验证）：

     D:\eml2md\doc2md.exe "test_samples\v8_tables\table_scan.pdf"
     D:\eml2md\doc2md.exe "test_samples\v8_tables\merged_scan.pdf" --keep-html

   期望：table_scan 输出完整 6 列 Markdown 表格；
         merged_scan 输出 <table> HTML（因为有合并单元格）

3. 邮件样本：

     D:\eml2md\eml2md.exe "test_samples\scan_test.eml" -o out
     D:\eml2md\eml2md.exe "test_samples\test_gb2312.eml" -o out
     D:\eml2md\eml2md.exe "test_samples\_test_office.eml" -o out
     D:\eml2md\eml2md.exe "test_samples\test_reply.msg" -o out
     D:\eml2md\eml2md.exe "test_samples\test_report.msg" -o out

4. 电子书样本（一次转换整个目录）：

     D:\eml2md\ebook2md.exe "test_samples\ebooks" -o out_books

5. 图形界面自测：双击 eml2md_gui.exe，把 test_samples\ebooks 拖进"目录批量转换"标签

判定标准
--------
扫描件表格（v8 新增）：
  * table_scan  -> 输出含 `| 序号 | 设备名称 | 型号 | 数量 | 单价（元） | 金额（元） |` 六列表头
                   各行数据（国产化服务器 / 万兆交换机 / …）在对应单元格内
  * merged_scan -> 输出为 <table> HTML（含 rowspan/colspan），内容不丢
  * table_scan --table-mode text  -> 表格变成 `单元格 | 单元格` 纯文本行
  * table_scan --table-mode off   -> ⚠️ 表格整块内容消失（这是有意行为，控制台会警告）

邮件部分：
  * scan_test.md   -> 附件部分出现 [OCR 识别 · 本地 RapidDoc（含表格识别）] 且能看到"设备采购验收报告"等文字
  * test_gb2312.md -> 标题"转发: 软件正版化"，中文姓名无乱码
  * _test_office.md -> 4 个附件全部转换；扫描 PDF 与图片带 [OCR 识别] 标记
  * test_reply.md  -> 标题"答复: 周会跟进"，中文完整
  * test_report.md -> xlsx 已转换 + image001.png 带 [OCR 识别] 标记

电子书部分：
  * sample_book.md        -> 4 个标题，含一个 Markdown 表格
  * sample_with_img.md    -> 全文不含 "![" 图片语法（插图按设计被丢弃）
  * pg25332.md            -> 177 个标题，中文完整无乱码（EPUB 最佳效果）
  * pg25332_mobi.md       -> 中文完整，但几乎没有标题（旧版 MOBI 的固有限制）
  * pg11-images-kf8.md    -> 20 个标题，章节目录完整（KF8/AZW3 效果最好）
  * pg11.md               -> 文字完整，无标题（旧版 MOBI）

其他：
  * 首次调用表格引擎会多等约 20 秒（加载模型），之后同一次运行内单页 2~4 秒
  * 电子书转换是纯离线解包+解析，不联网、不需要任何额外组件
  * 表格引擎全程离线（模型随包在 models\ 目录），不联网下载
  * 带 DRM 保护的正版电子书无法转换（这是唯一的能力边界）
