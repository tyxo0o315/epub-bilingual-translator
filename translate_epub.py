#!/usr/bin/env python3
"""
EPUB Bilingual Translator
Translates EPUB ebooks to bilingual format (original + translation interleaved).
Supports: Claude API, DeepSeek API, DeepL API, Google Translate.

New options:
  --parallel N      Translate N chapters concurrently (cloud APIs only)
  --glossary        Term consistency: 'A=B,C=D' or path to JSON file (claude/deepseek only)
  --text-cleanup    Fix OCR/typographic artifacts before translation
  --refine          Second LLM pass for literary polish (claude/deepseek only)
  --refine-model    Model for refine pass (default: claude-sonnet-4-6 / same model)
"""

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# System prompts (from Notion "Calibre 翻译提示词库")
# ---------------------------------------------------------------------------

BASE_PROMPT = """You are a meticulous translator. Translate the given content from {slang} to {tlang} only.

[Rules]
1. (意译优先) STRONGLY prefer free translation over literal translation. If a direct rendering sounds awkward, COMPLETELY REWRITE the sentence to make it native and elegant. Do NOT be constrained by the original syntax.
2. (去机翻味) Eliminate "machine translation" flavor. Avoid stacking long noun modifiers (绝对避免冗长的"……的……的"结构). Rearrange sentence order to suit Chinese reading habits.
3. (拆长句) DO NOT translate word-for-word. Break down long, complex English clauses into shorter, natural, idiomatic Chinese sentences.
4. (不省略) Do NOT omit any part of the content, even if it seems unimportant or repetitive.
5. (保留URL) Preserve all URLs and website addresses exactly as they appear in the source.
6. (不解释) Do NOT explain any term or answer question-like content. Your answer must be solely the translation — no prefix, no suffix, no annotations."""

GENRE_EXTRAS = {
    "general":    "",
    "history":    "\n[Genre: 历史政治]\n1. [Terminology] Accurately translate historical events, places, and proper nouns according to standard Chinese historical conventions.\n2. [Tone] Maintain an authoritative, scholarly tone befitting academic historical writing.",
    "scifi":      "\n[Genre: 科幻]\n1. [Terminology] Preserve original sci-fi terminology and neologisms consistently throughout. Transliterate creatively when no standard Chinese equivalent exists.\n2. [Tone] Capture the sense of wonder, speculation, and technical precision characteristic of the genre.",
    "mystery":    "\n[Genre: 悬疑推理]\n1. [Atmosphere] Preserve tension, suspense, and pacing. Short, punchy sentences that build dread must not be merged or smoothed over.\n2. [Tone] Maintain an atmosphere of unease and ambiguity. Do not over-clarify intentionally vague passages.",
    "romance":    "\n[Genre: 爱情]\n1. [Emotion] Faithfully convey the emotional subtext, yearning, and nuance of romantic language. Avoid cold or clinical phrasing.\n2. [Tone] Use warm, flowing Chinese prose. Romantic metaphors must feel natural — rewrite awkward comparisons to fit Chinese aesthetic sensibilities.",
    "fantasy":    "\n[Genre: 奇幻]\n1. [Worldbuilding] Keep place names, spell names, and faction names consistent throughout. If a term has an established Chinese fan translation, prefer it.\n2. [Tone] Match the epic, mythic register of the source. Grand proclamations should sound grand — not bureaucratic.",
    "horror":     "\n[Genre: 恐怖]\n1. [Atmosphere] Preserve visceral, unsettling imagery precisely. Do not soften graphic descriptions — the horror must land.\n2. [Pacing] Keep fragmented, breathless sentence rhythms intact when they serve the fear effect.",
    "literary":   "\n[Genre: 纯文学]\n1. [Style] Honor the author's distinctive voice and stylistic idiosyncrasies. Do not normalize experimental syntax.\n2. [Register] Match the register of the original — whether elevated, vernacular, lyrical, or minimalist.",
    "business":   "\n[Genre: 商业财经]\n1. [Terminology] Use standard mainland Chinese financial and business terminology.\n2. [Tone] Crisp, professional, and direct. Avoid overly literary flourishes.",
    "science":    "\n[Genre: 大众科普]\n1. [Accessibility] Make technical concepts approachable without dumbing them down. Use analogies familiar to Chinese readers where helpful.\n2. [Tone] Engaging, clear, and curious in register — like a knowledgeable friend explaining things.",
    "psychology": "\n[Genre: 心理自助]\n1. [Tone] Warm, empathetic, and encouraging. The reader should feel spoken to, not lectured at.\n2. [Terminology] Use standard psychological terms where established; otherwise prefer plain, accessible Chinese.",
}

