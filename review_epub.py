#!/usr/bin/env python3
"""
EPUB Chapter Reviewer
Extracts chapters from a bilingual EPUB and opens them in the browser for review.

Usage:
  review_epub.py <epub_path> --list
  review_epub.py <epub_path> --open 1,3,5
  review_epub.py <epub_path> --compare <epub2_path> --chapter 3
"""

import argparse
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import warnings
try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:
    pass


# ---------------------------------------------------------------------------
# EPUB parsing
# ---------------------------------------------------------------------------

def _parse_epub(epub_path: str) -> tuple[list[dict], zipfile.ZipFile]:
    zf = zipfile.ZipFile(epub_path)
    container = zf.read("META-INF/container.xml").decode("utf-8")
    root = ET.fromstring(container)
    ns = "urn:oasis:names:tc:opendocument:xmlns:container"
    rootfile = root.find(f".//{{{ns}}}rootfile")
    opf_path = rootfile.get("full-path", "")
    opf_base = os.path.dirname(opf_path)

    opf = zf.read(opf_path).decode("utf-8")
    root = ET.fromstring(opf)
    OPF_NS = "http://www.idpf.org/2007/opf"

    manifest = {}
    for item in root.findall(f".//{{{OPF_NS}}}item"):
        item_id = item.get("id", "")
        href = item.get("href", "")
        media_type = item.get("media-type", "")
        full_path = os.path.normpath(os.path.join(opf_base, href)).replace("\\", "/") if opf_base else href
        manifest[item_id] = {"media_type": media_type, "full_path": full_path}

    spine = []
    for itemref in root.findall(f".//{{{OPF_NS}}}itemref"):
        idref = itemref.get("idref", "")
        if idref in manifest and manifest[idref]["media_type"] == "application/xhtml+xml":
            spine.append(manifest[idref]["full_path"])

    chapters = []
    for i, path in enumerate(spine):
        try:
            html = zf.read(path).decode("utf-8", errors="replace")
            title = _extract_title(html) or path.split("/")[-1]
            has_bilingual = "epub-translation" in html
            word_count = len(re.findall(r'\w+', re.sub(r'<[^>]+>', '', html)))
        except Exception:
            title = path.split("/")[-1]
            has_bilingual = False
            word_count = 0
        chapters.append({
            "num": i + 1,
            "path": path,
            "title": title[:60],
            "has_bilingual": has_bilingual,
            "word_count": word_count,
        })
    return chapters, zf


def _extract_title(html: str) -> str:
    for pattern in [r'<h1[^>]*>(.*?)</h1>', r'<h2[^>]*>(.*?)</h2>', r'<title[^>]*>(.*?)</title>']:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if m:
            t = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if t:
                return t
    return ""


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(epub_path: str):
    chapters, zf = _parse_epub(epub_path)
    zf.close()
    book_name = Path(epub_path).stem
    print(f"\n《{book_name}》— 共 {len(chapters)} 章\n")
    for ch in chapters:
        tag = "[双语]" if ch["has_bilingual"] else "[无译文]"
        print(f"  {ch['num']:3}.  {tag}  {ch['title']}")
    print()


def cmd_open(epub_path: str, chapter_nums: list[int]):
    chapters, zf = _parse_epub(epub_path)
    selected = [ch for ch in chapters if ch["num"] in chapter_nums]
    if not selected:
        print(f"[错误] 未找到指定章节: {chapter_nums}", file=sys.stderr)
        zf.close()
        return 1

    book_name = Path(epub_path).stem
    sections_html = []

    for ch in selected:
        try:
            raw_html = zf.read(ch["path"]).decode("utf-8", errors="replace")
            body = _extract_body(raw_html)
        except Exception as e:
            body = f"<p>[读取失败: {e}]</p>"

        sections_html.append(f"""
<div class="chapter-section" id="ch{ch['num']}">
  <div class="chapter-label">第 {ch['num']} 章 · {ch['title']}</div>
  {body}
</div>""")

    zf.close()

    nav_links = " &nbsp;|&nbsp; ".join(
        f'<a href="#ch{ch["num"]}">第{ch["num"]}章</a>' for ch in selected
    )
    nav = f'<div class="chapter-nav">📖 {book_name} &nbsp;&nbsp; {nav_links}</div>' if len(selected) > 1 else f'<div class="chapter-nav">📖 {book_name} · 第 {selected[0]["num"]} 章 · {selected[0]["title"]}</div>'

    page = _wrap_html(book_name, nav, "\n".join(sections_html))
    out_path = f"/tmp/epub_review_{Path(epub_path).stem[:20]}.html"
    Path(out_path).write_text(page, encoding="utf-8")
    subprocess.run(["open", out_path])
    print(f"[预览] 已在浏览器打开: {out_path}")
    return 0


