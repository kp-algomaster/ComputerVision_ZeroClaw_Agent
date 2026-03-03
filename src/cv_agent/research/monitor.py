"""Research monitor — periodically checks for new CV papers."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from cv_agent.config import AgentConfig, load_config
from cv_agent.research.sources import (
    Paper,
    fetch_arxiv_recent,
    fetch_pwc_trending,
    fetch_s2_recent,
)

logger = logging.getLogger(__name__)


class ResearchMonitor:
    """Monitors multiple research sources for new CV papers."""

    def __init__(self, config: AgentConfig | None = None):
        self.config = config or load_config()
        self.rc = self.config.research
        self._state_file = Path(self.config.output.base_dir) / ".monitor_state.json"
        self._seen_ids: set[str] = self._load_seen()

    def _load_seen(self) -> set[str]:
        if self._state_file.exists():
            data = json.loads(self._state_file.read_text())
            return set(data.get("seen_ids", []))
        return set()

    def _save_seen(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        # Keep only last 5000 IDs to prevent unbounded growth
        trimmed = list(self._seen_ids)[-5000:]
        self._state_file.write_text(json.dumps({
            "seen_ids": trimmed,
            "last_check": datetime.now().isoformat(),
        }))

    def check_all_sources(self) -> list[Paper]:
        """Check all configured sources and return new papers."""
        all_papers: list[Paper] = []

        # ArXiv
        if self.rc.sources.arxiv.enabled:
            logger.info("Checking ArXiv...")
            arxiv_papers = fetch_arxiv_recent(
                categories=self.rc.sources.arxiv.categories,
                queries=self.rc.sources.arxiv.queries,
                max_results=self.rc.sources.arxiv.max_results_per_query,
            )
            all_papers.extend(arxiv_papers)
            logger.info(f"ArXiv: {len(arxiv_papers)} papers found")

        # Papers With Code
        if self.rc.sources.papers_with_code.enabled:
            logger.info("Checking Papers With Code...")
            pwc_papers = fetch_pwc_trending(
                areas=self.rc.sources.papers_with_code.areas,
            )
            all_papers.extend(pwc_papers)
            logger.info(f"Papers With Code: {len(pwc_papers)} papers found")

        # Semantic Scholar
        if self.rc.sources.semantic_scholar.enabled:
            logger.info("Checking Semantic Scholar...")
            s2_papers = fetch_s2_recent(
                fields_of_study=self.rc.sources.semantic_scholar.fields_of_study,
                api_key=self.rc.sources.semantic_scholar.api_key,
            )
            all_papers.extend(s2_papers)
            logger.info(f"Semantic Scholar: {len(s2_papers)} papers found")

        # Filter to new papers only
        new_papers = [p for p in all_papers if p.id not in self._seen_ids]
        for p in new_papers:
            self._seen_ids.add(p.id)
        self._save_seen()

        logger.info(f"Total new papers: {len(new_papers)}")
        return new_papers

    def get_papers_by_topic(self, papers: list[Paper]) -> dict[str, list[Paper]]:
        """Group papers by CV topic based on keywords in title/abstract."""
        topics: dict[str, list[Paper]] = {
            "Object Detection": [],
            "Segmentation": [],
            "3D Vision": [],
            "Video Understanding": [],
            "Vision-Language Models": [],
            "Generative Models": [],
            "Foundation Models": [],
            "Medical Imaging": [],
            "Autonomous Driving": [],
            "Robotics Vision": [],
            "Other": [],
        }

        topic_keywords = {
            "Object Detection": ["detection", "yolo", "detr", "rcnn", "anchor"],
            "Segmentation": ["segment", "mask", "semantic", "panoptic", "instance"],
            "3D Vision": ["3d", "nerf", "gaussian splat", "point cloud", "depth", "stereo", "reconstruction"],
            "Video Understanding": ["video", "temporal", "action recognition", "tracking", "optical flow"],
            "Vision-Language Models": ["vision-language", "vlm", "clip", "multimodal", "visual question"],
            "Generative Models": ["diffusion", "gan", "generative", "image synthesis", "image generation"],
            "Foundation Models": ["foundation", "pretrain", "self-supervised", "contrastive", "mae", "dino"],
            "Medical Imaging": ["medical", "clinical", "pathology", "radiology", "ct scan", "mri"],
            "Autonomous Driving": ["autonomous", "self-driving", "lidar", "bird's eye", "bev"],
            "Robotics Vision": ["robot", "manipulation", "grasp", "navigation", "slam"],
        }

        for paper in papers:
            text = f"{paper.title} {paper.abstract}".lower()
            placed = False
            for topic, keywords in topic_keywords.items():
                if any(kw in text for kw in keywords):
                    topics[topic].append(paper)
                    placed = True
                    break
            if not placed:
                topics["Other"].append(paper)

        # Remove empty topics
        return {k: v for k, v in topics.items() if v}
