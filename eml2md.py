# -*- coding: utf-8 -*-
"""
eml2md.py — 批量将 EML 邮件转换为无乱码的 Markdown，并把附件一并转换后合并进正文。

功能:
  1. 递归搜索指定路径下所有 *.eml 文件
  2. 正确解码邮件头 (RFC 2047 =?gb2312?B?...?=) 与正文 (base64 / quoted-printable, gb2312 等)
  3. 用 MarkItDown 将附件 (xlsx/docx/pdf/pptx/图片/csv/... ) 转换为 Markdown
  4. 正文 + 附件合并为「一个 EML → 一个 MD」的完整文件 (UTF-8 无 BOM)

用法:
  python eml2md.py <路径> [选项]

示例:
  python eml2md.py D:\\mail\\archive
  python eml2md.py D:\\mail\\a.eml -o D:\\out
  python eml2md.py D:\\mail --suffix .md --keep-attachments
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import re
import sys
from email import policy
from email.header import decode_header, Header
from email.message import Message
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.parser import BytesParser
from email.utils import parseaddr, getaddresses
from pathlib import Path

# ── 控制台编码（Windows 中文环境防乱码）─────────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# ── 依赖导入 ────────────────────────────────────────────────────────
try:
    from markitdown import MarkItDown
except Exception as exc:  # pragma: no cover
    print(f"[FATAL] 未安装 markitdown，请先: pip install 'markitdown[all]'\n{exc}")
    sys.exit(2)

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

try:
    from markdownify import markdownify as _markdownify
except Exception:
    _markdownify = None


# 常见中文邮件编码回退顺序
# latin-1 总是成功（ASCII 超集），永远不能作为自动回退，会把任意乱码字节误判为正确文本
CHARSET_FALLBACKS = ["utf-8", "utf-8-sig", "gb18030", "big5"]

# 这些 CTE 表示正文是"未编码"的纯文本，不需要 base64/qp 解码
RAW_CTE = {"", "7bit", "8bit", "binary"}

# 不作为附件展示的 MIME 类型
SKIP_MIME = {
    "application/pgp-signature",
    "application/pkcs7-signature",
    "application/x-pkcs7-signature",
}


# ── 通用工具 ────────────────────────────────────────────────────────
# RFC 2047 编码词： =?charset?B/Q?payload?=
_EW_RE = re.compile(r"=\?([^?]+)\?([BbQq])\?([^?]*?)\?=")


def _ew_bytes(charset: str, enc: str, payload: str) -> bytes:
    """把一个 RFC 2047 编码词解成原始字节（不处理 charset）。"""
    if enc.lower() == "b":
        try:
            return base64.b64decode(payload + "=" * (-len(payload) % 4))
        except Exception:
            return b""
    import quopri
    return quopri.decodestring(payload)


def decode_mime_words(value: str | None) -> str:
    """解码 RFC 2047 编码字符串，如 =?gb2312?B?Um9iaW4gU3VuIMvvvaE=?= 。

    比 email.header.decode_header 更容错：当发件方把一个多字节字符从中间切到
    相邻的两个编码词里（每个词单独解都会变成 U+FFFD）时，本函数会把 **相邻且同
    字符集** 的编码词先按字节拼接、再统一解码，从而还原被切断的字符；
    同时忽略相邻编码词之间的空白（符合 RFC 2047）。
    """
    if not value:
        return ""
    # 切成 编码词 / 字面文本 两类 token
    tokens: list[tuple] = []
    last = 0
    for m in _EW_RE.finditer(value):
        if m.start() > last:
            tokens.append(("lit", value[last:m.start()]))
        tokens.append(("ew", m.group(1), m.group(2), m.group(3)))
        last = m.end()
    if last < len(value):
        tokens.append(("lit", value[last:]))

    if not any(t[0] == "ew" for t in tokens):
        return value  # 没有编码词，原样返回

    out: list[str] = []
    buf = bytearray()
    buf_charset: str | None = None
    seen_ew = False

    def flush() -> None:
        nonlocal buf, buf_charset
        if buf or buf_charset:
            out.append(_decode_bytes(bytes(buf), buf_charset))
        buf = bytearray()
        buf_charset = None

    for tok in tokens:
        if tok[0] == "lit":
            txt = tok[1]
            # 相邻编码词之间的空白按 RFC 2047 忽略
            if seen_ew and not txt.strip():
                continue
            flush()
            out.append(txt)
        else:
            _, cs, enc, payload = tok
            cs_l = (cs or "utf-8").lower()
            if buf_charset is not None and cs_l != buf_charset:
                flush()
            if buf_charset is None:
                buf_charset = cs_l
            buf += _ew_bytes(cs, enc, payload)
            seen_ew = True
    flush()
    return "".join(out)


def _raw_header(msg: Message, name: str) -> str:
    """取未解码的原始头值（policy.default 下 get() 已自动解码，会丢失容错信息）。

    raw_items() 保留原始头（含 =?..?= 编码词与折行），展开折行后返回，
    交给 decode_mime_words 做容错解码。
    """
    vals = [v for k, v in msg.raw_items() if k.lower() == name.lower()]
    if not vals:
        return ""
    v = "".join(vals)
    # 展开折行：按 RFC 5322 只删 CRLF（保留续行前导空白），最后统一 strip 两端
    v = v.replace("\r\n", "").replace("\n", "").replace("\r", "")
    return v.strip()


def _decode_bytes(data: bytes, charset: str | None) -> str:
    """按声明的 charset 解码字节，失败时按常见中文编码回退。"""
    candidates: list[str] = []
    if charset:
        candidates.append(charset)
    candidates.extend(CHARSET_FALLBACKS)
    seen = set()
    for enc in candidates:
        if not enc:
            continue
        enc = enc.lower().strip()
        if enc in seen:
            continue
        seen.add(enc)
        try:
            text = data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        # 即使 decode 没抛异常，含 U+FFFD 仍说明该编码不完全正确（例如声明 utf-8
        # 但字节序列含非法序列，Python 会静默替换成 \ufffd 而不报错）。
        if "\ufffd" not in text:
            return text
        # 有 U+FFFD → 尝试后续回退（gb18030 通常能救回来）
    # 所有已知编码都失败/含 FFFD → 用 gb18030 最后兜底
    try:
        return data.decode("gb18030")
    except Exception:
        return data.decode("utf-8", errors="replace")


def html_to_markdown(html: str) -> str:
    """把 HTML 正文转成 Markdown。"""
    if not html or not html.strip():
        return ""
    # 先清理嵌入邮件签名块（防止混合编码乱码）
    html = _clean_embedded_headers(html)
    cleaned = html
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script", "style", "head", "title"]):
                tag.decompose()
            cleaned = str(soup)
        except Exception:
            cleaned = html
    if _markdownify is not None:
        try:
            md = _markdownify(cleaned, heading_style="ATX", strip=["style", "script"])
            return _tidy_markdown(md)
        except Exception:
            pass
    # 极简回退：去标签
    txt = re.sub(r"<[^>]+>", "", cleaned)
    return _tidy_markdown(txt)


def _decode_cte(raw, cte: str) -> bytes:
    """手动解 Content-Transfer-Encoding（base64 / quoted-printable）。"""
    if isinstance(raw, str):
        raw = raw.encode("latin-1")  # QP 字符串先转回字节
    if cte == "base64":
        return base64.b64decode(raw)
    if cte in ("quoted-printable", "quopri"):
        import quopri
        return quopri.decodestring(raw)
    return raw  # 7bit/8bit/binary 直接返回


def _recover_mojibake(mojibake: str) -> str | None:
    """把 email 库误用 UTF-8 解码（产生了乱码）的字符串逆转换回正确文本。

    原理：乱码 = 正确字节序列被错误地用 UTF-8 解码（应按 GB 系解码）。
    用 UTF-8 解码字符串得到的是 Latin-1 字节，再按 GB18030 解码即可还原。
    """
    try:
        corrupted_bytes = mojibake.encode("latin-1", errors="ignore")
        return corrupted_bytes.decode("gb18030", errors="ignore")
    except Exception:
        return None


def get_body_text(part: Message) -> str:
    """取 text/plain 正文内容，绕过 email 库的错误 charset 自动解码。"""
    cte = (part.get("Content-Transfer-Encoding") or "").strip().lower()
    raw = part.get_payload()
    if isinstance(raw, str):
        # email 库有时返回原始 QP 字符串（如 charset=utf-8 + CTE=quoted-printable），
        # 有时返回已解码字符串。这里统一走手动 CTE 解码路径。
        try:
            decoded = _decode_cte(raw.encode("latin-1"), cte)
            return _decode_bytes(decoded, part.get_content_charset())
        except Exception:
            pass
        # 如果还是乱码，尝试逆恢复
        recovered = _recover_mojibake(raw)
        return recovered if recovered else raw
    if not raw or isinstance(raw, list):
        return ""
    # raw 是字节 → 手动解 CTE
    try:
        decoded = _decode_cte(raw, cte)
        return _decode_bytes(decoded, part.get_content_charset())
    except Exception:
        return ""


def _get_html_body_bytes(part: Message) -> bytes | None:
    """取 HTML 正文的原始字节，手动解 CTE（不用 email 库自动解码）。"""
    cte = (part.get("Content-Transfer-Encoding") or "").strip().lower()
    raw = part.get_payload()
    if isinstance(raw, str):
        # 与 get_body_text 一致：先按 CTE 手动解码（QP/base64）。
        # policy.default 下 get_payload() 返回的是未解 CTE 的原始字符串。
        if cte:
            try:
                return _decode_cte(raw.encode("latin-1"), cte)
            except Exception:
                pass
        # 库可能已自动解码（无 CTE 或上面失败）→ 尝试逆乱码恢复
        recovered = _recover_mojibake(raw)
        if recovered is not None:
            return recovered.encode("utf-8", errors="replace")
        return raw.encode("utf-8", errors="replace")
    if not raw or isinstance(raw, list):
        return None
    try:
        return _decode_cte(raw, cte)
    except Exception:
        return None


# 匹配嵌入邮件头签名的各种写法（包括混合编码导致乱码的版本）
_EMAIL_HDR_RE = re.compile(
    r"(?im)^"
    r"['\"]?"
    r"(?P<label>From|Sent|To|Cc|Bcc|Subject|Date|发送时间|发件人|收件人|抄送|主题|日期)"
    r"['\"]?:\s*[^\n]{0,300}(?:\n|$)",
    re.MULTILINE,
)

# 附件签名块标记：<< File: xxx >>  或  <<File: xxx>>
_ATTACH_SIG_RE = re.compile(r"(?im)^\s*&lt;&lt;\s*File:\s*[^\n]{0,200}&gt;&gt;\s*$", re.MULTILINE)


def _clean_embedded_headers(html: str) -> str:
    """清理 HTML 正文中嵌入的邮件签名块，防止混合编码导致的乱码。

    邮件转发时，Outlook 等客户端会在正文中嵌入原始邮件头（From/Sent/To…），
    这些块在 HTML 里编码混乱，中文行用 GB2312、英文标签行用原始编码。
    直接解码会导致英文字段中的中文日期字符（如 `Sent: 2026年8月5日`）变成 `2026?`。
    本函数把这些签名块整体移除。
    """
    # 1. 清理附件标记行 << File: xxx >>
    html = _ATTACH_SIG_RE.sub("", html)
    # 2. 清理全角引号开头的行
    html = re.sub(r'^\s*[\u201C\u201D''"]+', "", html, flags=re.MULTILINE)
    # 3. 清理邮件头行（From: / Sent: / 发送时间: 等）
    html = _EMAIL_HDR_RE.sub("", html)
    # 4. 清理底部的横向分隔线（____ 开头的行）
    html = re.sub(r"^_{5,}\s*$", "", html, flags=re.MULTILINE)
    # 5. 清理邮件头后紧跟的空行（避免产生多余空段）
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def html_to_markdown(html: str) -> str:
    """把 HTML 正文转成 Markdown。"""
    if not html or not html.strip():
        return ""
    # 先清理嵌入邮件签名块（防止混合编码乱码）
    html = _clean_embedded_headers(html)
    cleaned = html
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script", "style", "head", "title"]):
                tag.decompose()
            cleaned = str(soup)
        except Exception:
            cleaned = html
    if _markdownify is not None:
        try:
            md = _markdownify(cleaned, heading_style="ATX", strip=["style", "script"])
            return _tidy_markdown(md)
        except Exception:
            pass
    # 极简回退：去标签
    txt = re.sub(r"<[^>]+>", "", cleaned)
    return _tidy_markdown(txt)


def _tidy_markdown(text: str) -> str:
    """清理多余空行与首尾空白。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# CJK 汉字与全角标点范围（用于清理 HTML 标签引入的多余空格）
