---
name: start-task
description: Starts and executes implementation tasks in the Susanoh repository with the repository's own planning and quality rules. Use when the user asks to start work, pick the next task, or continue implementation.
---

# Start Task (Susanoh)

Use this workflow when the user asks to start implementation, pick the next task, or continue development.

## 1. Gather Context First

1. Check branch and working tree (`git branch --show-current`, `git status --short`).
2. Read repository docs in priority order:
   1. `docs/RULE.md`
   2. `docs/SPEC.md`
   3. `docs/PLAN.md`
   4. `README.md`
   5. `docs/PROMPT.md`
3. If docs conflict, follow the priority above and note the mismatch in your response.
4. Identify the smallest deliverable unit (explicit user request first, otherwise next incomplete item in `docs/PLAN.md`).

## 2. Plan the Change

1. List affected areas before editing:
   - Backend: `backend/main.py`, `backend/l1_screening.py`, `backend/l2_gemini.py`, `backend/state_machine.py`, `backend/models.py`, `backend/mock_server.py`
   - Frontend: `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/components/*`
   - Tests: `tests/*`, `frontend/src/**/*.test.ts`
2. Define acceptance criteria tied to user-visible behavior (API response, state transition, dashboard output, or test).
3. If scope is unclear, ask one concise clarification question; otherwise proceed.

## 3. Implement

1. Keep diffs focused on one task.
2. Preserve repository constraints from `docs/RULE.md` and `docs/PROMPT.md`:
   - No Streamlit-based implementation.
   - Keep L2 failure behavior safe-side (`UNDER_SURVEILLANCE` fallback).
   - Respect existing API contracts.
3. Update related docs when behavior or contracts change.

## 4. Verify Locally

Run the narrowest useful checks first, then full checks before handoff:

1. Backend tests: `python3 -m pytest tests -v`
2. Frontend lint: `cd frontend && npm run lint`
3. Frontend tests: `cd frontend && npm run test:run`
4. Frontend build: `cd frontend && npm run build`

If a command cannot run, report why and what remains unverified.

## 5. Commit and Push

1. Use branch naming from `docs/PROMPT.md`: `feat/<scope>`, `fix/<scope>`, `chore/<scope>`.
2. Use Conventional Commit format: `<type>(<scope>): <summary>`.
3. Commit only relevant files.
4. Push to origin: `git push origin <current-branch>`.
5. Report:
   - What changed
   - Validation commands and results
   - Remaining risks or follow-ups
