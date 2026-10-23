"""Text metrics that need no rendering: paragraph size and inline code density."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List

from markdown_it import MarkdownIt
from markdown_it.token import Token


def markdown_parser() -> MarkdownIt:
    """CommonMark with the GitHub table and strikethrough extensions."""
    return MarkdownIt("commonmark").enable(["table", "strikethrough"])


@dataclass
class Paragraph:
    line: int
    words: int
    code_spans: int
    code_words: int
    preview: str


@dataclass
class TextReport:
    words: int
    paragraphs: List[Paragraph] = field(default_factory=list)

    @property
    def longest(self) -> Paragraph | None:
        return max(self.paragraphs, key=lambda p: p.words, default=None)

    def to_dict(self) -> dict:
        longest = self.longest
        return {
            "words": self.words,
            "paragraphs": len(self.paragraphs),
            "longest_paragraph_words": longest.words if longest else 0,
            "longest_paragraph_line": longest.line if longest else None,
            "max_code_spans": max((p.code_spans for p in self.paragraphs), default=0),
            "paragraph_details": [asdict(p) for p in self.paragraphs],
        }


def _plain_text(inline: Token) -> tuple[str, int, int]:
    """Returns the visible text of an inline token, its code span count, and code words."""
    parts: List[str] = []
    code_spans = 0
    code_words = 0
    for child in inline.children or []:
        if child.type == "text":
            parts.append(child.content)
        elif child.type == "code_inline":
            parts.append(child.content)
            code_spans += 1
            code_words += len(child.content.split())
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
        elif child.type == "image":
            parts.append(child.content)
    return "".join(parts), code_spans, code_words


def analyze_text(markdown: str) -> TextReport:
    """Measures every paragraph, including paragraphs inside list items and quotes.

    Headings, table cells, and code blocks are not paragraphs. They count toward
    the document's total words, except code blocks.
    """
    tokens = markdown_parser().parse(markdown)
    report = TextReport(words=0)
    for i, token in enumerate(tokens):
        if token.type != "inline":
            continue
        text, code_spans, code_words = _plain_text(token)
        words = len(text.split())
        report.words += words
        if i > 0 and tokens[i - 1].type == "paragraph_open":
            line = (token.map[0] + 1) if token.map else 0
            preview = " ".join(text.split()[:8])
            report.paragraphs.append(Paragraph(line, words, code_spans, code_words, preview))
    return report