_CJK_RANGE = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_FW_RANGE = r"\u3000-\u303f\uff01-\uff5e"


def _squeeze_cjk_spaces(text: str) -> str:
    """去掉 HTML 转 Markdown 时因标签边界引入的多余空格。

    例如 ``赞同 <span>UPS</span> 统一`` 会被转成 ``赞同 UPS 统一``；
    这里只压缩中日韩文字/全角标点之间的空格，不影响英文单词间的正常空格。
    """
    t = text
    # 汉字 ↔ 汉字
    t = re.sub(rf"(?<=[{_CJK_RANGE}])[ \t]+(?=[{_CJK_RANGE}])", "", t)
    # 汉字 ↔ 全角标点
    t = re.sub(rf"(?<=[{_CJK_RANGE}])[ \t]+(?=[{_FW_RANGE}])", "", t)
    t = re.sub(rf"(?<=[{_FW_RANGE}])[ \t]+(?=[{_CJK_RANGE}])", "", t)
    # 数字/字母 ↔ 全角标点
    t = re.sub(rf"[ \t]+(?=[{_FW_RANGE}])", "", t)
    t = re.sub(rf"(?<=[{_FW_RANGE}])[ \t]+(?=[0-9A-Za-z])", "", t)
    # 全角左括号/引号后、右括号/引号前的空格
    t = re.sub(r"(?<=[（《“”‘’\[【])[ \t]+", "", t)
    t = re.sub(r"[ \t]+(?=[）》。，、；：？！》”’\]】])", "", t)
    return t


