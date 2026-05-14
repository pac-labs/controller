from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_stack: list[str] = []
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._current_href: str | None = None
        self._current_link_text: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self.skip_stack.append(tag)
            return
        if self.skip_stack:
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._current_href = href
                self._current_link_text = []
        if tag in {"p", "div", "section", "article", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "pre", "blockquote"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip_stack and self.skip_stack[-1] == tag:
            self.skip_stack.pop()
            return
        if self.skip_stack:
            return
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._current_href:
            text = " ".join("".join(self._current_link_text).split())
            self.links.append({"text": text[:200], "href": self._current_href})
            self._current_href = None
            self._current_link_text = []
        if tag in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4", "h5", "pre", "blockquote"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_stack:
            return
        if self._in_title:
            self.title_parts.append(data)
        if self._current_href:
            self._current_link_text.append(data)
        self.parts.append(data)

    def text(self) -> str:
        raw = html.unescape("".join(self.parts))
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s*\n\s*\n+", "\n\n", raw)
        lines = [line.strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line).strip()

    def title(self) -> str:
        return " ".join("".join(self.title_parts).split()).strip()


def _run_text_browser(binary: str, url: str, timeout: int) -> str | None:
    try:
        if binary == "lynx":
            cmd = ["lynx", "-dump", "-nolist", "-width=120", url]
        elif binary == "links2":
            cmd = ["links2", "-dump", url]
        elif binary == "w3m":
            cmd = ["w3m", "-dump", url]
        else:
            return None
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        text = (proc.stdout or proc.stderr or "").strip()
        return text or None
    except Exception:
        return None


def fetch_page_text(url: str, *, max_chars: int = 30000, timeout: int = 20, prefer_browser: bool = True) -> dict[str, Any]:
    """Fetch a web page and return cleaned readable text.

    Uses lynx/links2/w3m when available because they produce useful rendered text, then falls
    back to urllib + a small HTML parser that removes scripts/styles and collapses whitespace.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are supported")

    if prefer_browser:
        for candidate in ("lynx", "links2", "w3m"):
            if shutil.which(candidate):
                text = _run_text_browser(candidate, url, timeout)
                if text:
                    return {"url": url, "title": "", "text": text[:max_chars], "source": candidate, "truncated": len(text) > max_chars, "links": []}

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PiAgentPlatform/0.10 text-fetcher (+https://local.agent)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("content-type", "")
        raw = resp.read(max_chars * 8)
    if "text/plain" in content_type:
        text = raw.decode("utf-8", errors="replace")
        return {"url": url, "title": "", "text": text[:max_chars], "source": "urllib-plain", "truncated": len(text) > max_chars, "links": []}
    parser = _TextExtractor()
    parser.feed(raw.decode("utf-8", errors="replace"))
    text = parser.text()
    return {"url": url, "title": parser.title(), "text": text[:max_chars], "source": "urllib-html", "truncated": len(text) > max_chars, "links": parser.links[:50]}


def search_web_text(query: str, *, max_results: int = 5, timeout: int = 20) -> dict[str, Any]:
    """Search the web using DuckDuckGo's HTML endpoint and return text-only results.

    This intentionally avoids browser automation. It is enough for agent reconnaissance and
    can be swapped later for SearXNG/Brave/Kagi/etc. through config.
    """
    if not query.strip():
        raise ValueError("query is required")
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    page = fetch_page_text(url, max_chars=60000, timeout=timeout, prefer_browser=False)
    links = []
    seen: set[str] = set()
    for link in page.get("links", []):
        href = str(link.get("href") or "")
        text = str(link.get("text") or "").strip()
        if not href or not text:
            continue
        # DDG wraps outbound links in /l/?uddg=...
        parsed = urllib.parse.urlparse(href)
        if "duckduckgo.com" in parsed.netloc or href.startswith("/l/"):
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("uddg"):
                href = qs["uddg"][0]
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("/"):
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append({"title": text[:240], "url": href})
        if len(links) >= max_results:
            break
    return {"query": query, "results": links, "source": "duckduckgo-html", "raw_text_preview": page.get("text", "")[:2000]}


def as_json_text(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)
