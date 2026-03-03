# Claude Code Instructions

## Commit Rules

- NEVER add `Co-Authored-By` trailers or any Claude attribution to commit messages
- Keep commit messages concise: one-line subject + optional bullet body
- Use present tense imperative ("add", "fix", "update") not past tense
- Stage specific files by name — never `git add -A` or `git add .`
- Do NOT push unless explicitly asked

## Code Style

- Python 3.11+, PydanticV2, ruff line-length 100
- Async-first: use `async/await` for I/O bound operations
- Tools decorated with `@tool` from `zeroclaw_tools`
- No docstrings on trivial functions; only where logic isn't self-evident

## Project Conventions

- Config loaded via `load_config()` — never hardcode paths or keys
- Secrets live in `.env` only — never commit `.env`
- New tools go in `src/cv_agent/tools/` and are registered in `agent.py:build_tools()`
- `src/zeroclaw_tools/__init__.py` is the local shim — edit it if the tool interface changes
