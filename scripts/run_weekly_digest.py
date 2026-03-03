#!/usr/bin/env python3
"""Cron-friendly script to generate the weekly CV research digest.

Add to crontab for automatic weekly digests:
    0 8 * * 1 cd /path/to/CV_Zero_Claw_Agent && .venv/bin/python scripts/run_weekly_digest.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cv_agent.config import load_config
from cv_agent.research.digest import generate_weekly_digest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()
    logger.info("Starting weekly digest generation...")

    digest = await generate_weekly_digest(config)

    # Print summary
    lines = digest.split("\n")
    title = next((l for l in lines if l.startswith("#")), "Digest")
    paper_count = digest.count("###")
    logger.info(f"Generated: {title}")
    logger.info(f"Papers covered: ~{paper_count}")


if __name__ == "__main__":
    asyncio.run(main())
