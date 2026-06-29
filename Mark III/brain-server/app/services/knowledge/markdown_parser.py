"""
MARK III — Markdown Parser

Parses Obsidian .md files into structured chunks suitable for embedding.
Each heading section becomes its own chunk for granular retrieval.

Extracts:
  - YAML frontmatter (title, tags, aliases, date, category)
  - Heading hierarchy
  - Content sections (split at headings for chunk embedding)
  - [[Wikilinks]] for backlink graph
  - #tags
  - Code blocks (stored but not embedded by default)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ─── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class DocumentSection:
    heading:    str           # heading text ("" for pre-heading content)
    level:      int           # 1-6 (0 = document intro)
    content:    str           # plain text content of this section
    line_start: int = 0


@dataclass
class ParsedDocument:
    file_path:    Path
    title:        str
    tags:         list[str]      = field(default_factory=list)
    aliases:      list[str]      = field(default_factory=list)
    category:     str            = ""
    frontmatter:  dict           = field(default_factory=dict)
    sections:     list[DocumentSection] = field(default_factory=list)
    wikilinks:    list[str]      = field(default_factory=list)
    outgoing:     list[str]      = field(default_factory=list)  # same as wikilinks
    word_count:   int            = 0
    is_empty:     bool           = True

    def full_text(self) -> str:
        """Concatenated plain text of all sections."""
        parts = [self.title] if self.title else []
        for s in self.sections:
            if s.heading:
                parts.append(s.heading)
            parts.append(s.content)
        return "\n".join(p for p in parts if p.strip())

    def chunks_for_embedding(self) -> list[tuple[str, dict]]:
        """
        Return (text, metadata) pairs for embedding.
        Each heading section is one chunk.
        Short sections are merged with the next one.
        """
        chunks = []
        MIN_WORDS = 20

        buffer_head = ""
        buffer_text = ""

        def flush():
            nonlocal buffer_head, buffer_text
            text = f"{buffer_head}\n{buffer_text}".strip() if buffer_head else buffer_text.strip()
            if text and len(text.split()) >= MIN_WORDS:
                meta = {
                    "title":    self.title,
                    "heading":  buffer_head,
                    "tags":     ",".join(self.tags),
                    "category": self.category,
                    "file":     str(self.file_path),
                }
                chunks.append((text, meta))
            buffer_head = ""
            buffer_text = ""

        for sec in self.sections:
            words = len(sec.content.split())
            if sec.level <= 1 or words < MIN_WORDS:
                # Merge short sections into buffer
                if sec.heading:
                    buffer_head = buffer_head or sec.heading
                buffer_text += "\n" + sec.content
            else:
                flush()
                buffer_head = sec.heading
                buffer_text = sec.content

        flush()
        return chunks


# ─── Regex patterns ───────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HEADING_RE     = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_WIKILINK_RE    = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]*?)?\]\]")
_TAG_RE         = re.compile(r"(?<!\w)#([A-Za-z][A-Za-z0-9_/-]*)")
_CODE_BLOCK_RE  = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_HTML_RE        = re.compile(r"<[^>]+>")
_MD_LINK_RE     = re.compile(r"!?\[([^\]]*)\]\([^\)]*\)")
_BOLD_ITALIC_RE = re.compile(r"(\*{1,3}|_{1,3})(.*?)\1")


# ─── Parsing ──────────────────────────────────────────────────────────────────

def parse_file(file_path: Path) -> Optional[ParsedDocument]:
    """Parse a single Obsidian markdown file."""
    try:
        raw = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    doc = ParsedDocument(file_path=file_path, title=file_path.stem)

    # ── Frontmatter ──────────────────────────────────────────────────────────
    fm_match = _FRONTMATTER_RE.match(raw)
    body = raw
    if fm_match:
        fm_text = fm_match.group(1)
        body = raw[fm_match.end():]
        doc.frontmatter = _parse_yaml_simple(fm_text)
        doc.title    = doc.frontmatter.get("title", file_path.stem)
        doc.category = doc.frontmatter.get("category", doc.frontmatter.get("type", ""))
        raw_tags = doc.frontmatter.get("tags", [])
        if isinstance(raw_tags, str):
            raw_tags = [t.strip() for t in raw_tags.split(",")]
        doc.tags = [t.lstrip("#") for t in raw_tags if t]
        raw_aliases = doc.frontmatter.get("aliases", [])
        if isinstance(raw_aliases, str):
            raw_aliases = [raw_aliases]
        doc.aliases = raw_aliases

    # ── Inline tags ───────────────────────────────────────────────────────────
    inline_tags = _TAG_RE.findall(body)
    doc.tags = list(set(doc.tags + inline_tags))

    # ── Wikilinks ─────────────────────────────────────────────────────────────
    doc.wikilinks = list(set(_WIKILINK_RE.findall(body)))
    doc.outgoing  = doc.wikilinks

    # ── Sections (split at headings) ──────────────────────────────────────────
    lines      = body.split("\n")
    current_h  = ""
    current_lv = 0
    current_lines: list[str] = []
    line_no = 0

    def flush_section(start: int):
        content = _clean_markdown("\n".join(current_lines).strip())
        if content or current_h:
            doc.sections.append(DocumentSection(
                heading=current_h, level=current_lv,
                content=content,   line_start=start,
            ))

    for i, line in enumerate(lines):
        hm = _HEADING_RE.match(line)
        if hm:
            flush_section(line_no)
            current_h  = hm.group(2).strip()
            current_lv = len(hm.group(1))
            current_lines = []
            line_no = i
        else:
            current_lines.append(line)

    flush_section(line_no)

    # Override title from first H1 if no frontmatter title
    if not fm_match:
        for s in doc.sections:
            if s.level == 1 and s.heading:
                doc.title = s.heading
                break

    doc.word_count = len(doc.full_text().split())
    doc.is_empty   = doc.word_count < 5
    return doc


def _clean_markdown(text: str) -> str:
    """Strip markdown syntax to plain readable text."""
    text = _CODE_BLOCK_RE.sub("[code block]", text)
    text = _INLINE_CODE_RE.sub("", text)
    text = _WIKILINK_RE.sub(lambda m: m.group(1), text)
    text = _MD_LINK_RE.sub(lambda m: m.group(1) or "", text)
    text = _BOLD_ITALIC_RE.sub(lambda m: m.group(2), text)
    text = _HTML_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_yaml_simple(text: str) -> dict:
    """Minimal YAML parser for frontmatter — handles common Obsidian patterns."""
    result: dict = {}
    current_key = None
    current_list: list = []
    in_list = False

    for line in text.split("\n"):
        if not line.strip() or line.strip().startswith("#"):
            continue
        # List item
        if line.startswith("  - ") or line.startswith("- "):
            item = line.lstrip(" -").strip().strip('"\'')
            if current_key:
                current_list.append(item)
                in_list = True
            continue
        # Key: value
        if ":" in line:
            if in_list and current_key:
                result[current_key] = current_list
                current_list = []
                in_list = False
            parts = line.split(":", 1)
            key = parts[0].strip().lower()
            val = parts[1].strip().strip('"\'') if len(parts) > 1 else ""
            current_key = key
            if val:
                result[key] = val
                in_list = False
            else:
                in_list = True

    if in_list and current_key and current_list:
        result[current_key] = current_list

    return result