LANG_NAMES = {
    "en": "English", "zh": "Chinese (Simplified)", "zh-tw": "Chinese (Traditional)",
    "ja": "Japanese", "ko": "Korean", "fr": "French", "de": "German",
    "es": "Spanish", "ru": "Russian", "pt": "Portuguese", "it": "Italian",
}


def build_system_prompt(genre: str, source_lang: str, target_lang: str,
                         extra_prompt: str | None,
                         glossary: dict | None = None) -> str:
    src = LANG_NAMES.get(source_lang, source_lang)
    tgt = LANG_NAMES.get(target_lang, target_lang)
    prompt = BASE_PROMPT.format(slang=src, tlang=tgt)
    prompt += GENRE_EXTRAS.get(genre, "")
    if glossary:
        prompt += "\n[Glossary — Always translate these terms exactly as specified]\n"
        for source_term, target_term in glossary.items():
            prompt += f"- {source_term} → {target_term}\n"
    if extra_prompt:
        prompt += f"\n[Extra instruction] {extra_prompt}"
    return prompt


# ---------------------------------------------------------------------------
# Glossary parsing
# ---------------------------------------------------------------------------

def parse_glossary(glossary_arg: str | None) -> dict | None:
    """Parse --glossary: 'A=B,C=D' inline string or path to JSON file."""
    if not glossary_arg:
        return None
    if os.path.isfile(glossary_arg):
        try:
            with open(glossary_arg, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return {item["source"]: item["target"]
                        for item in data if "source" in item and "target" in item}
        except Exception as e:
            print(f"[警告] 词汇表文件读取失败: {e}", file=sys.stderr)
            return None
    terms: dict[str, str] = {}
    for pair in glossary_arg.split(","):
        pair = pair.strip()
        if "=" in pair:
            source, _, target = pair.partition("=")
            if source.strip() and target.strip():
                terms[source.strip()] = target.strip()
    return terms if terms else None


# ---------------------------------------------------------------------------
# Text cleanup (OCR / typographic artifacts)
# ---------------------------------------------------------------------------

def cleanup_text(text: str) -> str:
    """Fix common OCR/typographic issues before translation."""
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("ﬀ", "ff")
    text = text.replace("ﬃ", "ffi").replace("ﬄ", "ffl")
    text = text.replace("­", "")                        # soft hyphen
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)      # broken words
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Technical content placeholder protection
# ---------------------------------------------------------------------------

_PROTECT_PATTERNS = [
    re.compile(r"```[\s\S]*?```"),             # fenced code blocks
    re.compile(r"`[^`\n]+`"),                   # inline code
    re.compile(r"\$\$[\s\S]{1,300}?\$\$"),      # LaTeX display math
    re.compile(r"\$[^\s$][^$\n]{0,58}\$"),      # LaTeX inline math
]


def protect_content(text: str) -> tuple[str, dict[str, str]]:
    """Replace technical patterns with placeholders. Returns (protected_text, map)."""
    placeholders: dict[str, str] = {}
    counter = [0]

    for pattern in _PROTECT_PATTERNS:
        def replacer(m: re.Match, _c: list = counter) -> str:
            key = f"⟦{_c[0]}⟧"   # ⟦N⟧
            placeholders[key] = m.group(0)
            _c[0] += 1
            return key
        text = pattern.sub(replacer, text)

    return text, placeholders


def restore_content(text: str, placeholders: dict[str, str]) -> str:
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text


# ---------------------------------------------------------------------------
# DeepSeek token estimation
# ---------------------------------------------------------------------------

def estimate_tokens_deepseek(all_texts: list[str]) -> dict:
    tokenizer_path = os.environ.get("DEEPSEEK_TOKENIZER_PATH")
    if not tokenizer_path:
        return {
            "available": False,
            "error": "set DEEPSEEK_TOKENIZER_PATH to a local tokenizer path",
        }
    try:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_path, trust_remote_code=True
        )
        total_input = sum(len(tokenizer.encode(t)) for t in all_texts)
        total_output = int(total_input * 1.1)
        return {"input": total_input, "output": total_output, "available": True}
    except Exception as e:
        return {"available": False, "error": str(e)}