def iter_leaf_parts(msg: Message):
    """遍历所有叶子 MIME 部分。

    遇到 message/rfc822 时把它当作一个整体（附件）产出，不再深入其内部，
    避免被转发邮件的正文/附件泄漏进外层邮件。
    """
    if msg.is_multipart():
        for part in msg.get_payload():
            if part.get_content_type() == "message/rfc822":
                yield part
            elif part.is_multipart():
                yield from iter_leaf_parts(part)
            else:
                yield part
    else:
        yield msg


def format_addresses(raw: str | None) -> str:
    """把地址列表格式化：名 名 <addr>, 名 <addr> 。"""
    if not raw:
        return ""
    raw = decode_mime_words(raw)
    items: list[str] = []
    try:
        for name, addr in getaddresses([raw]):
            name = name.strip()
            addr = addr.strip()
            if name and addr:
                # 名字本身可能再做一次解码
                name = decode_mime_words(name)
                items.append(f"{name} <{addr}>")
            elif addr:
                items.append(addr)
            elif name:
                items.append(name)
    except Exception:
        return raw
    return ", ".join(items)


def safe_filename(name: str) -> str:
    """去掉文件名中的非法字符。"""
    name = decode_mime_words(name) if name else ""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name)
    return name.strip().strip(".")


def guess_extension(filename: str, content_type: str) -> str:
    """推断附件扩展名，供 markitdown 选择转换器。"""
    ext = Path(filename).suffix.lower()
    if ext:
        return ext
    ctype = (content_type or "").lower()
    mapping = {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.ms-powerpoint": ".ppt",
        "text/csv": ".csv",
        "text/plain": ".txt",
        "text/html": ".html",
        "application/json": ".json",
        "application/zip": ".zip",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "message/rfc822": ".eml",
    }
    return mapping.get(ctype, "")


