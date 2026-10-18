#!/usr/bin/env python3
"""Download and extract one stored official legal source for human review."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import re
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from src.ingestion.rss_fetcher import _certifi_verify
from src.models.database import LegalDocument, create_all_tables, get_engine, get_session_factory


def main() -> int:
    parser = argparse.ArgumentParser(description="Import exact text for a stored legal reference")
    parser.add_argument("--document-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    engine = get_engine(settings.database_url)
    create_all_tables(engine)
    db = get_session_factory(engine)()
    try:
        document = db.get(LegalDocument, args.document_id)
        if not document:
            raise SystemExit("Legal document not found")
        if not document.source_url:
            raise SystemExit("Legal document has no source URL")

        response, tls_fallback = _fetch_source(document.source_url)
        response.raise_for_status()
        payload = response.content
        content_type = response.headers.get("content-type", "").lower()
        is_pdf = "pdf" in content_type or payload[:4] == b"%PDF"
        text = _extract_pdf(payload) if is_pdf else _extract_html(payload, response.encoding)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) < 200:
            raise SystemExit("Extracted legal text was too short; review the source manually")

        digest = hashlib.sha256(payload).hexdigest()
        suffix = ".pdf" if is_pdf else ".html"
        target = settings.base_dir / "data" / "legal_documents" / f"{document.id}-{digest[:12]}{suffix}"
        print(
            f"{'IMPORT' if args.apply else 'DRY RUN'}: {document.title}\n"
            f"bytes={len(payload)} text_chars={len(text)} sha256={digest}\n"
            f"source={response.url}"
        )
        if not args.apply:
            return 0

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        document.document_text = text
        document.content_hash = digest
        document.local_path = str(target.relative_to(settings.base_dir))
        document.downloaded_at = datetime.datetime.utcnow()
        document.date_accessed = datetime.datetime.utcnow()
        document.notes = (
            ((document.notes or "").strip() + "\n")
            + "Exact source content imported automatically; qualified legal review is still required."
            + (
                " TLS verification fallback was required on this workstation; counsel should "
                "compare the stored SHA-256 and text with the official source."
                if tls_fallback else ""
            )
        ).strip()
        db.commit()
        print(f"Saved {target}")
        return 0
    finally:
        db.close()
        engine.dispose()


def _extract_pdf(payload: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(payload))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _fetch_source(url: str) -> tuple[httpx.Response, bool]:
    options = {
        "timeout": 60,
        "follow_redirects": True,
        "headers": {"User-Agent": "NewsIntel/1.0 legal source archive"},
    }
    try:
        response = httpx.get(url, verify=_certifi_verify(), **options)
        response.raise_for_status()
        return response, False
    except httpx.HTTPError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        response = httpx.get(url, verify=False, **options)
        response.raise_for_status()
        return response, True


def _extract_html(payload: bytes, encoding: str | None) -> str:
    decoded = payload.decode(encoding or "utf-8", errors="replace")
    soup = BeautifulSoup(decoded, "lxml")
    for node in soup(["script", "style", "nav", "footer", "header"]):
        node.decompose()
    main = soup.select_one("main, article, .content, #content") or soup
    return main.get_text("\n", strip=True)


if __name__ == "__main__":
    raise SystemExit(main())
