# -*- coding: utf-8 -*-
"""ebook2md.py — 电子书批量转 Markdown（EPUB / MOBI / AZW3 / AZW）。

复用 router 的电子书通道：
  * EPUB        由 markitdown 内置转换器直接解析（保留标题层级/列表/表格）
  * MOBI / AWZ3 先用 mobi 库解包（KF8 会还原成 EPUB），再走同一条通道
  * 插图不参与转换，只提取文字（避免指向包内资源的死链）

用法示例:
    ebook2md "某本书.epub"                      # 单本，MD 生成在源文件同目录
    ebook2md "D:\\电子书" -o "D:\\MD输出"        # 整个目录 → 统一输出目录（平铺）
    ebook2md "D:\\电子书" --delete --overwrite   # 转换后删源文件并覆盖旧 MD
"""
import argparse
import sys
import time
from pathlib import Path

# 源码直接运行时补齐模块搜索路径（router.py 依赖上一级的 pdfocr.py）；打包后无需处理
if not getattr(sys, "frozen", False):
    _HERE = Path(__file__).resolve().parent
    for _p in (str(_HERE), str(_HERE.parent)):
        if _p not in sys.path:
            sys.path.insert(0, _p)

import router as _router


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ebook2md",
        description="把 EPUB / MOBI / AZW3 / AZW 电子书转换为 Markdown（全程离线）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  ebook2md 书.epub                       转单本，MD 生成在同目录
  ebook2md D:\\电子书 -o D:\\MD            转整个目录（含子目录），统一输出
  ebook2md D:\\电子书 -o D:\\MD --delete   转换成功后删除源文件
  ebook2md D:\\电子书 --overwrite          覆盖旧 MD（默认跳过已转换过的）
""")
    p.add_argument("input", nargs="+",
                   help="电子书文件，或包含电子书的目录（可给多个）")
    p.add_argument("-o", "--output-dir", default=None,
                   help="统一输出目录（平铺，不保留子目录）；不给则 MD 与源文件同一目录")
    p.add_argument("--flat", action="store_true",
                   help="与 -o 等效（.md 平铺到输出目录，重名覆盖）；保留此参数仅为语义清晰")
    p.add_argument("--delete", action="store_true",
                   help="转换成功后删除源电子书文件")
    p.add_argument("--no-recursive", action="store_true",
                   help="只处理第一层，不进入子目录")
    p.add_argument("--overwrite", action="store_true",
                   help="覆盖已存在的 MD（默认跳过已转换过的文件）")
    return p


def collect_books(src: Path, recursive: bool) -> list[Path]:
    if src.is_file():
        return [src] if src.suffix.lower() in _router.BOOK_EXTS else []
    pattern = "**/*" if recursive else "*"
    return sorted(p for p in src.glob(pattern)
                  if p.is_file() and p.suffix.lower() in _router.BOOK_EXTS)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    books: list[Path] = []
    for item in args.input:
        src = Path(item).expanduser()
        if not src.exists():
            print(f"[错误] 路径不存在：{src}")
            return 2
        books.extend(collect_books(src, not args.no_recursive))

    if not books:
        print("[提示] 未找到电子书文件（支持 .epub/.mobi/.azw3/.azw/.kf8）")
        return 0

    # 去重（同一个文件被多次指定时只处理一次）
    seen = set()
    unique_books = []
    for b in books:
        key = b.resolve()
        if key not in seen:
            seen.add(key)
            unique_books.append(b)
    books = unique_books

    # -o 存在即平铺输出；否则 MD 与源文件同目录
    outdir = Path(args.output_dir).expanduser() if args.output_dir else None
    mode = "flat" if outdir is not None else "same"

    print(f"共找到 {len(books)} 本电子书，开始转换…\n")
    eng = _router.Router(log=lambda m: print(m))
    ok = skip = fail = 0
    t0 = time.time()

    for i, book in enumerate(books, 1):
        target = (outdir / (book.stem + ".md")) if mode == "flat" \
            else book.with_suffix(".md")
        if target.exists() and not args.overwrite:
            print(f"[{i}/{len(books)}] 跳过（MD 已存在）{book.name}")
            skip += 1
            continue

        status, out, msg = eng.convert(book, output_mode=mode,
                                       output_dir=outdir,
                                       keep_source=not args.delete)
        if status == "ok":
            size_kb = Path(out).stat().st_size / 1024
            print(f"[{i}/{len(books)}] ✓ {book.name} → {Path(out).name} "
                  f"({size_kb:.0f} KB)")
            ok += 1
        elif status == "skip":
            print(f"[{i}/{len(books)}] – 跳过 {book.name}")
            skip += 1
        else:
            print(f"[{i}/{len(books)}] ✗ 失败 {book.name}：{msg}")
            fail += 1

    print(f"\n完成：成功 {ok}，跳过 {skip}，失败 {fail}，"
          f"耗时 {time.time() - t0:.1f} 秒")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