# ── MSG → EML（内存转换，复用 EML 管线）──────────────────────────
def _rtf_to_text(rtf: bytes) -> str:
    """极简 RTF 剥壳：去掉控制词与花括号，保留可读文本（兜底用）。"""
    txt = rtf.decode("ascii", "ignore")
    txt = re.sub(r"\{\\\*[^{}]*\}", "", txt)          # {\*\...} 目的组
    txt = re.sub(r"\\'([0-9a-fA-F]{2})", "", txt)     # 十六进制转义
    txt = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", txt)      # 控制词
    txt = re.sub(r"[{}]", "", txt)                    # 剩余花括号
    txt = txt.replace("\\", "")
    return re.sub(r"\n{3,}", "\n\n", txt).strip()


def msg_to_eml_bytes(msg_path: Path) -> bytes:
    """把 Outlook .msg（CFB 格式）解析后重组为标准 .eml 字节流。

    这样 MSG 邮件即可完整复用 eml_to_markdown 的既有管线：
    编码回退、正文择优、附件转换、扫描件 OCR、嵌套邮件递归……
    """
    import extract_msg

    with extract_msg.openMsg(str(msg_path)) as m:
        outer = MIMEMultipart("mixed")

        subject = str(m.subject or "").strip()
        if subject:
            outer["Subject"] = Header(subject, "utf-8").encode()

        # 发件人：显示名 + 邮箱地址
        sender = str(m.sender or "").strip()
        sender_email = str(getattr(m, "senderEmail", "") or "").strip()
        if sender and sender_email and sender_email not in sender:
            sender = f"{sender} <{sender_email}>"
        elif not sender and sender_email:
            sender = sender_email
        if sender:
            outer["From"] = sender
        if m.to:
            outer["To"] = Header(str(m.to), "utf-8").encode()
        if m.cc:
            outer["CC"] = Header(str(m.cc), "utf-8").encode()
        if m.date:
            outer["Date"] = str(m.date)

        # 正文：优先 HTML，其次纯文本，最后 RTF 剥壳兜底
        html = ""
        if m.htmlBody:
            html = (m.htmlBody.decode("utf-8", "replace")
                    if isinstance(m.htmlBody, bytes) else str(m.htmlBody))
        plain = str(m.body or "")
        if html.strip():
            alt = MIMEMultipart("alternative")
            if plain.strip():
                alt.attach(MIMEText(plain, "plain", "utf-8"))
            alt.attach(MIMEText(html, "html", "utf-8"))
            outer.attach(alt)
        elif plain.strip():
            outer.attach(MIMEText(plain, "plain", "utf-8"))
        elif m.rtfBody:
            outer.attach(MIMEText(_rtf_to_text(m.rtfBody), "plain", "utf-8"))

        # 附件：统一按标准附件挂载（内嵌签名图标也会包含，转换后可辨）
        for att in m.attachments:
            try:
                data = att.data
            except Exception:
                continue
            if not data:
                continue
            if isinstance(data, str):
                data = data.encode("utf-8", "replace")
            name = (att.longFilename or att.shortFilename or att.name
                    or "attachment.bin")
            part = MIMEApplication(data)
            try:
                part.add_header("Content-Disposition", "attachment",
                                filename=Header(str(name), "utf-8").encode())
            except Exception:
                part.add_header("Content-Disposition", "attachment",
                                filename="attachment.bin")
            outer.attach(part)

    return outer.as_bytes()


