"""Unit tests for src/cv_agent/tools/labelling.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from cv_agent.tools.labelling import (
    _pending_nodes,
    _project_title,
    _register_pending_node,
)


# ---------------------------------------------------------------------------
# _register_pending_node
# ---------------------------------------------------------------------------

class TestRegisterPendingNode:
    def setup_method(self):
        _pending_nodes.clear()

    def test_node_is_stored(self):
        _register_pending_node(
            node_id="abc123",
            dataset_name="road",
            project_id=1,
            project_title="2026-03-11_road",
            image_dir="/tmp/imgs",
            annotation_types="bbox",
            export_format="COCO",
            images_imported=10,
        )
        assert "abc123" in _pending_nodes

    def test_node_has_pending_status(self):
        _register_pending_node(
            node_id="xyz999",
            dataset_name="pothole",
            project_id=2,
            project_title="2026-03-11_pothole",
            image_dir="/tmp",
            annotation_types="polygon",
            export_format="YOLO",
            images_imported=5,
        )
        assert _pending_nodes["xyz999"]["status"] == "pending"

    def test_node_stores_project_id(self):
        _register_pending_node(
            node_id="node1",
            dataset_name="cats",
            project_id=99,
            project_title="2026-03-11_cats",
            image_dir="/data",
            annotation_types="bbox",
            export_format="COCO",
            images_imported=0,
        )
        assert _pending_nodes["node1"]["project_id"] == 99

    def test_node_stores_created_at(self):
        _register_pending_node(
            node_id="node2",
            dataset_name="dogs",
            project_id=3,
            project_title="2026-03-11_dogs",
            image_dir="/data",
            annotation_types="mask",
            export_format="VOC",
            images_imported=2,
        )
        assert "created_at" in _pending_nodes["node2"]


# ---------------------------------------------------------------------------
# create_labelling_dag_node — returns node_id
# ---------------------------------------------------------------------------

class TestCreateDagNodeReturnsNodeId:
    def setup_method(self):
        _pending_nodes.clear()

    def _make_mock_client(self, project_id: int = 42):
        client = MagicMock()
        client.health.return_value = True
        client.create_project.return_value = {"id": project_id, "title": "2026-03-11_test"}
        client.import_images.return_value = iter([
            {"imported": 1, "total": 1, "file": "img.jpg", "done": True}
        ])
        return client

    def test_returns_node_id_in_json(self):
        from cv_agent.tools.labelling import create_labelling_dag_node
        mock_client = self._make_mock_client()
        with patch("cv_agent.tools.labelling._client", return_value=mock_client):
            with patch("cv_agent.tools.labelling.load_config") as mock_cfg:
                mock_cfg.return_value.labelling.port = 8080
                mock_cfg.return_value.labelling.host = "0.0.0.0"
                result_str = create_labelling_dag_node.invoke({
                    "dataset_name": "test",
                    "image_dir": "/nonexistent",
                    "annotation_types": "bbox",
                    "export_format": "COCO",
                })
        result = json.loads(result_str)
        assert "node_id" in result
        assert len(result["node_id"]) == 12

    def test_node_is_registered_in_pending_nodes(self):
        from cv_agent.tools.labelling import create_labelling_dag_node
        mock_client = self._make_mock_client(project_id=7)
        with patch("cv_agent.tools.labelling._client", return_value=mock_client):
            with patch("cv_agent.tools.labelling.load_config") as mock_cfg:
                mock_cfg.return_value.labelling.port = 8080
                mock_cfg.return_value.labelling.host = "0.0.0.0"
                result_str = create_labelling_dag_node.invoke({
                    "dataset_name": "mydata",
                    "image_dir": "/nonexistent",
                    "annotation_types": "polygon",
                    "export_format": "YOLO",
                })
        result = json.loads(result_str)
        node_id = result["node_id"]
        assert node_id in _pending_nodes
        assert _pending_nodes[node_id]["status"] == "pending"
        assert _pending_nodes[node_id]["project_id"] == 7

    def test_returns_error_when_server_not_running(self):
        from cv_agent.tools.labelling import create_labelling_dag_node
        mock_client = MagicMock()
        mock_client.health.return_value = False
        with patch("cv_agent.tools.labelling._client", return_value=mock_client):
            with patch("cv_agent.tools.labelling.load_config"):
                result_str = create_labelling_dag_node.invoke({
                    "dataset_name": "test",
                    "image_dir": "/tmp",
                    "annotation_types": "bbox",
                    "export_format": "COCO",
                })
        result = json.loads(result_str)
        assert "error" in result


# ---------------------------------------------------------------------------
# _project_title
# ---------------------------------------------------------------------------

class TestProjectTitle:
    def test_returns_string_with_date_prefix(self):
        import re
        title = _project_title("pothole")
        assert re.match(r"\d{4}-\d{2}-\d{2}_pothole", title)

    def test_spaces_replaced_with_underscores(self):
        title = _project_title("my dataset")
        assert " " not in title
        assert "my_dataset" in title

    def test_uppercased_input_lowercased(self):
        title = _project_title("RoadDamage")
        assert "roaddamage" in title