def confirm_deepseek_translation(spine: list[str], epub_parser, inserter,
                                  auto_yes: bool = False) -> bool:
    print("[DeepSeek] 正在扫描书籍以估算 Token 用量...")
    all_texts = []
    for chapter_path in spine:
        html = epub_parser.read_chapter(chapter_path)
        segments = inserter.extract_translatable(html)
        all_texts.extend(s["text"] for s in segments)

    print(f"[DeepSeek] 共 {len(all_texts):,} 个段落待翻译")
    result = estimate_tokens_deepseek(all_texts)

    if result["available"]:
        inp = result["input"]
        out = result["output"]
        cost_est = inp / 1_000_000 * 0.27 + out / 1_000_000 * 1.10
        print(f"[DeepSeek] 估算 Token：输入 {inp:,} / 输出 {out:,}")
        print(f"[DeepSeek] 参考费用约 ${cost_est:.3f} USD（deepseek-v4-pro 定价，以实际账单为准）")
    else:
        print(f"[DeepSeek] Token 估算不可用（{result.get('error', '未知错误')}）")
        print("[DeepSeek] 建议先安装: pip install transformers")

    if auto_yes:
        print("[DeepSeek] 自动确认（--yes）")
        return True
    try:
        answer = input("[DeepSeek] 是否继续翻译？[y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


# ---------------------------------------------------------------------------
# EPUB Parser
# ---------------------------------------------------------------------------

class EPUBParser:
    def __init__(self, epub_path: str):
        self.epub_path = epub_path
        self.zip = zipfile.ZipFile(epub_path, "r")
        self.opf_path: str = ""
        self.opf_base_dir: str = ""
        self.manifest: dict[str, dict] = {}
        self.spine: list[str] = []

    def parse(self) -> "EPUBParser":
        self._find_opf()
        self._parse_opf()
        return self

    def _find_opf(self):
        container = self.zip.read("META-INF/container.xml").decode("utf-8")
        root = ET.fromstring(container)
        ns = "urn:oasis:names:tc:opendocument:xmlns:container"
        rootfile = root.find(f".//{{{ns}}}rootfile")
        if rootfile is None:
            raise ValueError("Cannot find rootfile in META-INF/container.xml")
        self.opf_path = rootfile.get("full-path", "")
        self.opf_base_dir = os.path.dirname(self.opf_path)

    def _parse_opf(self):
        opf_content = self.zip.read(self.opf_path).decode("utf-8")
        root = ET.fromstring(opf_content)
        OPF_NS = "http://www.idpf.org/2007/opf"

        for item in root.findall(f".//{{{OPF_NS}}}item"):
            item_id = item.get("id", "")
            href = item.get("href", "")
            media_type = item.get("media-type", "")
            if self.opf_base_dir:
                full_path = os.path.normpath(
                    os.path.join(self.opf_base_dir, href)
                ).replace("\\", "/")
            else:
                full_path = href
            self.manifest[item_id] = {
                "href": href,
                "media_type": media_type,
                "full_path": full_path,
            }

        for itemref in root.findall(f".//{{{OPF_NS}}}itemref"):
            idref = itemref.get("idref", "")
            if idref in self.manifest:
                item = self.manifest[idref]
                if item["media_type"] == "application/xhtml+xml":
                    self.spine.append(item["full_path"])

    def read_chapter(self, full_path: str) -> str:
        return self.zip.read(full_path).decode("utf-8", errors="replace")

    def get_all_infos(self) -> list[zipfile.ZipInfo]:
        return self.zip.infolist()

    def read_raw(self, name: str) -> bytes:
        return self.zip.read(name)

    def close(self):
        self.zip.close()


# ---------------------------------------------------------------------------
# Translation cache
# ---------------------------------------------------------------------------

class TranslationCache:
    def __init__(self, epub_path: str, engine: str, target_lang: str, use_cache: bool):
        key = f"{epub_path}:{engine}:{target_lang}"
        h = hashlib.md5(key.encode()).hexdigest()[:12]
        self.cache_path = Path(f"/tmp/epub_translate_{h}.json")
        self.use_cache = use_cache
        self.data: dict = {"chapters": {}}
        self._lock = threading.Lock()

        if use_cache and self.cache_path.exists():
            try:
                self.data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                done = len(self.data.get("chapters", {}))
                if done:
                    print(f"[Cache] 从断点恢复，已完成 {done} 章节（{self.cache_path}）")
            except (json.JSONDecodeError, KeyError):
                self.data = {"chapters": {}}

    def is_done(self, chapter_path: str) -> bool:
        return chapter_path in self.data.get("chapters", {})

    def get(self, chapter_path: str) -> str:
        return self.data["chapters"][chapter_path]

    def save_chapter(self, chapter_path: str, translated_html: str):
        with self._lock:
            self.data.setdefault("chapters", {})[chapter_path] = translated_html
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.cache_path)

    def clear(self):
        if self.cache_path.exists():
            self.cache_path.unlink()


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def escape_xml(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def parse_xml_translations(response_text: str, expected_count: int) -> list[str]:
    translations: dict[int, str] = {}
    for m in re.finditer(r'<t\s+id=["\'](\d+)["\']>(.*?)</t>', response_text, re.DOTALL):
        translations[int(m.group(1))] = m.group(2).strip()
    return [translations.get(i, f"[翻译失败 #{i}]") for i in range(1, expected_count + 1)]


def _make_batch_user_msg(texts: list[str]) -> str:
    items = "\n".join(f'<p id="{i+1}">{escape_xml(t)}</p>' for i, t in enumerate(texts))
    return (f"<source>\n{items}\n</source>\n\n"
            'Return translations in <translations><t id="N">...</t></translations> format.')


def _make_refine_user_msg(originals: list[str], translations: list[str]) -> str:
    items = "\n".join(
        f'<item id="{i+1}"><src>{escape_xml(o)}</src><tr>{escape_xml(t)}</tr></item>'
        for i, (o, t) in enumerate(zip(originals, translations))
    )
    return (f"<content>\n{items}\n</content>\n\n"
            'Return polished translations in <refined><t id="N">...</t></refined> format.')


def _parse_refined(response_text: str, fallback: list[str]) -> list[str]:
    refined: dict[int, str] = {}
    for m in re.finditer(r'<t\s+id=["\'](\d+)["\']>(.*?)</t>', response_text, re.DOTALL):
        refined[int(m.group(1))] = m.group(2).strip()
    return [refined.get(i + 1, fallback[i]) for i in range(len(fallback))]


# ---------------------------------------------------------------------------
# Translation engines
# ---------------------------------------------------------------------------

class BaseTranslator:
    def __init__(self, source_lang: str, target_lang: str):
        self.source_lang = source_lang
        self.target_lang = target_lang
        self._refine_enabled = False

    def translate_batch(self, texts: list[str]) -> list[str]:
        raise NotImplementedError

    def refine_batch(self, originals: list[str], translations: list[str]) -> list[str]:
        return translations

    def translate_paragraphs(self, paragraphs: list[str], batch_size: int = 20,
                              use_cleanup: bool = False,
                              use_protect: bool = True) -> list[str]:
        results = []
        for i in range(0, len(paragraphs), batch_size):
            batch = paragraphs[i:i + batch_size]
            non_empty = [(j, t) for j, t in enumerate(batch) if t.strip()]
            if not non_empty:
                results.extend(batch)
                continue
            indices, texts = zip(*non_empty)
            texts = list(texts)
            original_texts = texts.copy()

            if use_cleanup:
                texts = [cleanup_text(t) for t in texts]

            pmaps: list[dict] = []
            if use_protect:
                pairs = [protect_content(t) for t in texts]
                texts = [p[0] for p in pairs]
                pmaps = [p[1] for p in pairs]

            translated = self.translate_batch(texts)

            if use_protect and pmaps:
                translated = [restore_content(tr, pm) for tr, pm in zip(translated, pmaps)]

            if self._refine_enabled:
                translated = self.refine_batch(original_texts, translated)

            batch_result = list(batch)
            for idx, tr in zip(indices, translated):
                batch_result[idx] = tr
            results.extend(batch_result)
        return results


class ClaudeTranslator(BaseTranslator):
    DEFAULT_MODEL = "claude-haiku-4-5-20251001"
    DEFAULT_REFINE_MODEL = "claude-sonnet-4-6"

    def __init__(self, source_lang: str, target_lang: str, genre: str,
                 extra_prompt: str | None, model: str | None = None,
                 glossary: dict | None = None,
                 refine: bool = False, refine_model: str | None = None):
        super().__init__(source_lang, target_lang)
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model or self.DEFAULT_MODEL
        self.system_prompt = build_system_prompt(genre, source_lang, target_lang, extra_prompt, glossary)
        self._refine_enabled = refine
        if refine:
            self._refine_model = refine_model or self.DEFAULT_REFINE_MODEL
            src = LANG_NAMES.get(source_lang, source_lang)
            tgt = LANG_NAMES.get(target_lang, target_lang)
            self._refine_system = (
                f"You are a literary editor specializing in {src}-to-{tgt} translation polish. "
                f"You receive pairs of original text and their translations. "
                f"Improve each translation for naturalness, flow, and literary quality, "
                f"preserving meaning exactly. "
                f'Return ONLY <refined><t id="N">improved translation</t></refined>. No other text.'
            )

    def translate_batch(self, texts: list[str]) -> list[str]:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=[{"type": "text", "text": self.system_prompt,
                      "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": _make_batch_user_msg(texts)}],
        )
        return parse_xml_translations(response.content[0].text, len(texts))

    def refine_batch(self, originals: list[str], translations: list[str]) -> list[str]:
        if not self._refine_enabled:
            return translations
        response = self.client.messages.create(
            model=self._refine_model,
            max_tokens=8192,
            system=[{"type": "text", "text": self._refine_system,
                      "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": _make_refine_user_msg(originals, translations)}],
        )
        return _parse_refined(response.content[0].text, translations)