# ── 一个 EML → Markdown ─────────────────────────────────────────────
def eml_to_markdown(eml_path: Path, md: MarkItDown, opts: argparse.Namespace,
                    source_name: str | None = None,
                    raw: bytes | None = None) -> str:
    raw = eml_path.read_bytes() if raw is None else raw
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    lines: list[str] = []

    # ── 邮件头 ──────────────────────────────────────────────────
    subject = decode_mime_words(_raw_header(msg, "Subject")) or "(无主题)"
    date = decode_mime_words(_raw_header(msg, "Date")) or ""
    frm = format_addresses(_raw_header(msg, "From"))
    to = format_addresses(_raw_header(msg, "To"))
    cc = format_addresses(_raw_header(msg, "CC"))

    lines.append(f"# {subject}")
    lines.append("")
    lines.append("| 字段 | 内容 |")
    lines.append("| --- | --- |")
    lines.append(f"| 发件人 | {frm} |")
    if to:
        lines.append(f"| 收件人 | {to} |")
    if cc:
        lines.append(f"| 抄送 | {cc} |")
    if date:
        lines.append(f"| 日期 | {date} |")
    lines.append(f"| 来源文件 | {source_name or eml_path.name} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 收集正文与附件 ──────────────────────────────────────────
    body_text = ""
    body_html = ""
    attachments: list[tuple[str, str, bytes]] = []  # (filename, ext, data)
    nested_emls: list[tuple[str, bytes]] = []

    for part in iter_leaf_parts(msg):
        ctype = part.get_content_type()
        disp = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()

        if ctype in SKIP_MIME:
            continue

        # 嵌套邮件（作为附件转发的邮件）——整体当作附件，不深入其内部
        if ctype == "message/rfc822":
            payload = part.get_payload()
            if isinstance(payload, list) and payload:
                nested_raw = payload[0].as_bytes()
                nested_emls.append((safe_filename(filename or "转发邮件.eml"), nested_raw))
            continue

        if disp == "attachment":
            is_attachment = True
        elif filename is not None and ctype not in ("text/plain", "text/html"):
            # inline 图片/签名图标默认跳过，除非显式要求
            is_attachment = (disp != "inline") or opts.include_inline
        else:
            is_attachment = False

        if is_attachment:
            data = part.get_payload(decode=True)
            if data is None:
                continue
            if len(data) > opts.max_attachment_mb * 1024 * 1024:
                attachments.append((safe_filename(filename or "attachment"), "", 
                                    f"[附件过大，已跳过: {len(data)//1024//1024} MB]".encode("utf-8")))
                continue
            name = safe_filename(filename or f"attachment{guess_extension('', ctype)}")
            ext = guess_extension(name, ctype)
            attachments.append((name, ext, data))
            continue

        # 正文部分
        if ctype == "text/plain" and not body_text:
            body_text = get_body_text(part)
        elif ctype == "text/html" and not body_html:
            raw_bytes = _get_html_body_bytes(part)
            body_html = _decode_bytes(raw_bytes, part.get_content_charset()) if raw_bytes else ""
            # HTML 正文里的 QP 也需要解码（但 _get_html_body_bytes 已处理）

    # ── 正文选择 ────────────────────────────────────────────────
    # 优先纯文本；但若纯文本已损坏（含 U+FFFD 替换符）而 HTML 更干净，
    # 则改用 HTML 正文（部分发件端生成的纯文本会把表格/标点搞成 “U+FFFD+?”）。
    plain_md = _tidy_markdown(body_text) if body_text.strip() else ""
    html_md = _squeeze_cjk_spaces(html_to_markdown(body_html)) if body_html.strip() else ""
    plain_bad = plain_md.count("\ufffd")
    html_bad = html_md.count("\ufffd")
    if plain_md and html_md:
        if html_bad < plain_bad:
            body_md = html_md
            print(f"      · 纯文本正文含{plain_bad}处损坏字符(U+FFFD)，已改用 HTML 正文")
        else:
            body_md = plain_md
    else:
        body_md = plain_md or html_md

    lines.append("## 正文")
    lines.append("")
    lines.append(body_md if body_md else "*(无正文)*")
    lines.append("")

    # ── 附件清单 ────────────────────────────────────────────────
    all_names = [a[0] for a in attachments] + [n[0] for n in nested_emls]
    lines.append("---")
    lines.append("")
    if all_names:
        lines.append("## 附件清单")
        lines.append("")
        for i, n in enumerate(all_names, 1):
            lines.append(f"{i}. {n}")
        lines.append("")
    else:
        lines.append("## 附件清单")
        lines.append("")
        lines.append("*(无附件)*")
        lines.append("")

    # ── 逐个附件转换 ────────────────────────────────────────────
    idx = 0
    for name, ext, data in attachments:
        idx += 1
        lines.append("---")
        lines.append("")
        lines.append(f"## 附件 {idx}: {name}")
        lines.append("")
        if not ext:
            lines.append(f"> 无法识别的附件类型，跳过转换（{len(data)} 字节）。")
            lines.append("")
            continue
        if opts.keep_attachments and opts.output_dir is not None:
            att_dir = opts.output_dir / (eml_path.stem + "_attachments")
            att_dir.mkdir(parents=True, exist_ok=True)
            (att_dir / name).write_bytes(data)
        lines.append(_convert_attachment(md, data, ext, name, opts))
        lines.append("")

    # ── 嵌套邮件递归 ────────────────────────────────────────────
    for name, nested_raw in nested_emls:
        idx += 1
        lines.append("---")
        lines.append("")
        lines.append(f"## 附件 {idx}: {name} (转发的邮件)")
        lines.append("")
        tmp = opts.output_dir / f".__nested_{os.getpid()}_{idx}.eml" if opts.output_dir else None
        try:
            if tmp is not None:
                tmp.write_bytes(nested_raw)
                nested_md = eml_to_markdown(tmp, md, opts, source_name=name)
            else:
                nested_md = _eml_bytes_to_markdown(nested_raw, md, opts, name)
            # 降一级标题，避免与本文档标题冲突
            nested_md = "\n".join(
                ("#" + ln) if ln.startswith("#") else ln for ln in nested_md.splitlines()
            )
            lines.append(nested_md)
        except Exception as exc:
            lines.append(f"> 嵌套邮件转换失败: {exc}")
        finally:
            if tmp is not None and tmp.exists():
                tmp.unlink()
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _eml_bytes_to_markdown(raw: bytes, md: MarkItDown, opts: argparse.Namespace, name: str) -> str:
    """内存中的 EML 字节 → Markdown（用于嵌套邮件，避免临时文件）。"""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".eml", delete=False) as tf:
        tf.write(raw)
        tmp_path = Path(tf.name)
    try:
        return eml_to_markdown(tmp_path, md, opts, source_name=name)
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass


