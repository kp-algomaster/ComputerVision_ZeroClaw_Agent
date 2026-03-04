"""Specialized standalone sub-agents for CV Zero Claw Agent."""

from cv_agent.agents.blog_writer import run_blog_writer_agent
from cv_agent.agents.website_maintenance import run_website_maintenance_agent
from cv_agent.agents.model_training import run_model_training_agent
from cv_agent.agents.data_visualization import run_data_visualization_agent
from cv_agent.agents.paper_to_code import run_paper_to_code_agent
from cv_agent.agents.digest import run_digest_agent

__all__ = [
    "run_blog_writer_agent",
    "run_website_maintenance_agent",
    "run_model_training_agent",
    "run_data_visualization_agent",
    "run_paper_to_code_agent",
    "run_digest_agent",
]

AGENT_REGISTRY: dict[str, dict] = {
    "blog_writer": {
        "name": "Blog Writer Agent",
        "description": "Writes research blog posts from paper summaries, digests, or topics.",
        "icon": "✍️",
        "runner": run_blog_writer_agent,
        "config_key": "blog_writer",
    },
    "website_maintenance": {
        "name": "Website Maintenance Agent",
        "description": "Audits websites for broken links, uptime, and SEO health.",
        "icon": "🌐",
        "runner": run_website_maintenance_agent,
        "config_key": "website_maintenance",
    },
    "model_training": {
        "name": "Model Training Agent",
        "description": "Assists with training config generation, cost estimation, and script scaffolding.",
        "icon": "🏋️",
        "runner": run_model_training_agent,
        "config_key": "model_training",
    },
    "data_visualization": {
        "name": "Data Visualization Agent",
        "description": "Generates chart code and extracts metrics tables from papers and datasets.",
        "icon": "📊",
        "runner": run_data_visualization_agent,
        "config_key": "data_visualization",
    },
    "paper_to_code": {
        "name": "Paper to Code Agent",
        "description": "Scaffolds full PyTorch implementations directly from ArXiv papers.",
        "icon": "📄→💻",
        "runner": run_paper_to_code_agent,
        "config_key": "paper_to_code",
    },
    "digest_writer": {
        "name": "Digest Writer Agent",
        "description": "Searches arXiv and generates magazine-style weekly CV research digests.",
        "icon": "📰",
        "runner": run_digest_agent,
        "config_key": "digest_writer",
    },
}