class DeepSeekTranslator(BaseTranslator):
    MODEL = "deepseek-v4-pro"
    BASE_URL = "https://api.deepseek.com/v1"

    def __init__(self, source_lang: str, target_lang: str, genre: str,
                 extra_prompt: str | None, model: str | None = None,
                 glossary: dict | None = None,
                 refine: bool = False, refine_model: str | None = None):
        super().__init__(source_lang, target_lang)
        from openai import OpenAI
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("请设置环境变量 DEEPSEEK_API_KEY")
        self.client = OpenAI(api_key=api_key, base_url=self.BASE_URL)
        self.model = model or self.MODEL
        self.system_prompt = build_system_prompt(genre, source_lang, target_lang, extra_prompt, glossary)
        self._refine_enabled = refine
        if refine:
            self._refine_model = refine_model or self.MODEL
            src = LANG_NAMES.get(source_lang, source_lang)
            tgt = LANG_NAMES.get(target_lang, target_lang)
            self._refine_system = (
                f"You are a literary editor specializing in {src}-to-{tgt} translation polish. "
                f"You receive pairs of original text and their translations. "
                f"Improve each translation for naturalness and literary quality, preserving meaning exactly. "
                f'Return ONLY <refined><t id="N">improved translation</t></refined>.'
            )

    def translate_batch(self, texts: list[str]) -> list[str]:
        response = self.client.chat.completions.create(
            model=self.model,
            stream=False,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": _make_batch_user_msg(texts)},
            ],
        )
        return parse_xml_translations(response.choices[0].message.content, len(texts))

    def refine_batch(self, originals: list[str], translations: list[str]) -> list[str]:
        if not self._refine_enabled:
            return translations
        response = self.client.chat.completions.create(
            model=self._refine_model,
            stream=False,
            messages=[
                {"role": "system", "content": self._refine_system},
                {"role": "user", "content": _make_refine_user_msg(originals, translations)},
            ],
        )
        return _parse_refined(response.choices[0].message.content, translations)


