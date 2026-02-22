---
name: code-review
description: Reviews Susanoh pull requests for regressions, spec drift, and missing tests across FastAPI backend and React/TypeScript frontend. Use when the user asks for a PR review or code quality check.
---

# Code Review (Susanoh)

Use this workflow when reviewing PRs or branch diffs in this repository.

## Review Goal

Prioritize bugs, behavior regressions, and spec/documentation drift over style-only comments.

## 1. Gather Context

1. Determine review range:
   - `git log --oneline main..HEAD`
   - `git diff --name-only main...HEAD`
2. Read relevant docs in this order when behavior/spec is involved:
   1. `docs/RULE.md`
   2. `docs/SPEC.md`
   3. `docs/PLAN.md`
   4. `README.md`
   5. `docs/PROMPT.md`
3. If docs disagree with implementation, flag as a finding.

## 2. Repository-Specific Checks

### Backend (`backend/*.py`)

- `backend/state_machine.py`
  - Allowed transitions only.
  - Withdraw behavior aligns with state model.
- `backend/l1_screening.py`
  - 5-minute window purge correctness.
  - Rule triggers (`R1`-`R4`) and counters.
- `backend/l2_gemini.py`
  - API-key-missing and API-failure fallback remains safe-side.
  - Structured output parsing handles bad data safely.
- `backend/main.py`
  - API contracts and status codes stay compatible.
  - Async/background paths do not silently lose critical failures.

### Frontend (`frontend/src/*`)

- `frontend/src/api.ts`
  - Endpoint paths and error handling match backend responses.
- Dashboard components
  - Polling/rendering uses available fields only.
  - State colors/labels match backend enum values.

### Tests

- Backend tests in `tests/` cover modified behavior.
- Frontend tests in `frontend/src/**/*.test.ts` cover changed UI logic.
- Flag missing tests for risky logic changes.

### Docs

- If API/behavior changed, `README.md`, `docs/SPEC.md`, and `docs/PLAN.md` are consistent with code.
- Do not present roadmap items as already implemented.

## 3. Validation Commands

Run what is relevant to the touched areas:

- Backend: `python3 -m pytest tests -v`
- Frontend lint: `cd frontend && npm run lint`
- Frontend tests: `cd frontend && npm run test:run`
- Frontend build: `cd frontend && npm run build`

If not run, state it explicitly as review risk.

## 4. Reporting Format

1. Findings first, ordered by severity:
   - `[blocking]`, `[important]`, `[nit]`
2. Include concrete references (`path:line`).
3. Add open questions/assumptions.
4. Keep summary short.
5. If no findings, say so explicitly and mention remaining risk gaps.

## Optional Deep References

- [Architecture Review Guide](reference/architecture-review-guide.md)
- [Performance Review Guide](reference/performance-review-guide.md)
- [Security Review Guide](reference/security-review-guide.md)
- [Common Bugs Checklist](reference/common-bugs-checklist.md)
- [PR Review Template](assets/pr-review-template.md)
- [Review Checklist](assets/review-checklist.md)
