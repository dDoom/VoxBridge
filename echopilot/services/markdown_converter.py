"""Convert PDF, DOCX, TXT, and URLs to markdown for AI context ingestion."""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class MarkdownConverter:
    """Lightweight converter for user-uploaded context files."""

    MAX_CHARS = 12000  # ~4K tokens safety margin for system prompt

    def convert(self, path: Path) -> str:
        """Auto-detect and convert a file to markdown."""
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._from_pdf(path)
        if suffix in (".docx", ".doc"):
            return self._from_docx(path)
        if suffix in (".txt", ".md", ".markdown"):
            return self._from_text(path)
        # Fallback: try as plain text
        return self._from_text(path)

    def _from_pdf(self, path: Path) -> str:
        try:
            import pymupdf  # optional dep
            doc = pymupdf.open(str(path))
            parts = []
            for page in doc:
                text = page.get_text()
                if text.strip():
                    parts.append(text)
            raw = "\n\n".join(parts)
            return self._truncate(raw)
        except Exception:
            return self._fallback_text(path, "PDF extraction failed. Install pymupdf.")

    def _from_docx(self, path: Path) -> str:
        try:
            import docx2txt  # optional dep
            raw = docx2txt.process(str(path))
            return self._truncate(raw)
        except Exception:
            return self._fallback_text(path, "DOCX extraction failed. Install python-docx or docx2txt.")

    def _from_text(self, path: Path) -> str:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        return self._truncate(raw)

    def _fallback_text(self, path: Path, reason: str) -> str:
        return f"<!-- {reason} -->\n\n{self._from_text(path)}"

    def _truncate(self, text: str) -> str:
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        if len(text) > self.MAX_CHARS:
            text = text[: self.MAX_CHARS] + "\n\n[...truncated]"
        return text

    def url_to_markdown(self, url: str) -> str:
        """Fetch a URL and convert HTML to markdown-ish text."""
        try:
            import httpx
            from bs4 import BeautifulSoup
            resp = httpx.get(url, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            # Kill scripts/styles
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator="\n")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            raw = "\n".join(lines)
            return self._truncate(raw)
        except Exception as exc:
            return f"<!-- URL fetch failed: {exc} -->"