class DeepLTranslator(BaseTranslator):
    def __init__(self, source_lang: str, target_lang: str,
                 glossary: dict | None = None, refine: bool = False,
                 refine_model: str | None = None, **_):
        super().__init__(source_lang, target_lang)
        import deepl
        api_key = os.environ.get("DEEPL_API_KEY")
        if not api_key:
            raise ValueError("请设置环境变量 DEEPL_API_KEY")
        self.translator = deepl.Translator(api_key)
        self.deepl_target = target_lang.upper()
        if glossary:
            print("[警告] DeepL 引擎不支持 --glossary，词汇表将被忽略", file=sys.stderr)
        if refine:
            print("[警告] DeepL 引擎不支持 --refine，跳过精修", file=sys.stderr)

    def translate_batch(self, texts: list[str]) -> list[str]:
        results = self.translator.translate_text(
            texts,
            source_lang=self.source_lang.upper(),
            target_lang=self.deepl_target,
        )
        return [r.text for r in results]


class GoogleTranslator(BaseTranslator):
    def __init__(self, source_lang: str, target_lang: str,
                 glossary: dict | None = None, refine: bool = False,
                 refine_model: str | None = None, **_):
        super().__init__(source_lang, target_lang)
        from googletrans import Translator
        self.translator = Translator()
        if glossary:
            print("[警告] Google 引擎不支持 --glossary，词汇表将被忽略", file=sys.stderr)
        if refine:
            print("[警告] Google 引擎不支持 --refine，跳过精修", file=sys.stderr)

    def translate_batch(self, texts: list[str]) -> list[str]:
        results = self.translator.translate(texts, src=self.source_lang, dest=self.target_lang)
        if isinstance(results, list):
            return [r.text for r in results]
        return [results.text]