def clean_table_artifacts(text: str) -> str:
    """清理 MarkItDown 处理 xlsx 时由 pandas 产生的表格噪声。

    - 单元格值为 NaN  → 置空
    - 整行全空的表格行 → 删除
    """
    if "NaN" not in text:
        return text
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.count("|") >= 2):
            out.append(line)
            continue
        cells = line.split("|")[1:-1]
        # 判定分隔行（---）
        is_sep = all(
            c.strip() and set(c.strip()) <= set("-: ")
            for c in cells
        )
        new_cells = []
        for c in cells:
            cs = c.strip()
            if cs == "NaN":
                cs = ""
            new_cells.append(f" {cs} " if cs else "  ")
        if not is_sep and all(not c.strip() for c in new_cells):
            continue  # 丢弃整行空行
        out.append("|" + "|".join(new_cells) + "|")
    return "\n".join(out)


# ── OCR（本地 RapidOCR，离线免费）────────────────────────────────
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}

_OCR_ENGINE = None


def ocr_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def ocr_image(img) -> str:
    """对单张图像 OCR。img 可为 PIL.Image 或 numpy ndarray。"""
    import numpy as np
    from PIL import Image
    if isinstance(img, Image.Image):
        img = np.array(img.convert("RGB"))
    res, _ = _get_ocr_engine()(img)
    if not res:
        return ""
    return "\n".join(r[1] for r in res if len(r) >= 2 and r[1])


def ocr_image_bytes(data: bytes) -> str:
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        return ocr_image(im)