def cmd_compare(epub1: str, epub2: str, chapter_num: int):
    chapters1, zf1 = _parse_epub(epub1)
    chapters2, zf2 = _parse_epub(epub2)

    ch1 = next((c for c in chapters1 if c["num"] == chapter_num), None)
    ch2 = next((c for c in chapters2 if c["num"] == chapter_num), None)

    if not ch1 or not ch2:
        print(f"[错误] 找不到第 {chapter_num} 章", file=sys.stderr)
        zf1.close(); zf2.close()
        return 1

    body1 = _extract_body(zf1.read(ch1["path"]).decode("utf-8", errors="replace"))
    body2 = _extract_body(zf2.read(ch2["path"]).decode("utf-8", errors="replace"))
    zf1.close(); zf2.close()

    label1 = Path(epub1).stem[:40]
    label2 = Path(epub2).stem[:40]

    compare_html = f"""
<div class="compare-header">
  <div class="compare-label">📄 {label1}</div>
  <div class="compare-label">📄 {label2}</div>
</div>
<div class="compare-grid">
  <div class="compare-col">{body1}</div>
  <div class="compare-col">{body2}</div>
</div>"""

    nav = f'<div class="chapter-nav">🔍 对比 · 第 {chapter_num} 章</div>'
    page = _wrap_html("对比预览", nav, compare_html, compare_mode=True)
    out_path = f"/tmp/epub_compare_ch{chapter_num}.html"
    Path(out_path).write_text(page, encoding="utf-8")
    subprocess.run(["open", out_path])
    print(f"[对比] 已在浏览器打开: {out_path}")
    return 0


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _extract_body(html: str) -> str:
    m = re.search(r'<body[^>]*>(.*?)</body>', html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else html


def _wrap_html(title: str, nav: str, content: str, compare_mode: bool = False) -> str:
    compare_css = """
    .compare-header { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 10px; }
    .compare-label { font-weight: bold; color: #555; font-size: 0.85em; padding: 8px 12px; background: #f0f0f0; border-radius: 4px; }
    .compare-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    .compare-col { border: 1px solid #e0e0e0; border-radius: 6px; padding: 20px; }
    """ if compare_mode else ""

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{
      max-width: {'1400px' if compare_mode else '780px'};
      margin: 0 auto;
      padding: 20px 24px 60px;
      font-family: "Georgia", "Noto Serif SC", serif;
      line-height: 1.9;
      color: #222;
      background: #fafafa;
    }}
    .chapter-nav {{
      position: sticky;
      top: 0;
      background: rgba(250,250,250,0.95);
      padding: 10px 16px;
      border-bottom: 1px solid #ddd;
      margin-bottom: 32px;
      font-size: 0.88em;
      color: #555;
      z-index: 100;
    }}
    .chapter-nav a {{ color: #0066cc; text-decoration: none; }}
    .chapter-nav a:hover {{ text-decoration: underline; }}
    .chapter-section {{ margin-bottom: 60px; padding-bottom: 40px; border-bottom: 2px solid #eee; }}
    .chapter-label {{ color: #aaa; font-size: 0.82em; letter-spacing: 0.05em; margin-bottom: 28px; padding-bottom: 10px; border-bottom: 1px solid #eee; }}
    .epub-original {{ color: #1a1a1a; }}
    .epub-translation {{ color: #888888; font-size: 0.92em; margin-top: 0.1em; margin-bottom: 0.8em; }}
    h1, h2, h3 {{ color: #111; }}
    {compare_css}
  </style>
</head>
<body>
{nav}
{content}
</body>
</html>"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="EPUB 章节预览工具")
    parser.add_argument("epub", help="双语 EPUB 文件路径")
    parser.add_argument("--list", action="store_true", help="列出所有章节")
    parser.add_argument("--open", metavar="CHAPTERS", help="打开指定章节，逗号分隔，如 1,3,5 或 2-6")
    parser.add_argument("--compare", metavar="EPUB2", help="对比另一个 EPUB 的同一章节")
    parser.add_argument("--chapter", type=int, help="对比时指定章节编号")
    args = parser.parse_args()

    if not os.path.exists(args.epub):
        print(f"[错误] 文件不存在: {args.epub}", file=sys.stderr)
        return 1

    if args.list:
        cmd_list(args.epub)
        return 0

    if args.open:
        nums = _parse_chapter_range(args.open)
        return cmd_open(args.epub, nums)

    if args.compare:
        if not args.chapter:
            print("[错误] 对比模式需要指定 --chapter N", file=sys.stderr)
            return 1
        return cmd_compare(args.epub, args.compare, args.chapter)

    parser.print_help()
    return 0


def _parse_chapter_range(s: str) -> list[int]:
    nums = []
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            nums.extend(range(int(a), int(b) + 1))
        else:
            nums.append(int(part))
    return sorted(set(nums))


if __name__ == "__main__":
    sys.exit(main())