def create_translator(engine: str, source_lang: str, target_lang: str,
                       genre: str, extra_prompt: str | None,
                       model_override: str | None,
                       glossary: dict | None = None,
                       refine: bool = False,
                       refine_model: str | None = None) -> BaseTranslator:
    kwargs = dict(source_lang=source_lang, target_lang=target_lang,
                  genre=genre, extra_prompt=extra_prompt, model=model_override,
                  glossary=glossary, refine=refine, refine_model=refine_model)
    if engine == "claude":
        return ClaudeTranslator(**kwargs)
    elif engine == "deepseek":
        return DeepSeekTranslator(**kwargs)
    elif engine == "deepl":
        return DeepLTranslator(**kwargs)
    elif engine == "google":
        return GoogleTranslator(**kwargs)
    raise ValueError(f"未知引擎: {engine}")


# ---------------------------------------------------------------------------
# Bilingual HTML inserter
# ---------------------------------------------------------------------------

TRANSLATE_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li"}
SKIP_ANCESTOR_TAGS = {"code", "pre", "script", "style", "math", "svg"}

import warnings
try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:
    pass

BILINGUAL_CSS = """
.epub-original { color: #1a1a1a; }
.epub-translation { color: #888888; font-size: 0.92em; margin-top: 0.1em; margin-bottom: 0.6em; }
"""


class BilingualInserter:
    def extract_translatable(self, html: str) -> list[dict]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        segments = []
        for tag in soup.find_all(TRANSLATE_TAGS):
            if any(a.name in SKIP_ANCESTOR_TAGS for a in tag.parents):
                continue
            text = tag.get_text(separator=" ", strip=True)
            if not text or len(text) < 3:
                continue
            segments.append({"text": text, "tag_name": tag.name})
        return segments

    def inject_translations(self, html: str, translations: list[str],
                             expected_count: int) -> str:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")

        translatable_tags = []
        for tag in soup.find_all(TRANSLATE_TAGS):
            if any(a.name in SKIP_ANCESTOR_TAGS for a in tag.parents):
                continue
            text = tag.get_text(separator=" ", strip=True)
            if not text or len(text) < 3:
                continue
            translatable_tags.append(tag)

        if len(translatable_tags) != len(translations):
            count = min(len(translatable_tags), len(translations))
            translatable_tags = translatable_tags[:count]
            translations = translations[:count]

        for tag, translation in zip(reversed(translatable_tags), reversed(translations)):
            existing = tag.get("class", [])
            if isinstance(existing, str):
                existing = existing.split()
            tag["class"] = existing + ["epub-original"]

            new_tag = soup.new_tag(tag.name)
            new_tag["class"] = "epub-translation"
            new_tag.string = translation
            tag.insert_after(new_tag)

        head = soup.find("head")
        if head:
            style_tag = soup.new_tag("style", type="text/css")
            style_tag.string = BILINGUAL_CSS
            head.append(style_tag)

        return str(soup)


# ---------------------------------------------------------------------------
# EPUB Writer
# ---------------------------------------------------------------------------

