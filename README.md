# NextRole

Local, multi-agent resume tailoring and interview-prep tool. See `docs/scope.md`,
`docs/requirements.md`, and `docs/spec.md` for the project's scope, requirements,
and technical design. This implementation covers Phases 1-3 (MVP) only:
resume parsing, JD Analyst, Resume Agent, Interview Coach, LangGraph
orchestration, FastAPI backend, React frontend, SQLite persistence, and PDF
export. Company Researcher, Editor Agent, and URL-based JD ingestion are
Future-phase per the project documents and are intentionally not implemented.

## Prerequisites

- Python 3.12+
- Node.js 18+
- [Ollama](https://ollama.com) running locally with a model pulled, e.g.:
  ```
  ollama pull llama3.1:8b
  ```

## Backend

```powershell
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload
```

Runs at `http://localhost:8000`. Configuration is via environment variables
(see `backend/config.py`), e.g. `NEXTROLE_OLLAMA_MODEL`, `NEXTROLE_DB_PATH`.

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

Runs at `http://localhost:5173` and talks to the backend over HTTP.

## Tests

```powershell
python -m pytest
```

Runs the full suite (agents, guardrails, pipeline orchestration, and an
end-to-end MVP workflow) against a FakeOllamaClient, independent of a live
Ollama server (NFR-007). One additional LLM-as-a-Judge test is skipped by
default; opt in with:

```powershell
$env:NEXTROLE_RUN_LLM_TESTS = "1"
python -m pytest -m llm
```

## Known assumptions / limitations

- The LangGraph approval-gate pause uses an in-process `InMemorySaver`
  checkpointer (appropriate for a single-user, single-process local tool,
  NFR-008); an in-flight pending-approval run does not survive a backend
  process restart. Already-generated documents remain in SQLite regardless.
- SEC-002/003 fabrication guardrails are best-effort heuristics (word-overlap
  traceability + numeric-claim + JD-keyword-injection checks), not a
  guarantee of zero false negatives/positives.
- There is no "acknowledge flagged content" endpoint (none is listed in
  `spec.md` Section 7); a tailored resume with unresolved guardrail flags
  stays export-blocked (ERR-008) even after approval.
