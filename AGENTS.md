# Repository Guidelines

## Project Structure & Module Organization
`tripleten-analyzer` is a Python pipeline project.

- `src/`: core domain logic (`parsers/`, `transcription/`, `enrichment/`, `analysis/`).
- `scripts/`: runnable entry points (`data_prep`, `run_enrichment`, `run_analysis`, `run_pipeline`).
- `tests/`: pytest suites aligned to features (`test_parsers.py`, `test_analysis.py`, etc.).
- `data/`: pipeline artifacts (`source/`, `raw/`, `enriched/`, `output/`).
- `config/config.yaml`: non-secret runtime configuration.
- `.env` (local only): API keys and environment-specific secrets.

## Build, Test, and Development Commands
- `python -m venv venv` then `venv\Scripts\activate` (Windows): create/activate local environment.
- `pip install -r requirements.txt`: install runtime and test dependencies.
- `pytest tests -v`: run the full test suite.
- `python -m scripts.data_prep`: run Phase 1 data preparation.
- `python -m scripts.run_pipeline`: run the full 6-step pipeline.
- `python -m scripts.run_pipeline --from-step 3 --skip-steps 4`: resume from a later step.

## Coding Style & Naming Conventions
- Target Python 3.11+ and follow PEP 8 with 4-space indentation.
- Use `snake_case` for modules, functions, and variables; `PascalCase` for classes.
- Keep reusable logic in `src/`; keep orchestration and CLI handling in `scripts/`.
- Add concise docstrings and type hints for public functions and non-trivial logic.
- No enforced formatter is configured; keep style consistent with existing files.

## Testing Guidelines
- Framework: `pytest` with test files named `test_*.py`.
- Test behavior at unit level (parsing, transformations, metric calculations, response parsing).
- Keep tests deterministic and API-independent; mock external services where needed.
- Add regression tests for every bug fix and pipeline edge case.

## Commit & Pull Request Guidelines
- History favors imperative subjects, often Conventional Commit style (for example, `feat: ...`).
- Prefer: `<type>: <short summary>` where type is `feat`, `fix`, `test`, or `chore`.
- Keep each commit focused on one logical change.
- PRs should include: purpose, affected pipeline steps, commands run (at minimum `pytest tests -v`), and key output paths changed (for example, `data/output/analysis_report.md`).
- Call out API-cost or credential-impacting changes explicitly.

## Security & Configuration Tips
- Never commit `.env`, API keys, or cookie files.
- Keep secrets in environment variables referenced by `.env.example`.
- Review `config/config.yaml` defaults before long or paid pipeline runs.
