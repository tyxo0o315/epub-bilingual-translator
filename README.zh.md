# epub-bilingual-translator

[🇬🇧 English](README.md)

将 EPUB 电子书翻译为双语对照格式的 Claude Code Skill——原文与译文逐段交错排列。

## 功能特性

- **多引擎支持**：Claude API、DeepSeek、DeepL、Google 翻译
- **双语排版**：原文深色（`#1a1a1a`）+ 译文灰色（`#888888`）
- **11 种题材预设**：`general`通用 / `history`历史 / `scifi`科幻 / `mystery`悬疑 / `romance`爱情 / `fantasy`奇幻 / `horror`恐怖 / `literary`纯文学 / `business`商业 / `science`科普 / `psychology`心理
- **并行翻译**：多线程并发翻译章节（`--parallel`）
- **词汇表**：专有名词一致性映射，支持内联或 JSON 文件（`--glossary`）
- **文学润色**：翻译后第二轮 LLM 精修（`--refine`）
- **OCR 清理**：翻译前修复断字、合字、软连字符（`--text-cleanup`）
- **技术内容保护**：代码块、行内代码、LaTeX 公式自动保护，翻译后原样还原
- **断点续传**：章节级缓存，中断后自动恢复（`/tmp/epub_translate_<hash>.json`）
- **DeepSeek 费用估算**：翻译前扫描 token 用量并显示参考费用

## 文件说明

| 文件 | 说明 |
|------|------|
| `translate-ebook.md` | Claude Code Skill 定义（`/translate-ebook` 调用） |
| `translate_epub.py` | Python 翻译核心脚本 |

## 安装方法

1. 将 `translate-ebook.md` 复制到 `~/.claude/skills/`
2. 将 `translate_epub.py` 复制到 `~/.claude/scripts/`
3. 按需设置 API Key：
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...   # Claude 引擎
   export DEEPSEEK_API_KEY=sk-...        # DeepSeek 引擎
   export DEEPL_API_KEY=...              # DeepL 引擎
   ```

## 使用方式

在 Claude Code 中调用：

```
/translate-ebook <epub路径> [选项]
```

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--engine` | `claude` | 翻译引擎：`claude` \| `deepseek` \| `deepl` \| `google` |
| `--source` | `en` | 源语言代码 |
| `--target` | `zh` | 目标语言代码 |
| `--genre` | `general` | 题材类型 |
| `--output` | `{原文件名}_bilingual.epub` | 输出路径 |
| `--batch-size` | `20` | 每批翻译段落数 |
| `--parallel` | `1` | 并发章节数（云端 API 推荐 3–5） |
| `--glossary` | — | 词汇表：`"A=B,C=D"` 或 JSON 文件路径 |
| `--refine` | 关闭 | 翻译后文学润色（约增加 2× API 费用） |
| `--refine-model` | sonnet-4-6 | 润色使用的模型 |
| `--text-cleanup` | 关闭 | 翻译前清理 OCR/排版问题 |
| `--no-cache` | 关闭 | 忽略断点续传缓存 |
| `--prompt` | — | 追加到系统提示词的额外指令 |
| `--model` | — | 覆盖默认翻译模型 |
| `--yes / -y` | 关闭 | 跳过 DeepSeek 费用确认（非交互式环境） |

## 使用示例

```bash
# 基础用法
/translate-ebook ~/book.epub

# 大型小说快速并行翻译
/translate-ebook ~/book.epub --engine claude --parallel 4 --genre romance

# 保持角色名一致性
/translate-ebook ~/book.epub --engine deepseek --glossary "Elena=叶莲娜,Damon=戴蒙" --genre romance

# 纯文学作品完整质量翻译
/translate-ebook ~/book.epub --engine claude --genre literary --refine --refine-model claude-sonnet-4-6

# 扫描版/OCR 书籍
/translate-ebook ~/book.epub --engine claude --text-cleanup --genre science

# DeepSeek 全功能
/translate-ebook ~/book.epub --engine deepseek --genre scifi --parallel 3 --refine --glossary "Foundation=基地,Seldon=谢顿"
```

## 依赖安装

```bash
pip install anthropic openai beautifulsoup4 lxml  # Claude / DeepSeek
pip install deepl                                  # 仅 DeepL
pip install "googletrans==4.0.0rc1"               # 仅 Google
```

DeepSeek Token 估算（可选）：
```bash
pip install transformers
```
