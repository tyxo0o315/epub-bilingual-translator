---
name: translate-ebook
description: Translate EPUB ebooks to bilingual format (original + translation interleaved). Triggers on /translate-ebook with an .epub file path and optional flags.
---

# EPUB Bilingual Translator

When the user invokes `/translate-ebook`, follow these steps exactly.

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

- On success (exit code 0): show the output file path and summary statistics.
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
