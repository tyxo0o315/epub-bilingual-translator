# epub-bilingual-translator

[🇨🇳 中文](README.zh.md)

A Claude Code skill that translates EPUB ebooks into bilingual format — original text and translation interleaved, paragraph by paragraph.

## Features

- **Multiple engines**: Claude API, DeepSeek, DeepL, Google Translate
- **Bilingual layout**: original in dark (`#1a1a1a`) + translation in gray (`#888888`)
- **11 genre presets**: `general` / `history` / `scifi` / `mystery` / `romance` / `fantasy` / `horror` / `literary` / `business` / `science` / `psychology`
- **Parallel translation**: translate N chapters concurrently (`--parallel`)
- **Glossary support**: term consistency map, inline or JSON file (`--glossary`)
- **Literary refinement**: optional second LLM pass for polish (`--refine`)
- **OCR cleanup**: fix broken words, ligatures, soft hyphens before translation (`--text-cleanup`)
- **Technical content protection**: code blocks, inline code, LaTeX formulas are auto-preserved
- **Resume from checkpoint**: chapter-level cache at `/tmp/epub_translate_<hash>.json`
- **DeepSeek token estimation**: pre-scan + cost estimate before starting

## Files

| File | Description |
|------|-------------|
| `translate-ebook.md` | Claude Code skill definition (invoke with `/translate-ebook`) |
| `translate_epub.py` | Python translation core script |

## Installation

1. Copy `translate-ebook.md` to `~/.claude/skills/`
2. Copy `translate_epub.py` to `~/.claude/scripts/`
3. Set API keys as needed:
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...   # for Claude engine
   export DEEPSEEK_API_KEY=sk-...        # for DeepSeek engine
   export DEEPL_API_KEY=...              # for DeepL engine
   ```

## Usage

Invoke inside Claude Code:

```
/translate-ebook <epub_path> [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--engine` | `claude` | `claude` \| `deepseek` \| `deepl` \| `google` |
| `--source` | `en` | Source language code |
| `--target` | `zh` | Target language code |
| `--genre` | `general` | Genre preset |
| `--output` | `{stem}_bilingual.epub` | Output path |
| `--batch-size` | `20` | Paragraphs per translation batch |
| `--parallel` | `1` | Concurrent chapter threads |
| `--glossary` | — | `"A=B,C=D"` or path to JSON file |
| `--refine` | off | Second LLM pass for literary polish |
| `--refine-model` | sonnet-4-6 | Model for refine pass |
| `--text-cleanup` | off | Fix OCR/typographic artifacts |
| `--no-cache` | off | Ignore resume cache |
| `--prompt` | — | Extra instruction appended to system prompt |
| `--model` | — | Override default translation model |
| `--yes / -y` | off | Skip DeepSeek cost confirmation |

### Examples

```bash
# Basic
/translate-ebook ~/book.epub

# Fast parallel translation of a large novel
/translate-ebook ~/book.epub --engine claude --parallel 4 --genre romance

# Fiction with character name consistency
/translate-ebook ~/book.epub --engine deepseek --glossary "Elena=叶莲娜,Damon=戴蒙" --genre romance

# Literary novel — full quality pass
/translate-ebook ~/book.epub --engine claude --genre literary --refine --refine-model claude-sonnet-4-6

# Scanned/OCR book cleanup
/translate-ebook ~/book.epub --engine claude --text-cleanup --genre science

# DeepSeek with all features
/translate-ebook ~/book.epub --engine deepseek --genre scifi --parallel 3 --refine --glossary "Foundation=基地,Seldon=谢顿"
```

## Dependencies

```bash
pip install anthropic openai beautifulsoup4 lxml  # Claude / DeepSeek
pip install deepl                                  # DeepL only
pip install "googletrans==4.0.0rc1"               # Google only
```

Optional (for DeepSeek token estimation):
```bash
pip install transformers
```