def ocr_pdf_bytes(data: bytes, dpi: int) -> str:
    """扫描版 PDF：逐页渲染为图片后 OCR。"""
    import pymupdf  # PyMuPDF
    from PIL import Image
    doc = pymupdf.open(stream=data, filetype="pdf")
    parts: list[str] = []
    try:
        for i, page in enumerate(doc, 1):
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            txt = ocr_image(img)
            if txt:
                parts.append(f"<!-- 第 {i} 页 -->\n{txt}")
    finally:
        doc.close()
    return "\n\n".join(parts)


def ocr_zip_media(data: bytes, prefix: str) -> str:
    """OCR Office 压缩包内的图片（ppt/media 等），用于图片型文档兜底。"""
    import zipfile
    texts: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                if name.startswith(prefix) and Path(name).suffix.lower() in IMAGE_EXTS:
                    try:
                        t = ocr_image_bytes(z.read(name))
                    except Exception:
                        t = ""
                    if t:
                        texts.append(t)
    except Exception:
        return ""
    return "\n\n".join(texts)


def _tag_ocr(text: str) -> str:
    return f"> **[OCR 识别 · 本地 RapidOCR]**\n\n{text}"


def _md_convert(md: MarkItDown, data: bytes, ext: str) -> str:
    result = md.convert_stream(io.BytesIO(data), file_extension=ext)
    return (result.text_content or "").strip()


def _convert_attachment(md: MarkItDown, data: bytes, ext: str, name: str,
                        opts: argparse.Namespace) -> str:
    """转换附件：文本类走 MarkItDown；扫描件 / 图片走本地 OCR。"""
    ext = ext.lower()
    ocr_on = (not opts.no_ocr) and ocr_available()

    # 命中关键词 → 跳过转换，直接引用文件名
    if opts.skip_keywords:
        name_lower = name.lower()
        if any(kw in name_lower for kw in opts.skip_keywords):
            return f"> 附件 `{name}`（已按关键词过滤，跳过转换）"

    # ① 纯图片 → 直接 OCR
    if ext in IMAGE_EXTS:
        if ocr_on:
            print(f"      · OCR 图片: {name}")
            try:
                t = ocr_image_bytes(data)
            except Exception as exc:
                print(f"      ! OCR 失败: {type(exc).__name__}: {exc}")
                t = ""
            if t.strip():
                return _tag_ocr(_tidy_markdown(t))
        try:
            t = _md_convert(md, data, ext)
        except Exception as exc:
            return f"> 附件 `{name}` 转换失败: {type(exc).__name__}: {exc}"
        return t if t.strip() else f"> 附件 `{name}` 未识别到文字。"

    # ② 其他类型 → MarkItDown
    try:
        text = _md_convert(md, data, ext)
    except Exception as exc:
        return f"> 附件 `{name}` 转换失败: {type(exc).__name__}: {exc}"

    # ③ 扫描版 PDF 兜底
    if ext == ".pdf" and ocr_on and len(text.strip()) < opts.ocr_pdf_min_chars:
        print(f"      · OCR 扫描版 PDF: {name}")
        try:
            ocr_t = ocr_pdf_bytes(data, opts.ocr_dpi)
        except Exception as exc:
            print(f"      ! OCR 失败: {type(exc).__name__}: {exc}")
            ocr_t = ""
        if ocr_t.strip():
            ocr_t = _tag_ocr(_tidy_markdown(ocr_t))
            text = f"{text}\n\n{ocr_t}" if text.strip() else ocr_t

    # ④ 图片型 Office 文档兜底
    if ext in (".pptx", ".docx", ".xlsx") and ocr_on and len(text.strip()) < opts.ocr_office_min_chars:
        prefix = {".pptx": "ppt/media/", ".docx": "word/media/", ".xlsx": "xl/media/"}[ext]
        print(f"      · OCR {ext} 内嵌图片: {name}")
        try:
            ocr_t = ocr_zip_media(data, prefix)
        except Exception as exc:
            print(f"      ! OCR 失败: {type(exc).__name__}: {exc}")
            ocr_t = ""
        if ocr_t.strip():
            ocr_t = _tag_ocr(_tidy_markdown(ocr_t))
            text = f"{text}\n\n{ocr_t}" if text.strip() else ocr_t

    if not text.strip():
        return f"> 附件 `{name}` 无可用文本内容（OCR 也未识别到文字）。"
    if not opts.keep_nan:
        text = clean_table_artifacts(text)
    return text


# ── 目录扫描 ────────────────────────────────────────────────────────
def find_eml_files(root: Path, recursive: bool) -> list[Path]:
    """查找 .eml 与 .msg 邮件文件（大小写均匹配），去重后排序。"""
    suffixes = (".eml", ".msg")
    if recursive:
        files = [p for p in root.glob("**/*") if p.is_file()
                 and p.suffix.lower() in suffixes]
    else:
        files = [p for p in root.glob("*") if p.is_file()
                 and p.suffix.lower() in suffixes]
    uniq = sorted({p.resolve() for p in files})
    return uniq


