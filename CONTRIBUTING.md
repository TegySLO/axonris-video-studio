# Contributing to Axonris Video Studio

Thank you for your interest in contributing! This tool is designed to help Axonris Hub users create videos, and to be modified by the people who use it.

## Ways to Contribute

- Bug reports and feature requests (open an issue)
- Bug fixes
- New templates (see "Adding a New Template" below)
- New generation-pipeline stages (script-gen / TTS / caption-timing providers — see "Adding a New Pipeline Stage")
- Documentation improvements

## Development Setup

1. Fork and clone the repository
2. `python -m venv .venv && .venv\Scripts\activate` (Windows)
3. `pip install -r requirements.txt`
4. Run the app once (`python video_studio_gui.py`) to go through the first-run setup wizard

## Adding a New Template

1. Create a new folder under `templates/`
2. Include a `config.json` describing the template's parameters (see `templates/concept-explainer-short/config.json` for the reference shape)
3. Add a `README.md` explaining what the template produces and its parameters
4. Register it in `templates/registry.json`
5. Test it end-to-end through the app's template picker before submitting a PR

## Adding a New Pipeline Stage

Each pipeline stage (script generation, text-to-speech, caption timing) is an independently swappable component (see `docs/architecture.md`, Task 5 of the Foundation plan). To add a new provider for an existing stage, implement its interface and register it — do not modify the stage's call sites.

## Project Tracking

- `ROADMAP.md` — planned work
- `BACKLOG.md` — unscheduled ideas, open for anyone to pick up
- `CHANGELOG.md` — shipped history

## Pull Request Process

Feature branch → implement → test locally → update relevant docs → submit PR with a clear description of what changed and why. We (the Axonris team) review and merge; accepted changes ship in the next Hub-distributed release.