class EPUBWriter:
    @staticmethod
    def write(output_path: str, parser: EPUBParser, chapter_overrides: dict[str, str]):
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(str(out), "w") as zout:
            zout.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")

            for zinfo in parser.get_all_infos():
                name = zinfo.filename
                if name == "mimetype":
                    continue
                if name in chapter_overrides:
                    content = chapter_overrides[name].encode("utf-8")
                    new_info = zipfile.ZipInfo(name)
                    new_info.compress_type = zipfile.ZIP_DEFLATED
                    zout.writestr(new_info, content)
                else:
                    data = parser.read_raw(name)
                    new_info = zipfile.ZipInfo(name)
                    new_info.compress_type = zinfo.compress_type
                    zout.writestr(new_info, data)

        size_mb = out.stat().st_size / 1024 / 1024
        print(f"[Writer] 输出文件: {out} ({size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# Chapter translation helper
# ---------------------------------------------------------------------------

def _translate_chapter_html(chapter_path: str, html: str,
                              translator: BaseTranslator, inserter: BilingualInserter,
                              cache: TranslationCache, batch_size: int,
                              text_cleanup: bool) -> tuple[str, int]:
    """Translate one chapter. Returns (bilingual_html, paragraph_count)."""
    segments = inserter.extract_translatable(html)
    if not segments:
        return html, 0
    texts = [s["text"] for s in segments]
    translations = translator.translate_paragraphs(
        texts, batch_size, use_cleanup=text_cleanup, use_protect=True
    )
    bilingual_html = inserter.inject_translations(html, translations, len(segments))
    cache.save_chapter(chapter_path, bilingual_html)
    return bilingual_html, len(segments)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def translate_epub(input_path: str, output_path: str, engine: str,
                   source_lang: str, target_lang: str, genre: str,
                   batch_size: int, use_cache: bool,
                   extra_prompt: str | None, model_override: str | None,
                   glossary: dict | None = None,
                   text_cleanup: bool = False,
                   parallel: int = 1,
                   refine: bool = False,
                   refine_model: str | None = None,
                   yes: bool = False):
    start_time = time.time()
    print(f"[Translate] 输入:  {input_path}")
    print(f"[Translate] 输出:  {output_path}")
    flags = f"{engine} | {source_lang}→{target_lang} | 题材:{genre}"
    if parallel > 1:
        flags += f" | 并行:{parallel}"
    if glossary:
        flags += f" | 词汇表:{len(glossary)}条"
    if text_cleanup:
        flags += " | OCR清理"
    if refine:
        flags += " | 精修"
    print(f"[Translate] {flags}")

    parser = EPUBParser(input_path).parse()
    print(f"[Parse] 发现 {len(parser.spine)} 个章节")

    cache = TranslationCache(input_path, engine, target_lang, use_cache)
    inserter = BilingualInserter()

    if engine == "deepseek":
        pending_for_estimate = [cp for cp in parser.spine if not cache.is_done(cp)]
        if pending_for_estimate:
            if not confirm_deepseek_translation(pending_for_estimate, parser, inserter, auto_yes=yes):
                print("[Translate] 已取消。")
                parser.close()
                return 1

    translator = create_translator(
        engine, source_lang, target_lang, genre, extra_prompt, model_override,
        glossary=glossary, refine=refine, refine_model=refine_model,
    )

    chapter_overrides: dict[str, str] = {}
    total_paragraphs = 0

    # Load cached chapters
    cached = [cp for cp in parser.spine if cache.is_done(cp)]
    if cached:
        print(f"[Cache] {len(cached)} 章节已从缓存恢复")
        for cp in cached:
            chapter_overrides[cp] = cache.get(cp)

    pending = [cp for cp in parser.spine if not cache.is_done(cp)]

    if pending:
        print(f"\n[翻译] 开始处理 {len(pending)} 个章节...")
        # Pre-read all HTML in main thread (zipfile is not thread-safe for concurrent reads)
        chapter_htmls = {cp: parser.read_chapter(cp) for cp in pending}
        spine_pos = {cp: i + 1 for i, cp in enumerate(parser.spine)}
        print_lock = threading.Lock()

        if parallel > 1:
            print(f"[并行] 使用 {parallel} 个并发线程")
            with ThreadPoolExecutor(max_workers=parallel) as executor:
                future_to_path = {
                    executor.submit(
                        _translate_chapter_html,
                        cp, chapter_htmls[cp], translator, inserter,
                        cache, batch_size, text_cleanup
                    ): cp
                    for cp in pending
                }
                completed = 0
                for future in as_completed(future_to_path):
                    cp = future_to_path[future]
                    completed += 1
                    try:
                        bilingual_html, count = future.result()
                        chapter_overrides[cp] = bilingual_html
                        total_paragraphs += count
                        elapsed = time.time() - start_time
                        label = f"{count} 段落" if count else "无内容，跳过"
                        with print_lock:
                            print(f"  [第{spine_pos[cp]}章 {completed}/{len(pending)}] "
                                  f"{label} | {elapsed:.1f}s")
                    except Exception as e:
                        with print_lock:
                            print(f"  [错误] {cp}: {e}", file=sys.stderr)
                        chapter_overrides[cp] = chapter_htmls[cp]
        else:
            for cp in pending:
                print(f"\n[章节 {spine_pos[cp]}/{len(parser.spine)}] {cp}")
                bilingual_html, count = _translate_chapter_html(
                    cp, chapter_htmls[cp], translator, inserter,
                    cache, batch_size, text_cleanup
                )
                chapter_overrides[cp] = bilingual_html
                total_paragraphs += count
                elapsed = time.time() - start_time
                label = f"{count} 段落" if count else "无可翻译内容"
                print(f"  [完成] {label} | 已用时 {elapsed:.1f}s")

    print(f"\n[Write] 正在生成双语 EPUB...")
    EPUBWriter.write(output_path, parser, chapter_overrides)
    parser.close()

    elapsed = time.time() - start_time
    print(f"\n[完成] 翻译结束！")
    print(f"  章节数: {len(parser.spine)}")
    print(f"  段落数: {total_paragraphs:,}")
    print(f"  用时:   {elapsed:.1f}s")
    print(f"  输出:   {output_path}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="将 EPUB 电子书翻译为双语对照格式",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input_epub", help="输入 EPUB 文件路径")
    parser.add_argument("--engine", choices=["claude", "deepseek", "deepl", "google"],
                        default="claude", help="翻译引擎（默认: claude）")
    parser.add_argument("--source", default="en", help="源语言代码（默认: en）")
    parser.add_argument("--target", default="zh", help="目标语言代码（默认: zh）")
    parser.add_argument("--genre", choices=list(GENRE_EXTRAS.keys()),
                        default="general", help="题材类型（默认: general）")
    parser.add_argument("--output", default=None, help="输出路径（默认: 原文件名_bilingual.epub）")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="每批翻译的段落数（默认: 20）")
    parser.add_argument("--no-cache", action="store_true", help="忽略翻译缓存")
    parser.add_argument("--prompt", default=None, help="额外翻译指令（追加到系统提示词）")
    parser.add_argument("--model", default=None, help="覆盖默认翻译模型名")
    parser.add_argument("--parallel", type=int, default=1,
                        help="并发翻译的章节数（默认: 1，推荐用于云端 API）")
    parser.add_argument("--glossary", default=None,
                        help="词汇表：'源词=译词,源词=译词' 或 JSON 文件路径（仅 claude/deepseek）")
    parser.add_argument("--text-cleanup", action="store_true",
                        help="翻译前清理 OCR/排版问题（断字、连字符、合字）")
    parser.add_argument("--refine", action="store_true",
                        help="翻译后进行第二轮文学润色（仅 claude/deepseek，增加 API 费用）")
    parser.add_argument("--refine-model", default=None,
                        help="精修使用的模型（Claude 默认: claude-sonnet-4-6；DeepSeek 默认同主模型）")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="跳过 DeepSeek token 估算确认（非交互式环境使用）")
    args = parser.parse_args()

    if not os.path.exists(args.input_epub):
        print(f"[错误] 文件不存在: {args.input_epub}", file=sys.stderr)
        return 1

    if args.output is None:
        inp = Path(args.input_epub)
        args.output = str(inp.parent / f"{inp.stem}_bilingual.epub")

    glossary = parse_glossary(args.glossary)
    if glossary:
        print(f"[词汇表] 加载 {len(glossary)} 条词条: {', '.join(list(glossary.keys())[:5])}"
              + (" ..." if len(glossary) > 5 else ""))

    return translate_epub(
        input_path=args.input_epub,
        output_path=args.output,
        engine=args.engine,
        source_lang=args.source,
        target_lang=args.target,
        genre=args.genre,
        batch_size=args.batch_size,
        use_cache=not args.no_cache,
        extra_prompt=args.prompt,
        model_override=args.model,
        glossary=glossary,
        text_cleanup=args.text_cleanup,
        parallel=args.parallel,
        refine=args.refine,
        refine_model=args.refine_model,
        yes=args.yes,
    )


if __name__ == "__main__":
    sys.exit(main())