# ── 主流程 ──────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(
        description="批量将 EML 转为无乱码、含附件内容的 Markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("path", help="EML 文件或包含 EML 的目录")
    ap.add_argument("-o", "--output-dir", default=None,
                    help="输出目录（默认与源 EML 同目录）")
    ap.add_argument("--suffix", default=".md", help="输出后缀（默认 .md）")
    ap.add_argument("--no-recursive", action="store_true", help="不递归子目录")
    ap.add_argument("--overwrite", action="store_true",
                    help="覆盖已存在的同名 MD（默认跳过）")
    ap.add_argument("--keep-attachments", action="store_true",
                    help="同时把附件原文件另存到 <输出>/<邮件名>_attachments/")
    ap.add_argument("--max-attachment-mb", type=int, default=50,
                    help="单个附件大小上限 MB（默认 50，超出仅记录不转换）")
    ap.add_argument("--include-inline", action="store_true",
                    help="把内嵌(inline)图片也当作附件转换（默认跳过签名图标）")
    ap.add_argument("--keep-nan", action="store_true",
                    help="保留 xlsx 空单元格的 NaN（默认清理为空白）")
    ap.add_argument("--no-ocr", action="store_true",
                    help="禁用 OCR（默认对扫描版PDF/图片自动启用本地 OCR）")
    ap.add_argument("--ocr-dpi", type=int, default=200,
                    help="扫描版 PDF 渲染 DPI（默认 200，越高越准越慢）")
    ap.add_argument("--ocr-pdf-min-chars", type=int, default=20,
                    help="PDF 提取文本少于该字符数时改用 OCR（默认 20）")
    ap.add_argument("--ocr-office-min-chars", type=int, default=20,
                    help="Office 文档文本少于该字符数时补充 OCR 内嵌图片（默认 20）")
    ap.add_argument("--skip-keywords", nargs="*", default=[],
                    help="附件文件名命中任一关键词（不分大小写）则跳过转换，直接保留文件名引用。最多 7 个。")
    opts = ap.parse_args()

    if len(opts.skip_keywords) > 7:
        print("[ERROR] --skip-keywords 最多 7 个关键词")
        return 1
    skip_kws = [kw.lower() for kw in opts.skip_keywords]  # 大小写不敏感

    root = Path(opts.path).expanduser()
    if not root.exists():
        print(f"[ERROR] 路径不存在: {root}")
        return 1

    opts.output_dir = Path(opts.output_dir).expanduser() if opts.output_dir else None
    if opts.output_dir:
        opts.output_dir.mkdir(parents=True, exist_ok=True)

    if root.is_file():
        eml_files = ([root.resolve()]
                     if root.suffix.lower() in (".eml", ".msg") else [])
    else:
        eml_files = find_eml_files(root, recursive=not opts.no_recursive)

    if not eml_files:
        print(f"[WARN] 未找到任何 .eml/.msg 文件: {root}")
        return 0

    print(f"共找到 {len(eml_files)} 个 EML/MSG 文件，开始转换...")
    if opts.no_ocr:
        print("OCR: 已禁用 (--no-ocr)")
    elif ocr_available():
        print("OCR: 已启用（本地 RapidOCR，离线免费）")
    else:
        print("OCR: 未安装 → 扫描版PDF/图片将无法识别。安装: pip install rapidocr-onnxruntime pymupdf\n")
    print()
    md = MarkItDown(enable_plugins=False)

    ok = fail = 0
    for i, eml in enumerate(eml_files, 1):
        try:
            raw = None
            if eml.suffix.lower() == ".msg":
                raw = msg_to_eml_bytes(eml)
            content = eml_to_markdown(eml, md, opts, raw=raw)
        except Exception as exc:
            fail += 1
            print(f"[{i}/{len(eml_files)}] ✗ {eml.name}  失败: {type(exc).__name__}: {exc}")
            continue

        if opts.output_dir:
            out = opts.output_dir / (eml.stem + opts.suffix)
        else:
            out = eml.with_suffix(opts.suffix)
        if out.exists() and not opts.overwrite:
            print(f"[{i}/{len(eml_files)}] - {eml.name}  已存在，跳过")
            continue
        out.write_text(content, encoding="utf-8", newline="\n")
        ok += 1
        print(f"[{i}/{len(eml_files)}] ✓ {eml.name}  →  {out}")

    print(f"\n完成：成功 {ok} 个，失败 {fail} 个。")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
