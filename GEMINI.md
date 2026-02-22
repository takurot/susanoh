# Susanoh (スサノヲ) - Gemini CLI Context

This project is an AI-driven economic defense middleware designed to protect online game economies from RMT (Real Money Trading), money laundering, and bot activities. It uses a hybrid architecture of fast rule-based screening (L1) and deep contextual analysis via Google Gemini (L2).

## Project Overview

- **Core Goal**: Real-time detection, isolation (state machine), and auditing of suspicious in-game transactions.
- **Architecture**:
    - **L1 (Screening)**: High-speed rule evaluation (currently Python in-memory, transitioning to Rust/Redis).
    - **L2 (Analysis)**: Contextual deep-dive using Gemini API to analyze chat logs and transaction patterns.
    - **State Machine**: Controls user capabilities (NORMAL -> RESTRICTED_WITHDRAWAL -> UNDER_SURVEILLANCE -> BANNED).
- **Key Concepts**:
    - **Honeypot Control**: Restricting withdrawals instead of immediate banning to observe actor behavior without risking economic leakage.
    - **Auto-Recovery**: L2 "White" verdicts automatically restore users to NORMAL state.

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy (PostgreSQL support), Pydantic v2, Google GenAI SDK.
- **Frontend**: React 19, TypeScript, Vite, Tailwind CSS v4, `react-force-graph-2d`.
- **Testing**: Pytest (Backend), Vitest (Frontend).

## Development Guide

### Environment Variables

Required for L2 features:
- `GEMINI_API_KEY`: Google AI Studio API key.
- `GEMINI_MODEL`: Defaults to `gemini-2.0-flash`.

Optional:
- `SUSANOH_API_KEYS`: Comma-separated keys for `X-API-KEY` header authentication.
- `DATABASE_URL`: PostgreSQL connection string for snapshot persistence.

### Key Commands

#### Backend
```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# Run
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Test
pytest
```

#### Frontend
```bash
cd frontend
npm install

# Run
npm run dev

# Test
npm test
```

## Directory Structure

- `backend/`: Core logic.
    - `main.py`: Entry point and API routes.
    - `models.py`: Pydantic models and Enums (AccountState, FraudType).
    - `l1_screening.py`: Rule-based engine logic.
    - `l2_gemini.py`: Gemini API integration and prompt engineering.
    - `state_machine.py`: Transition logic and state management.
    - `persistence.py`: SQLAlchemy-based snapshotting.
- `frontend/`: React dashboard.
    - `src/components/`: UI components (NetworkGraph, AuditReport, etc.).
    - `src/api.ts`: Typed API client.
- `docs/`: Technical specifications (`SPEC.md`), roadmaps (`PLAN.md`), and prompt engineering details.
- `tests/`: Comprehensive backend test suite (E2E, unit, integration).

## Development Conventions

- **Surgical Updates**: When modifying the state machine or L1 rules, ensure corresponding updates in `backend/models.py` and `frontend/src/api.ts`.
- **Testing**: Always run `pytest` after backend changes. New features must include an integration test in `tests/`.
- **AI Safety**: Never log or leak `GEMINI_API_KEY`.
- **Frontend**: Use Tailwind CSS v4 utility classes and prefer Vanilla CSS over adding new libraries.
