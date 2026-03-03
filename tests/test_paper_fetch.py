"""Tests for paper fetching tools."""

import pytest

from cv_agent.tools.paper_fetch import _extract_arxiv_id


def test_extract_id_from_abs_url():
    assert _extract_arxiv_id("https://arxiv.org/abs/2312.00785") == "2312.00785"


def test_extract_id_from_pdf_url():
    assert _extract_arxiv_id("https://arxiv.org/pdf/2312.00785") == "2312.00785"


def test_extract_id_raw():
    assert _extract_arxiv_id("2312.00785") == "2312.00785"


def test_extract_id_with_version():
    assert _extract_arxiv_id("https://arxiv.org/abs/2312.00785v2") == "2312.00785"
