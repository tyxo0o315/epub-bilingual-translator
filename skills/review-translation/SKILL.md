---
name: review-translation
description: Review chapters from a bilingual EPUB in the browser, take notes on translation issues, and save parameter suggestions for future translations. Triggers on /review-translation with a bilingual .epub path.
---

# EPUB Translation Reviewer

When the user invokes `/review-translation`, follow these steps exactly.

## Step 1: Get EPUB Path

If the user provided a path, use it. Otherwise ask:

```
请输入双语 EPUB 文件路径（拖入文件即可）：
```

Verify the file exists. If not, tell the user and stop.

## Step 2: List Chapters

Run:
```bash
python3 ~/.claude/scripts/review_epub.py "<epub_path>" --list
```

Show the output to the user.

## Step 3: Select Chapters

Ask:

```
请选择要预览的章节：
（支持单章、多章、范围，例如：3 / 1,3,5 / 2-6）
```

Wait for input.

## Step 4: Open in Browser

Run:
```bash
python3 ~/.claude/scripts/review_epub.py "<epub_path>" --open <chapters>
```

Tell the user: "已在浏览器打开，请查看翻译效果。"

Then ask:
```
是否需要对比另一个版本的翻译？（例如不同引擎/题材的同一本书）（y/n）
```

If yes, ask for the second EPUB path and chapter number, then run:
```bash
python3 ~/.claude/scripts/review_epub.py "<epub_path>" --compare "<epub2_path>" --chapter <N>
```

## Step 5: Collect Feedback Notes

Ask:
```
请记录你发现的翻译问题（可多条，完成后输入"完成"）：

格式示例：
  第3章 人名不一致 → 建议加 --glossary "Elena=叶莲娜"
  第5章 成语太多   → 建议加 --prompt "避免使用成语，用现代白话文"
  整体  语气太正式  → 建议改用 --genre romance

直接回车跳过记录。
```

If the user provides notes, parse each line into:
- `chapter`: 章节编号或"整体"
- `issue`: 问题描述
- `suggestion`: 建议的参数调整

## Step 6: Save Notes

Determine the notes file path:
```python
import re
book_name = re.sub(r'[^\w一-鿿\-]', '_', Path(epub_path).stem)[:60]
notes_path = f"~/.claude/translation-notes/{book_name}.json"
```

Load existing notes if the file exists, then append the new notes. Save as JSON:
```json
{
  "book": "<stem of epub filename>",
  "epub_path": "<full path>",
  "updated": "<YYYY-MM-DD>",
  "notes": [
    {
      "chapter": "第3章",
      "issue": "人名不一致",
      "suggestion_type": "glossary",
      "suggestion": "--glossary \"Elena=叶莲娜\""
    }
  ]
}
```

Create the directory `~/.claude/translation-notes/` if it doesn't exist.

Run:
```bash
mkdir -p ~/.claude/translation-notes
```

Then write the JSON file. Confirm: "笔记已保存到 `<notes_path>`。"

## Step 7: Summary

Show a summary:
```
✅ 预览完成

📋 本次记录了 N 条笔记：
  · 第3章：人名不一致 → --glossary "Elena=叶莲娜"
  · 第5章：成语太多   → --prompt "避免使用成语..."

下次翻译这本书时，/translate-ebook 会自动加载这些建议。
```
