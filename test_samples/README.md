# 测试样本

用于验证转换正确性的样本与**标准答案**。`expected/` 中的 `.md` 是逐字比对基准。

## 已包含

| 样本 | 类型 | 说明 |
| --- | --- | --- |
| `scan_test.eml` | 邮件 | 合成样本：正文 + 扫描件 PDF 附件，验证编码解码与 **RapidOCR 识别** |
| `ebooks/sample_book.epub` | EPUB | 最小 EPUB，验证标题层级 |
| `ebooks/sample_with_img.epub` | EPUB | 含插图 EPUB，验证「只取文字」策略 |
| `ebooks/pg25332.epub` | EPUB | Project Gutenberg 公版书（中文） |
| `ebooks/pg11.mobi` | MOBI | 旧版 MOBI 格式（源文件无标题层级） |
| `ebooks/pg11-images-kf8.mobi` | KF8 | KF8 格式，解包为 EPUB 后转换 |
| `ebooks/pg25332_mobi.mobi` | MOBI | 由 EPUB 重新打包的 MOBI |

## 验证方法

```cmd
eml2md.exe  test_samples\scan_test.eml -o out
ebook2md.exe test_samples\ebooks -o out
:: 与 expected/ 下的同名 .md 逐字比对
```

## 未包含的样本

开发期还使用了 4 个**含真实内部信息**的邮件样本（GB2312 编码邮件、Office 附件邮件、两封 `.msg` 往来邮件），
出于隐私考虑未纳入本公开仓库。如需复现这些场景，可自行构造同类邮件：

- GB2312 编码：邮件头用 RFC 2047 编码，正文用 GB2312 + base64 / quoted-printable；
- 附件合并：在邮件中携带 PDF / PPT / 扫描件 / 图片附件；
- `.msg`：用 Outlook 保存任意邮件为 `.msg` 格式。
