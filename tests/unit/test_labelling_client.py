"""Unit tests for src/cv_agent/labelling_client.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cv_agent.config import LabellingConfig
from cv_agent.labelling_client import (
    LabelStudioClient,
    _LABEL_CONFIG_XML,
    _SUPPORTED_EXTS,
    export_path,
)


# ---------------------------------------------------------------------------
# Label config XML structure
# ---------------------------------------------------------------------------

class TestLabelConfigXML:
    def test_contains_all_four_annotation_types(self):
        assert "RectangleLabels" in _LABEL_CONFIG_XML
        assert "PolygonLabels" in _LABEL_CONFIG_XML
        assert "KeyPointLabels" in _LABEL_CONFIG_XML
        assert "BrushLabels" in _LABEL_CONFIG_XML

    def test_references_image_element(self):
        assert 'name="image"' in _LABEL_CONFIG_XML
        assert 'value="$image"' in _LABEL_CONFIG_XML

    def test_all_annotation_elements_reference_image(self):
        assert _LABEL_CONFIG_XML.count('toName="image"') == 4


# ---------------------------------------------------------------------------
# Project name format
# ---------------------------------------------------------------------------

class TestProjectNameFormat:
    def test_project_title_uses_date_prefix(self):
        from cv_agent.tools.labelling import _project_title
        title = _project_title("road_damage")
        import re
        assert re.match(r"\d{4}-\d{2}-\d{2}_road_damage", title), f"Got: {title}"

    def test_project_title_lowercases_and_replaces_spaces(self):
        from cv_agent.tools.labelling import _project_title
        title = _project_title("Road Damage Dataset")
        assert " " not in title
        assert title.endswith("road_damage_dataset")


# ---------------------------------------------------------------------------
# Export path convention
# ---------------------------------------------------------------------------

class TestExportPathConvention:
    def test_coco_produces_json(self):
        p = export_path("road_damage", "COCO", 42)
        assert p.suffix == ".json"
        assert "coco" in str(p)

    def test_yolo_produces_zip(self):
        p = export_path("road_damage", "YOLO", 42)
        assert p.suffix == ".zip"
        assert "yolo" in str(p)

    def test_voc_produces_zip(self):
        p = export_path("road_damage", "VOC", 42)
        assert p.suffix == ".zip"
        assert "voc" in str(p)

    def test_path_contains_project_id(self):
        p = export_path("mydata", "COCO", 99)
        assert "99" in p.name

    def test_custom_base_dir_respected(self):
        p = export_path("mydata", "COCO", 1, base="/tmp/output")
        assert str(p).startswith("/tmp/output")


# ---------------------------------------------------------------------------
# LabelStudioClient — mocked httpx
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg() -> LabellingConfig:
    return LabellingConfig(port=18080, host="0.0.0.0", api_token="testtoken")


@pytest.fixture
def client(cfg: LabellingConfig) -> LabelStudioClient:
    return LabelStudioClient(cfg)


class TestLabelStudioClientHealth:
    def test_health_returns_true_on_2xx(self, client: LabelStudioClient):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch.object(client, "_get", return_value=mock_resp):
            assert client.health() is True

    def test_health_returns_false_on_500(self, client: LabelStudioClient):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch.object(client, "_get", return_value=mock_resp):
            assert client.health() is False

    def test_health_returns_false_on_connection_error(self, client: LabelStudioClient):
        with patch.object(client, "_get", side_effect=Exception("refused")):
            assert client.health() is False


class TestLabelStudioClientCreateProject:
    def test_posts_label_config_xml(self, client: LabelStudioClient):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": 42, "title": "2026-03-11_test"}

        with patch.object(client, "_post", return_value=mock_resp) as mock_post:
            result = client.create_project("2026-03-11_test")

        call_kwargs = mock_post.call_args[1]
        assert "label_config" in call_kwargs["json"]
        assert result["id"] == 42

    def test_raises_on_http_error(self, client: LabelStudioClient):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("400")
        with patch.object(client, "_post", return_value=mock_resp):
            with pytest.raises(Exception):
                client.create_project("bad")


class TestLabelStudioClientAuth:
    def test_auth_header_set_when_token_provided(self, cfg: LabellingConfig):
        cfg.api_token = "mytoken"
        c = LabelStudioClient(cfg)
        assert c._headers.get("Authorization") == "Token mytoken"

    def test_no_auth_header_when_token_empty(self):
        cfg = LabellingConfig(port=18080, api_token="")
        c = LabelStudioClient(cfg)
        assert "Authorization" not in c._headers


class TestSupportedExtensions:
    def test_jpg_supported(self):
        assert ".jpg" in _SUPPORTED_EXTS

    def test_png_supported(self):
        assert ".png" in _SUPPORTED_EXTS

    def test_mp4_not_supported(self):
        assert ".mp4" not in _SUPPORTED_EXTS
