"""
scripts/run_ingest.py

Run IFC knowledge base ingest directly from terminal.
Bypasses FastAPI, BackgroundTasks, and connection caching issues.

Usage:
    cd /path/to/ifc_viewer_backend
    python scripts/run_ingest.py

    # Skip already-ingested URLs (default)
    python scripts/run_ingest.py --skip-existing

    # Re-ingest everything from scratch
    python scripts/run_ingest.py --fresh

    # Test with just one URL first
    python scripts/run_ingest.py --url https://docs.ifcopenshell.org/introduction/introduction_to_ifc.html
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# ── Make sure app is importable ───────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
# Silence truly noisy loggers only
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# Keep httpx at INFO so you can see each HTTP request to the scraper
logging.getLogger("httpx").setLevel(logging.INFO)

# Make sure all app loggers are visible
logging.getLogger("app").setLevel(logging.DEBUG)
logging.getLogger("ingest").setLevel(logging.DEBUG)

logger = logging.getLogger("ingest")


# ── Patched scraper that logs every fetched URL ───────────────────────────────

async def run_full_ingest(skip_existing: bool = True) -> None:
    from ycpa.core.ifc_knowledge.scraper import IFCDocScraper
    from ycpa.services.ifc_knowledge_service import IFCKnowledgeIngestService

    from ycpa.core.database.session import AsyncSessionLocal

    logger.info("=" * 60)
    logger.info("IFC Knowledge Base Ingest")
    logger.info(f"Mode: {'skip existing' if skip_existing else 'full re-ingest'}")
    logger.info("=" * 60)

    start = time.time()

    # ── Phase 1: Scrape (show live URL fetches via httpx INFO logs) ───────────
    logger.info("PHASE 1 — Scraping docs.ifcopenshell.org ...")
    logger.info("  (watch the httpx lines below — each = one page fetched)")
    logger.info("")

    scraper = IFCDocScraper()
    pages = await scraper.scrape_all()

    logger.info("")
    logger.info(f"PHASE 1 DONE — {len(pages)} pages scraped")
    logger.info("")

    if not pages:
        logger.error("No pages scraped! Check your internet connection or the seed URLs.")
        return

    # ── Phase 2: Chunk + Embed + Store ───────────────────────────────────────
    logger.info("PHASE 2 — Chunking, embedding, storing in DB ...")
    logger.info("")

    async with AsyncSessionLocal() as session:
        svc = IFCKnowledgeIngestService(session=session)

        async def progress(page_num: int, total: int, url: str) -> None:
            pct = round(page_num / total * 100) if total else 0
            logger.info(f"  [{page_num:>4}/{total}] {pct:>3}%  {url}")

        # Call ingest_all but pass our already-scraped pages
        # by patching the service to skip re-scraping
        stats = await _ingest_pages(svc, pages, skip_existing, progress)

    elapsed = time.time() - start
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)

    logger.info("")
    logger.info("=" * 60)
    logger.info("INGEST COMPLETE")
    logger.info(f"  Pages scraped:  {stats['pages_scraped']}")
    logger.info(f"  Pages ingested: {stats['pages_ingested']}")
    logger.info(f"  Pages skipped:  {stats['pages_skipped']}")
    logger.info(f"  Chunks created: {stats['chunks_created']}")
    logger.info(f"  Errors:         {stats['errors']}")
    logger.info(f"  Time elapsed:   {mins}m {secs}s")
    logger.info("=" * 60)


async def _ingest_pages(svc, pages, skip_existing: bool, progress_callback) -> dict:
    """
    Ingest pre-scraped pages directly — avoids scraping twice.
    Mirrors IFCKnowledgeIngestService.ingest_all() but takes pages as input.
    """

    stats = {
        "pages_scraped":  len(pages),
        "pages_ingested": 0,
        "pages_skipped":  0,
        "chunks_created": 0,
        "errors":         0,
    }

    for i, page in enumerate(pages):
        if progress_callback:
            await progress_callback(i + 1, len(pages), page.url)

        if skip_existing and await svc._repo.document_exists(page.url):
            logger.debug(f"  Skipping existing: {page.url}")
            stats["pages_skipped"] += 1
            continue

        try:
            count = await svc._ingest_page(page)
            stats["chunks_created"] += count
            stats["pages_ingested"] += 1
            await svc._session.commit()
            logger.debug(f"  ✓ {page.url} → {count} chunks")

        except Exception as exc:
            logger.error(f"  ✗ Failed {page.url}: {exc}", exc_info=True)
            await svc._session.rollback()
            stats["errors"] += 1

    return stats


async def run_single_url(url: str) -> None:
    from app.core.database.session import AsyncSessionLocal
    from app.services.ifc_knowledge_service import IFCKnowledgeIngestService

    logger.info(f"Ingesting single URL: {url}")

    async with AsyncSessionLocal() as session:
        svc = IFCKnowledgeIngestService(session=session)
        chunks = await svc.ingest_url(url=url)

    logger.info(f"Done — {chunks} chunks created")


async def show_status() -> None:
    from app.core.database.session import AsyncSessionLocal
    from app.repositories.ifc_knowledge_repository import IFCKnowledgeRepository

    async with AsyncSessionLocal() as session:
        repo = IFCKnowledgeRepository(session)
        status = await repo.get_status()

    logger.info("")
    logger.info("Current knowledge base status:")
    logger.info(f"  Documents:  {status['document_count']}")
    logger.info(f"  Chunks:     {status['chunk_count']}")
    logger.info(f"  Embedded:   {status['embedded_chunks']}")
    logger.info(f"  By source:  {status['by_source']}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="IFC Knowledge Base Ingest")
    parser.add_argument("--fresh",         action="store_true", help="Re-ingest everything (overwrite existing)")
    parser.add_argument("--skip-existing", action="store_true", help="Skip URLs already in DB (default behaviour)")
    parser.add_argument("--url",           type=str,            help="Ingest a single URL only")
    parser.add_argument("--status",        action="store_true", help="Show current DB status and exit")
    args = parser.parse_args()

    if args.status:
        asyncio.run(show_status())
        return

    if args.url:
        asyncio.run(run_single_url(args.url))
        return

    skip = not args.fresh  # default = skip existing
    asyncio.run(run_full_ingest(skip_existing=skip))


if __name__ == "__main__":
    main()