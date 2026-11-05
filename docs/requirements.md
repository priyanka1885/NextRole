# NextRole — Product Requirements Document (PRD)

> Source of truth for scope: `docs/scope.md`. Assumptions (where `scope.md` was silent) are flagged **(A)**.

## Table of Contents
1. [Product Overview](#1-product-overview)
2. [Problem Statement](#2-problem-statement)
3. [Vision and Objectives](#3-product-vision-and-objectives)
4. [Target Users and Personas](#4-target-users-and-user-personas)
5. [User Journey and Workflows](#5-user-journey-and-main-workflows)
6. [Functional Requirements](#6-functional-requirements)
7. [Agent-Specific Requirements](#7-agent-specific-requirements)
8. [Input Requirements](#8-input-requirements)
9. [Output Requirements](#9-output-requirements)
10. [Frontend Requirements (React)](#10-frontend-requirements-react)
11. [Backend Requirements (FastAPI)](#11-backend-requirements-fastapi)
12. [Multi-Agent Workflow Requirements](#12-multi-agent-workflow-requirements)
13. [Document Generation Requirements](#13-document-generation-requirements)
14. [Chat-Based Editing Requirements](#14-chat-based-editing-requirements)
15. [Non-Functional Requirements](#15-non-functional-requirements)
16. [Security and Guardrail Requirements](#16-security-and-guardrail-requirements)
17. [Error Handling and Edge Cases](#17-error-handling-and-edge-cases)
18. [User Stories with Acceptance Criteria](#18-user-stories-with-acceptance-criteria)
19. [MVP Requirements and Priorities](#19-mvp-requirements-and-priorities)
20. [Future Enhancements](#20-future-enhancements)
21. [Success Metrics](#21-success-metrics)
22. [Requirement ID Index](#22-requirement-id-index)

---

## 1. Product Overview
- Local, multi-agent system: resume (PDF/DOCX) + JD (text/URL) → tailored resume, company research report, interview prep doc, interview cheat sheet.
- 5 agents (JD Analyst, Company Researcher, Resume Agent, Interview Coach, Editor Agent) orchestrated via LangGraph.
- Local Ollama LLMs only, no paid API. React frontend + FastAPI backend + SQLite. Single-user, local-only tool.

## 2. Problem Statement
- Manual resume tailoring, company research, and interview prep per application is slow, repetitive, and fragmented across tools. NextRole consolidates this into one grounded, repeatable pipeline.

## 3. Product Vision and Objectives
**Vision:** One local tool turning a resume + JD into a trustworthy prep package in minutes, with zero fabrication and no recurring cost.

**Objectives:**
- O-1: Cut active prep time from hours to minutes.
- O-2: Tailored resume fully traceable to source resume (no fabricated content).
- O-3: Structured company/role understanding (post-MVP).
- O-4: Interview Q&A grounded in actual resume content.
- O-5: Conversational document refinement (post-MVP).
- O-6: Fully local, open-source LLM stack.

## 4. Target Users and User Personas
- **Primary — Job-seeking engineer:** applies to multiple roles locally; wants faster, consistent tailoring + prep without fabrication risk.
- **Secondary — Developer-operator (A):** builds/dogfoods NextRole; needs visibility into intermediate agent outputs to debug quality/regressions.
- Explicitly out of scope: recruiters, hiring teams, multi-tenant/hosted users.

## 5. User Journey and Main Workflows
**A — New application prep:** upload resume → submit JD → JD Analyst (+ Company Researcher, future) → Resume Agent drafts resume → **user approval gate** → Interview Coach generates prep → user reviews all outputs.

**B — Conversational refinement (future):** user requests a chat edit on any document → Editor Agent applies it → if resume edited, it re-enters the approval gate → repeat until satisfied.

**C — Export and use:** download approved resume PDF; review cheat sheet (future) before interview.

## 6. Functional Requirements

| ID | Requirement |
|---|---|
| FR-001 | Accept resume upload (PDF/DOCX). |
| FR-002 | Parse resume into structured text for downstream agents. |
| FR-003 | Accept JD as pasted text. |
| FR-004 | Accept JD via URL, fetch + parse. *(Future)* |
| FR-005 | Orchestrate JD Analyst, Resume Agent, Interview Coach via one LangGraph pipeline. |
| FR-006 | Persist session inputs/outputs locally in SQLite. |
| FR-007 | Export approved tailored resume as PDF via RenderCV. |
| FR-008 | Require explicit user approval of tailored resume before export/final. No other document requires approval. |
| FR-009 | Allow chat-based edits to any document regardless of approval status. *(Editor Agent: future)* |
| FR-010 | Surface partial result + status if one agent fails; don't abort whole run. |
| FR-011 | Expose all functionality via FastAPI REST API. |
| FR-012 | React frontend covers upload, status, review, approval, (future) chat editing. |

## 7. Agent-Specific Requirements

**7.1 JD Analyst (MVP)**
- FR-013 Extract required skills. FR-014 Extract responsibilities. FR-015 Extract experience requirements. FR-016 Extract technical keywords. FR-017 Extract preferred qualifications (separate from required). FR-018 Output as Pydantic-validated schema.

**7.2 Company Researcher (Future)**
- FR-019 Web search for company info. FR-020 Extract page content (BeautifulSoup). FR-021 Summarize products/business model. FR-022 Summarize culture/recent news. FR-023 Degrade gracefully on search/scrape failure, pipeline continues.

**7.3 Resume Agent (MVP)**
- FR-024 Tailor wording/emphasis to JD. FR-025 No fabrication — only rephrase/reorder/emphasize existing content, never invent skills/employers/titles/achievements/metrics. FR-026 Add JD keywords only where backed by existing resume content. FR-027 Output stays unapproved until user approves (FR-008). FR-028 Revisable via Editor Agent *(future)*.

**7.4 Interview Coach (MVP)**
- FR-029 Generate self-introduction. FR-030 Technical questions. FR-031 HR/behavioral questions. FR-032 Project-based questions. FR-033 STAR answers grounded in resume (same no-fabrication rule as FR-025). FR-034 Interview-day cheat sheet *(future)*.

**7.5 Editor Agent (Future)**
- FR-035 Interpret chat edit requests. FR-036 Identify target document. FR-037 Maintain context across edit turns. FR-038 Support edits on all 4 document types.

## 8. Input Requirements
- FR-039 Max resume file size, default 10MB (A); reject larger with error.
- FR-040 Reject resumes with no extractable text (e.g., scanned images).
- FR-041 JD text length bounds: min 50 / max 20,000 chars (A).
- FR-042 Validate JD URL format/reachability before fetch. *(Future)*
- FR-043 Reject unsupported file types, list accepted formats.

## 9. Output Requirements
- FR-044 Tailored resume as PDF (RenderCV), preserving standard sections.
- FR-045 Company research report: overview, products/business model, culture, news, role relevance. *(Future)*
- FR-046 Interview prep doc: intro, technical/HR/project questions + STAR answers, clearly sectioned.
- FR-047 Cheat sheet: single condensed doc. *(Future)*
- FR-048 All outputs viewable in UI; resume downloadable as PDF, others at least viewable/copyable at MVP.

## 10. Frontend Requirements (React)
- FR-049 Upload form (resume + JD text; URL field reserved). FR-050 Per-document viewer. FR-051 Chat panel *(future)*. FR-052 Loading/progress indicators for long-running steps. FR-053 Approve / Request-changes actions on resume; export gated on approval. FR-054 Clear, actionable error states with retry.

## 11. Backend Requirements (FastAPI)
- FR-055 Upload/parse resume endpoint. FR-056 Submit JD endpoint (text; URL later). FR-057 Trigger pipeline run endpoint. FR-058 Fetch documents/run status endpoint. FR-059 Submit chat edit endpoint *(future)*. FR-060 Approve/reject resume endpoint. FR-061 Pydantic validation on all request/response bodies. FR-062 Async handling (background task + polling/streaming) for long-running LLM calls.

## 12. Multi-Agent Workflow Requirements
- FR-063 Shared LangGraph state object across agent nodes. FR-064 Conditional routing on per-node success/failure. FR-065 Bounded retry policy for transient failures, up to 2 retries (A). FR-066 On unrecoverable failure, halt only that branch, return completed outputs + reason.

## 13. Document Generation Requirements
- FR-067 RenderCV template fits all Resume Agent sections without dropping content. FR-068 Validate rendered PDF is non-empty/well-formed before returning. FR-069 At least one configurable resume template at MVP.

## 14. Chat-Based Editing Requirements (Future)
- FR-070 Resolve which document/section a chat message targets. FR-071 Re-validate edits against no-fabrication rule (FR-025) before display. FR-072 Retain per-session edit history.

## 15. Non-Functional Requirements
| ID | Requirement |
|---|---|
| NFR-001 | No hard real-time requirement; agent steps complete in seconds–minutes locally. |
| NFR-002 | Runs on a single local machine (Windows), no cloud infra required. |
| NFR-003 | Resume/personal data stays local by default. |
| NFR-004 | No paid LLM API as a core/required dependency. |
| NFR-005 | One agent's failure doesn't crash the pipeline; partial results surfaced. |
| NFR-006 | Agents are modular and independently testable. |
| NFR-007 | Core logic unit-testable with Pytest, independent of live LLM calls. |
| NFR-008 | Single-user only; no concurrency requirement. |

## 16. Security and Guardrail Requirements
| ID | Requirement |
|---|---|
| SEC-001 | Prompt injection resistance: system instructions isolated from user/scraped content; embedded instructions in that content are never followed. |
| SEC-002 | Automated check flags any resume content not traceable to the source resume. |
| SEC-003 | Automated check flags numeric claims (%, counts, durations) not traceable to source resume. |
| SEC-004 | No personal data sent to third parties except local Ollama and search queries (search queries exclude personal data). |
| SEC-005 | Uploaded files and scraped content sanitized before use in LLM/render pipeline. |
| SEC-006 | Generated content screened for unsafe/policy-violating output before display. |

## 17. Error Handling and Edge Cases
| ID | Scenario → Behavior |
|---|---|
| ERR-001 | Unparseable/unsupported resume → reject at upload with specific message; no pipeline run. |
| ERR-002 | JD URL unreachable/unparseable → error + fallback prompt to paste text. |
| ERR-003 | Search/scrape failure → Company Researcher returns partial result + notice; rest of pipeline continues. |
| ERR-004 | LLM call timeout/error → retry per FR-065, then surfaced error + manual retry option. |
| ERR-005 | Agent output fails schema validation → retry once, else show raw/partial output with a warning. |
| ERR-006 | JD text empty/too short → inline validation error, submission blocked. |
| ERR-007 | User rejects resume at approval gate → resume returns to editable state; export stays disabled. |
| ERR-008 | Fabrication guardrail flags content → surfaced at/before approval gate, not auto-silently corrected; blocks export until acknowledged. |

## 18. User Stories with Acceptance Criteria

| ID | Story | Acceptance Criteria |
|---|---|---|
| US-001 | Upload resume | Valid PDF/DOCX parses successfully (FR-001/002/039/040); unsupported type → clear error, no run starts (ERR-001). |
| US-002 | Submit JD | Valid text → structured JD extraction (FR-003/013-018); too-short text → blocked with inline message (ERR-006). |
| US-003 | Get tailored resume | Draft contains only source-traceable content (FR-024/025, SEC-002/003); flagged content visibly marked (ERR-008). |
| US-004 | Approve resume | Approve → export enabled (FR-008/027/053); Request changes → stays editable, export disabled (ERR-007). |
| US-005 | Export resume PDF | Approved resume renders as valid, non-empty PDF (FR-007/044/067/068). |
| US-006 | Get interview prep | Intro + technical/HR/project questions + STAR answers, all resume-grounded (FR-029-033). |
| US-007 | Research company *(future)* | Success → structured report (FR-019-022/045); search down → partial result + notice, pipeline continues (ERR-003). |
| US-008 | Chat-edit a document *(future)* | Edit applies to correct document (FR-009/035-037/070); if resume edited, re-enters approval gate. |
| US-009 | Handle bad JD URL *(future)* | Fetch/parse failure → error + prompt to paste text instead (ERR-002). |

## 19. MVP Requirements and Priorities
MVP mirrors `scope.md` §11–12. Company Researcher and Editor Agent are fully specified (Section 7) but **not** MVP.

| Phase | Priority | Requirements |
|---|---|---|
| 1 — Core pipeline | Highest | FR-001–003, 005, 011–018, 024–027, 039–041, 043, 049, 050, 052–055, 056(text), 057–058, 060–064, 069 |
| 2 — Interview prep | High | FR-029–033, 046 |
| 3 — Output polish/persistence | Medium | FR-006–007, 044, 048, 065–068, ERR-001/002(text)/004–008 |
| 4 — Research & refinement | Medium-low | FR-019–023, 034, 035–038, 045, 047, 051, 059, 070–072 |
| 5 — Service separation/extras | Low (stretch) | FR-004, 042, 056(URL), ChromaDB (if needed), UI polish |

Phase-independent, always-on: FR-008–010, SEC-001–006, NFR-001–008.

**MVP exit criteria:** upload resume → paste JD → get tailored resume + interview prep → approve resume → export PDF, end-to-end via React/FastAPI/local Ollama.

## 20. Future Enhancements
- Company Researcher (live search + scraping).
- Editor Agent (chat-based document refinement).
- Interview-day cheat sheet as its own artifact.
- JD ingestion via URL.
- ChromaDB-backed retrieval, if needed.
- Multiple resume versions / concurrent applications.
- Richer RenderCV templates.
- Polished React UI (previews, drag-and-drop, inline chat panel).

No Study Planner, timetable, deadline tracking, or time-management features, now or later.

## 21. Success Metrics
Proposed defaults **(A)**, pending review:

| Metric | Target |
|---|---|
| Active user time (MVP flow) | < 15 min hands-on (excl. LLM wait) |
| Fabrication rate | 0% flagged by SEC-002/003 across guardrail test set |
| LLM-as-Judge score | Avg ≥ 4/5 on accuracy, relevance, completeness, clarity |
| Pipeline reliability | ≥ 95% runs complete without unhandled crash |
| Test coverage | ≥ 80% on parsing/extraction/orchestration logic |
| Resume approval efficiency *(post-Editor Agent)* | ≥ 90% approved within 2 edit iterations |

**Evaluation framework** (Python, Pytest, Pydantic, Ollama only):
1. **Agent-level:** Pytest + JSON test datasets per agent; Precision/Recall/F1 where applicable; Pydantic schema pass/fail.
2. **LLM-as-a-Judge:** local Ollama model (specific model deferred to Technical Spec), scored on accuracy/relevance/completeness/clarity via versioned rubric prompts.
3. **Guardrail:** Pytest cases for prompt injection, fabricated experience, fake metrics, invalid inputs, unsafe output — each must block, flag, or safely degrade.
4. **End-to-end:** Pytest run of full MVP workflow (upload → approval → export → interview prep) against fixtures, asserting schema-valid output and graceful degradation.

## 22. Requirement ID Index
- FR-001–012: System-level (§6) · FR-013–018: JD Analyst (§7.1) · FR-019–023: Company Researcher (§7.2) · FR-024–028: Resume Agent (§7.3) · FR-029–034: Interview Coach (§7.4) · FR-035–038: Editor Agent (§7.5) · FR-039–043: Input (§8) · FR-044–048: Output (§9) · FR-049–054: Frontend (§10) · FR-055–062: Backend (§11) · FR-063–066: Workflow (§12) · FR-067–069: Document generation (§13) · FR-070–072: Chat editing (§14)
- NFR-001–008 (§15) · SEC-001–006 (§16) · ERR-001–008 (§17) · US-001–009 (§18)

No duplicate IDs across this document.
