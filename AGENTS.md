# Repository Guidelines

## Project Structure & Module Organization
- `backend/`: FastAPI backend and core fraud logic (`main.py`, `state_machine.py`, `l1_screening.py`, `l2_gemini.py`).
- `frontend/`: React + TypeScript dashboard (`src/`), with Vite build tooling.
- `tests/`: Backend pytest suite (`test_*.py`) covering API, state transitions, L1/L2 behavior, and E2E flows.
- `docs/`: Product and implementation references (`SPEC.md`, `PLAN.md`, `PROMPT.md`, `RULE.md`).
- `.agent/skills/`: Agent skill definitions and references used during automated development workflows.

## Project Skills
- `start-task`: Starts and executes implementation tasks with Susanoh-specific planning and quality rules. Path: `.agent/skills/start-task/SKILL.md`
- `code-review`: Reviews PRs/branch diffs for regressions, spec drift, and missing tests. Path: `.agent/skills/code-review/SKILL.md`

### Skill Trigger Rules
- If the user explicitly names a skill (e.g. `$start-task`, `$code-review`), load and follow that skill.
- If the request clearly matches a skill description, load and follow the matching skill.

## Build, Test, and Development Commands
- Backend setup: `python3 -m venv .venv && .venv/bin/python -m pip install -r backend/requirements.txt`
- Run backend: `.venv/bin/python -m uvicorn backend.main:app --reload`
- Frontend setup: `cd frontend && npm install`
- Run frontend dev server: `cd frontend && npm run dev`
- Backend tests: `.venv/bin/python -m pytest tests -v`
- Frontend lint: `cd frontend && npm run lint`
- Frontend tests: `cd frontend && npm run test:run`
- Frontend build: `cd frontend && npm run build`

## Coding Style & Naming Conventions
- Python: 4-space indentation, type hints preferred, concise functions, explicit state transitions.
- TypeScript/React: component files in `PascalCase` where applicable, variables/functions in `camelCase`, test files as `*.test.ts`.
- Keep API contracts stable in `backend/main.py` and `backend/models.py`.
- Avoid manual edits to generated outputs such as `frontend/dist/` and dependency trees.

## Testing Guidelines
- Frameworks: `pytest` + `pytest-asyncio` (backend), `vitest` (frontend).
- Naming: backend tests use `tests/test_<feature>.py`; frontend tests use `<feature>.test.ts`.
- Prefer TDD for risky logic (state machine rules, auth checks, L1/L2 decision paths).
- Before opening a PR, run backend tests, frontend lint/tests, and frontend build.

## Commit & Pull Request Guidelines
- Follow Conventional Commits seen in history: `feat(scope): ...`, `fix(scope): ...`, `chore(scope): ...`.
- Branch naming: `feat/<scope>`, `fix/<scope>`, `chore/<scope>`.
- PRs should include: summary, changed files/areas, validation commands run, and remaining risks.
- Update docs (`README.md`, `docs/SPEC.md`, `docs/PLAN.md`) when behavior or contracts change.

## Security & Configuration Tips
- Use env vars only for secrets/config: `GEMINI_API_KEY`, optional `GEMINI_MODEL`, and optional `SUSANOH_API_KEYS`.
- If `SUSANOH_API_KEYS` is set, all `/api/v1/*` requests must include valid `X-API-KEY`.
- Never commit API keys or credentials.
