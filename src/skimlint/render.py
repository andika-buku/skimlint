"""Renders Markdown as GitHub does and cuts the page into desktop screens."""

from __future__ import annotations

import io
import os
from importlib import resources
from typing import List

from PIL import Image

from .text import markdown_parser

# AIM's metrics are defined on a 1280x800 desktop screenshot.
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 800


def render_html(markdown: str, content_width: int) -> str:
    css = resources.files("skimlint").joinpath("assets/github-markdown-light.css").read_text()
    body = markdown_parser().render(markdown)
    return (
        "<!doctype html><meta charset='utf-8'>"
        f"<style>{css}\n"
        "body{margin:0;background:#fff}"
        f".markdown-body{{box-sizing:border-box;max-width:{content_width}px;margin:0 auto;padding:32px}}"
        f"</style><article class='markdown-body'>{body}</article>"
    )


def split_screens(page_png: bytes, max_screens: int) -> List[bytes]:
    """Cuts a full-page PNG into screens. The last screen is padded with white."""
    page = Image.open(io.BytesIO(page_png)).convert("RGB")
    screens = []
    for top in range(0, page.height, SCREEN_HEIGHT):
        if len(screens) == max_screens:
            break
        screen = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), "white")
        screen.paste(page.crop((0, top, SCREEN_WIDTH, min(top + SCREEN_HEIGHT, page.height))))
        buf = io.BytesIO()
        screen.save(buf, format="PNG")
        screens.append(buf.getvalue())
    return screens


def screenshot(markdowns: List[str], content_width: int, max_screens: int, chromium: str | None = None) -> List[List[bytes]]:
    """Returns the screens of each document, in input order."""
    from playwright.sync_api import sync_playwright

    executable = chromium or os.environ.get("SKIMLINT_CHROMIUM")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT})
        result = []
        for markdown in markdowns:
            page.set_content(render_html(markdown, content_width), wait_until="load")
            result.append(split_screens(page.screenshot(full_page=True), max_screens))
        browser.close()
    return result
