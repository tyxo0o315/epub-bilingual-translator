---
name: translate-ebook
description: Translate EPUB ebooks to bilingual format (original + translation interleaved). Triggers on /translate-ebook with an .epub file path and optional flags.
---

# EPUB Bilingual Translator

When the user invokes `/translate-ebook`, follow these steps exactly.

## Step 0: Check Existing Notes

After parsing `epub_path` from the command, check if a notes file exists:
```bash
ls ~/.claude/translation-notes/ 2>/dev/null
```

Compute the expected notes filename from the epub stem (same logic as review-translation skill). If a matching notes file exists, read it and display:

```
📋 发现这本书的翻译笔记（上次 review 记录）：

  · 第3章：人名不一致 → --glossary "Elena=叶莲娜"
  · 第5章：成语太多   → --prompt "避免使用成语，用现代白话文"

是否将以上建议应用到本次翻译？
1. 应用全部建议
2. 手动选择
3. 跳过
```

If the user chooses 1, automatically merge the suggested parameters into the current command arguments.
If the user chooses 2, show each suggestion one by one and ask y/n.
If the user chooses 3 or no notes file exists, continue to the next step.

## Step 0.5: Usage Guide

Ask the user:

```
是否查看使用说明？（y/n）
```

If the user answers `y` or `yes`, display the following, then wait for them to confirm before continuing:

```
📖 EPUB 双语翻译器 — 使用说明

【引擎对比】
  claude    — 质量最佳，速度适中，默认使用 haiku 模型（费用较低）
  deepseek  — 性价比高，翻译前会估算 token 用量和参考费用
  deepl     — 速度最快，不支持词汇表和文学润色
  google    — 免费，质量一般，有频率限制

【费用参考（每10万字估算）】
  claude haiku   ≈ $0.10–0.20
  deepseek-v4    ≈ $0.05–0.15
  deepl          按字符计费，免费额度 50 万字/月
  google         免费

【题材建议】
  小说/文学     → literary 或对应题材（romance/scifi/mystery/fantasy）
  历史/政治     → history
  科普/学术     → science
  商业/财经     → business
  心理/自助     → psychology
  不确定        → general

【实用技巧】
  · --parallel 3~5   大书加速，推荐云端 API
  · --refine         文学润色，质量更好但费用翻倍
  · --glossary       人名/专有名词保持一致
  · --text-cleanup   OCR 扫描版书籍专用

按回车继续翻译。
```

If the user answers `n` or skips, proceed immediately to Step 1.

## Step 1: Parse Arguments

The invocation format is:
```
/translate-ebook <epub_path> [--engine claude|deepseek|deepl|google] [--source en] [--target zh] [--genre general|history|scifi|mystery|romance|fantasy|horror|literary|business|science|psychology] [--output path] [--batch-size 20] [--no-cache] [--prompt "extra instruction"] [--model model_name] [--parallel N] [--glossary "A=B,C=D"] [--text-cleanup] [--refine] [--refine-model model_name]
```

Extract:
- `epub_path`: required, the first non-flag argument (may contain spaces — handle carefully)
- `--engine`: default `claude`
- `--source`: default `en`
- `--target`: default `zh`
- `--genre`: default `general`
- `--output`: default = same directory as input, filename `{stem}_bilingual.epub`
- `--batch-size`: default `20`
- `--no-cache`: flag, pass through if present
- `--prompt`: optional extra instruction string
- `--model`: optional model override for translation
- `--parallel`: number of concurrent chapters (default `1`; use 3–5 for cloud APIs on large books)
- `--glossary`: term consistency map — either `"Elena=叶莲娜,Hogwarts=霍格沃茨"` or path to a JSON file `{"term": "translation", ...}` (claude/deepseek only)
- `--text-cleanup`: flag — fix OCR artifacts (broken words, ligatures, soft hyphens) before translation
- `--refine`: flag — second LLM pass for literary polish after translation (claude/deepseek only; increases cost ~2×)
- `--refine-model`: model for the refine pass (Claude default: `claude-sonnet-4-6`; DeepSeek default: same as main model)

If `epub_path` is not provided or the file does not exist, tell the user and stop.

## Step 1.5: Confirm Genre

If `--genre` was **not** explicitly provided by the user, ask them to choose before proceeding:

```
请选择书籍题材（直接输入数字）：

1. general   — 通用（默认高质量翻译规则）
2. history   — 历史政治
3. scifi     — 科幻
4. mystery   — 悬疑推理
5. romance   — 爱情
6. fantasy   — 奇幻
7. horror    — 恐怖
8. literary  — 纯文学
9. business  — 商业财经
10. science  — 大众科普
11. psychology — 心理自助
```

Wait for the user's input and map the number to the genre name. If the user types the genre name directly, accept that too. Set `genre` to the selected value before continuing.

If `--genre` was already provided, skip this step.

## Step 1.6: Confirm Output Path

If `--output` was **not** explicitly provided, show the default output path and ask for confirmation:

```
输出文件将保存到：
  <default_output_path>

直接回车确认，或输入新路径：
```

Wait for input. If the user presses Enter (empty input), keep the default. If they type a path, use that instead.

## Step 1.7: Confirm Cache Behavior

Ask the user whether to use the resume cache:

