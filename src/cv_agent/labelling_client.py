"""Synchronous HTTP client for the Label Studio REST API."""

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from pathlib import Path

import httpx

from cv_agent.config import LabellingConfig

logger = logging.getLogger(__name__)

# Label config XML — all 4 annotation types always included
_LABEL_CONFIG_XML = """\
<View>
  <Image name="image" value="$image"/>
  <RectangleLabels name="bbox" toName="image">
    <Label value="object"/>
  </RectangleLabels>
  <PolygonLabels name="polygon" toName="image">
    <Label value="object"/>
  </PolygonLabels>
  <KeyPointLabels name="keypoint" toName="image">
    <Label value="point"/>
  </KeyPointLabels>
  <BrushLabels name="mask" toName="image">
    <Label value="mask"/>
  </BrushLabels>
</View>"""

_SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}

_EXPORT_TYPE_MAP = {
    "COCO": "COCO",
    "YOLO": "YOLO",
    "VOC": "VOC",
}


class LabelStudioClient:
    def __init__(self, cfg: LabellingConfig) -> None:
        self._base = f"http://localhost:{cfg.port}/api"
        self._headers: dict[str, str] = {}
        if cfg.api_token:
            self._headers["Authorization"] = f"Token {cfg.api_token}"

    def _get(self, path: str, **kwargs: object) -> httpx.Response:
        with httpx.Client(timeout=30) as client:
            return client.get(f"{self._base}{path}", headers=self._headers, **kwargs)

    def _post(self, path: str, **kwargs: object) -> httpx.Response:
        with httpx.Client(timeout=60) as client:
            return client.post(f"{self._base}{path}", headers=self._headers, **kwargs)

    def health(self) -> bool:
        try:
            resp = self._get("/health")
            return resp.status_code < 500
        except Exception:
            return False

    def create_project(self, title: str) -> dict:
        resp = self._post(
            "/projects/",
            json={"title": title, "label_config": _LABEL_CONFIG_XML},
        )
        resp.raise_for_status()
        return resp.json()

    def list_projects(self) -> list[dict]:
        resp = self._get("/projects/?page_size=100")
        resp.raise_for_status()
        return resp.json().get("results", [])

    def get_project(self, project_id: int) -> dict:
        resp = self._get(f"/projects/{project_id}/")
        resp.raise_for_status()
        return resp.json()

    def import_images(
        self,
        project_id: int,
        image_dir: str | Path,
    ) -> Generator[dict, None, None]:
        paths = [p for p in Path(image_dir).iterdir() if p.suffix.lower() in _SUPPORTED_EXTS]
        total = len(paths)
        for n, p in enumerate(paths, 1):
            self._upload_one(project_id, p)
            yield {"imported": n, "total": total, "file": p.name}
        if total == 0:
            yield {"imported": 0, "total": 0, "file": "", "done": True}
        else:
            yield {"imported": total, "total": total, "file": "", "done": True}

    def _upload_one(self, project_id: int, path: Path) -> None:
        with open(path, "rb") as f:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{self._base}/projects/{project_id}/import",
                    headers=self._headers,
                    files={"file": (path.name, f, _mime(path))},
                )
        if resp.status_code >= 400:
            logger.warning("Failed to upload %s: %s", path.name, resp.text)

    def trigger_export(self, project_id: int, export_format: str) -> int:
        ls_type = _EXPORT_TYPE_MAP.get(export_format.upper(), "COCO")
        resp = self._post(f"/projects/{project_id}/exports/", json={"exportType": ls_type})
        resp.raise_for_status()
        return resp.json()["id"]

    def poll_export(self, project_id: int, export_id: int, max_wait: int = 60) -> bool:
        import time
        for _ in range(max_wait):
            resp = self._get(f"/projects/{project_id}/exports/{export_id}")
            if resp.status_code == 200:
                status = resp.json().get("status", "")
                if status == "completed":
                    return True
                if status == "failed":
                    return False
            time.sleep(1)
        return False

    def download_export(self, project_id: int, export_id: int) -> bytes:
        resp = self._get(f"/projects/{project_id}/exports/{export_id}/download")
        resp.raise_for_status()
        return resp.content


def _mime(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }.get(ext, "application/octet-stream")


def export_path(dataset_name: str, export_format: str, project_id: int, base: str = "./output") -> Path:
    ext = {"COCO": "json", "YOLO": "zip", "VOC": "zip"}.get(export_format.upper(), "zip")
    return Path(base) / "labels" / dataset_name / export_format.lower() / f"{project_id}.{ext}"
