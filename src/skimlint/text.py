"""Text metrics that need no rendering: block size and inline code density."""

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
    """A block of running text: a paragraph, list item, quote, or table cell."""

    line: int
    kind: str  # "paragraph" or "cell"
    words: int
    code_spans: int
    code_words: int
    text: str

    @property
    def preview(self) -> str:
        return " ".join(self.text.split()[:8])


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
            "paragraph_details": [
                {k: v for k, v in asdict(p).items() if k != "text"} | {"preview": p.preview}
                for p in self.paragraphs
            ],
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


_BLOCK_OPENERS = {"paragraph_open": "paragraph", "td_open": "cell", "th_open": "cell"}


def analyze_text(markdown: str) -> TextReport:
    """Measures every block of running text.

    Paragraphs inside list items and quotes count as paragraphs. Table cells are
    blocks too, so a wall of text cannot hide in a table. Headings and code
    blocks are not blocks; headings count toward the total words, code blocks
    do not.
    """
    tokens = markdown_parser().parse(markdown)
    report = TextReport(words=0)
    for i, token in enumerate(tokens):
        if token.type != "inline":
            continue
        text, code_spans, code_words = _plain_text(token)
        words = len(text.split())
        report.words += words
        kind = _BLOCK_OPENERS.get(tokens[i - 1].type) if i > 0 else None
        if kind and words:
            report.paragraphs.append(Paragraph(_line(tokens, i), kind, words, code_spans, code_words, text))
    return report


def _line(tokens: List[Token], i: int) -> int:
    """1-based source line of token i. Table cells carry no map, so use their row's."""
    for token in reversed(tokens[: i + 1]):
        if token.map:
            return token.map[0] + 1
    return 0