```
断点续传缓存：如果之前翻译过这本书，可以从上次中断的地方继续，节省 API 费用。

1. 启用缓存（推荐）— 从断点继续，已翻译章节跳过
2. 忽略缓存 — 从头重新翻译全部章节
```

Wait for input (1 or 2). If the user chooses 2, add `--no-cache` to the command.

If `--no-cache` was already provided in the original command, skip this step.

## Step 2: Install Dependencies

```bash
python3 -m pip install -q anthropic openai beautifulsoup4 lxml 2>&1 | grep -v "already satisfied"
```

For deepl engine, also run:
```bash
python3 -m pip install -q deepl 2>&1 | grep -v "already satisfied"
```

For google engine:
```bash
python3 -m pip install -q "googletrans==4.0.0rc1" 2>&1 | grep -v "already satisfied"
```

## Step 3: Verify API Keys

- `claude`: check `ANTHROPIC_API_KEY` is set in environment. If missing, tell user: `export ANTHROPIC_API_KEY=sk-ant-...`
- `deepseek`: check `DEEPSEEK_API_KEY` is set. If missing, tell user: `export DEEPSEEK_API_KEY=sk-...`
- `deepl`: check `DEEPL_API_KEY` is set.
- `google`: no key needed.

## Step 4: Run Translation Script

Build the command:
```bash
python3 ~/.claude/scripts/translate_epub.py \
  "<epub_path>" \
  --engine <engine> \
  --source <source> \
  --target <target> \
  --genre <genre> \
  --output "<output_path>" \
  --batch-size <batch_size> \
  [--no-cache] \
  [--prompt "<extra_instruction>"] \
  [--model <model>] \
  [--parallel <N>] \
  [--glossary "<terms_or_path>"] \
  [--text-cleanup] \
  [--refine] \
  [--refine-model <model>]
```

Stream the output so the user sees progress per chapter.

## Step 5: Report Result

- On success (exit code 0): show the output file path and summary statistics. Then ask:

  ```
  翻译已完成。是否删除断点续传缓存？
  （缓存文件约占几 MB，重启电脑后也会自动清除）

  1. 删除缓存
  2. 保留缓存（下次重翻同一本书时可断点续传）
  ```

  If the user chooses 1, compute the cache path:
  ```python
  import hashlib
  key = f"{input_path}:{engine}:{target_lang}"
  h = hashlib.md5(key.encode()).hexdigest()[:12]
  cache_path = f"/tmp/epub_translate_{h}.json"
  ```
  Then delete it:
  ```bash
  rm -f "<cache_path>"
  ```
  Confirm: "缓存已删除。"

- On failure: show the error message and suggest a fix.

## Notes

- A checkpoint cache is kept at `/tmp/epub_translate_<hash>.json`. If the user re-runs the same command, already-translated chapters are skipped automatically.
- To retranslate from scratch, add `--no-cache`.
- The output EPUB can be opened in Calibre or any EPUB reader.
- `--parallel` parallelizes at the chapter level using threads. Recommended values: 3–5 for cloud APIs. Not useful for google (free rate limits) or local models.
- `--glossary` only affects the LLM system prompt (claude/deepseek). DeepL and Google will ignore it with a warning.
- `--text-cleanup` is useful for scanned/OCR books with broken words or typographic artifacts.
- `--refine` sends each batch through a second LLM call for literary polish. Claude refine defaults to `claude-sonnet-4-6` (better quality than haiku). DeepSeek refine uses the same model. Roughly doubles API cost.
- `--refine` + `--glossary` is the recommended setup for literary novels where consistency and flow both matter.
- Technical content (code blocks, inline code, LaTeX formulas) is automatically protected with placeholders during translation and restored afterward — no special flag needed.
- Genre options and what they do:
  - `general`: universal high-quality translation rules
  - `history`: scholarly tone, standard historical terminology
  - `scifi`: preserve neologisms, sense of wonder
  - `mystery`: maintain tension and pacing
  - `romance`: warm flowing prose, emotional subtext
  - `fantasy`: epic register, consistent worldbuilding terms
  - `horror`: preserve visceral imagery, fragmented pacing
  - `literary`: honor author's voice and style
  - `business`: crisp professional tone, standard financial terms
  - `science`: accessible but accurate, engaging register
  - `psychology`: warm empathetic tone, standard clinical terms

## Usage examples

```
# Basic
/translate-ebook ~/book.epub

# Fast parallel translation of a large novel
/translate-ebook ~/book.epub --engine claude --parallel 4 --genre romance

# Fiction with character name consistency
/translate-ebook ~/book.epub --engine deepseek --glossary "Elena=叶莲娜,Damon=戴蒙" --genre romance

# Glossary from file
/translate-ebook ~/book.epub --engine claude --glossary ~/glossary.json --genre fantasy

# Literary novel with full quality pass
/translate-ebook ~/book.epub --engine claude --genre literary --refine --refine-model claude-sonnet-4-6

# Scanned/OCR book cleanup
/translate-ebook ~/book.epub --engine claude --text-cleanup --genre science

# DeepSeek with all features
/translate-ebook ~/book.epub --engine deepseek --genre scifi --parallel 3 --refine --glossary "Foundation=基地,Seldon=谢顿"
```
