# NextRole — Project Scope Document

## 1. Project Overview and Problem Statement

Job seekers typically spend hours manually tailoring resumes to each job description, researching companies, and preparing for interviews — often repeating this process from scratch for every application. The work is fragmented across tools (resume editors, search engines, note-taking apps, Q&A prep lists) and is difficult to do consistently well under time pressure.

NextRole is an AI-powered, multi-agent system that automates and coordinates this preparation workflow. Given a candidate's resume and a target job description, it produces a tailored resume, company research, and interview preparation materials — using a set of specialized agents coordinated through LangGraph, running on local open-source LLMs via Ollama.

## 2. Project Objectives

- Reduce the time a job seeker spends preparing for a single application from hours to minutes.
- Produce a tailored resume that reflects the job description's language and priorities without fabricating experience.
- Give the candidate a clear, structured understanding of the target company and role.
- Generate realistic interview questions and well-structured (STAR-format) answers based on the candidate's actual background.
- Allow the candidate to refine any generated document conversationally instead of starting over.
- Build the system using a local, free/open-source LLM stack so it has no recurring per-use API cost.

## 3. Target Users

- **Primary user:** An individual job seeker (e.g., software engineer or similar technical/professional role) preparing applications and interviews, running the tool locally on their own machine.
- **Secondary / implied user:** The developer of NextRole themselves, as the first real user and tester of the system (dogfooding).

NextRole is scoped as a single-user, locally-run tool. It is not designed, in this phase, for multi-tenant, hosted, or team use.

## 4. Core Features and Capabilities

1. **Resume tailoring** — Rewrite/adjust an existing resume to align with a specific job description, without inventing skills or experience.
2. **Company and role research** — Summarize company background, products, business model, and recent news relevant to the role.
3. **Interview preparation** — Generate technical, HR/behavioral, and project-based questions, with STAR-format answers grounded in the candidate's resume.
4. **Chat-based editing** — Let the user request changes to any generated document through conversational follow-up instructions.
5. **Multi-agent orchestration** — Coordinate the above capabilities through specialized agents sharing state via LangGraph, rather than one monolithic prompt.

## 5. Functional Scope

The system shall:

- Accept a resume file (PDF or DOCX) as input.
- Accept a job description as pasted text or a URL to fetch and parse.
- Extract structured job requirements (skills, responsibilities, keywords) from the job description via the JD Analyst agent.
- Research the hiring company via the Company Researcher agent, using web search and page content extraction.
- Tailor the resume content via the Resume Agent, constrained to information already present in the source resume.
- Generate interview questions and STAR answers via the Interview Coach agent.
- Allow the user to request edits to any generated document via chat, applied by the Editor Agent.
- Render a tailored resume as a PDF output (via RenderCV or equivalent).
- Persist session/application data (inputs, generated documents, chat edits) locally (SQLite).
- Expose the system through a FastAPI backend, consumed by a React front end, for interaction.

## 6. Non-Functional Scope

- **Cost:** No paid LLM API shall be a core/required dependency. The system must run fully on local, open-source models via Ollama.
- **Privacy:** Resume and personal data stay local by default; no required third-party upload of personal data.
- **Portability:** The system should run on a single developer machine (Windows, as used for development) without cloud infrastructure.
- **Reliability (MVP-level):** Agents should fail gracefully (e.g., a research or search failure should not crash the whole pipeline) and surface a usable partial result where possible.
- **Maintainability:** Agent responsibilities are modular and independently testable, reflecting the multi-agent boundaries described above.
- **Performance:** No hard real-time requirement; local-LLM generation times (seconds to low minutes per document) are acceptable for this use case.
- **Testability:** Core logic (parsing, extraction, orchestration) should be unit-testable with Pytest, independent of actual LLM calls where feasible.

## 7. In-Scope Features

- Resume parsing from PDF and DOCX.
- Job description ingestion from pasted text or a single URL.
- JD keyword/requirement extraction.
- Company research using web search (DuckDuckGo or similar) and page scraping (BeautifulSoup).
- Resume tailoring grounded strictly in the source resume's existing content.
- Interview question generation (technical, HR, project-based) with STAR-format answers.
- Chat-based, iterative editing of generated documents.
- Local persistence of inputs and generated outputs (SQLite).
- Single-user React front end backed by a FastAPI API.
- Export of the tailored resume as a PDF.

## 8. Out-of-Scope Features

The following are explicitly **not** part of this project's scope (now or as planned future phases beyond what is listed in Section 11):

- Paid/commercial LLM API integration as a required dependency (e.g., OpenAI, Anthropic) — may be an optional, user-supplied alternative at most, never a core dependency.
- Multi-user accounts, authentication, or hosted/multi-tenant deployment.
- Automatic submission of applications to job boards or company portals.
- Scraping or integrating with job board aggregators (e.g., LinkedIn, Indeed) to source job descriptions in bulk.
- Mobile application or native desktop application.
- Real-time mock interview (voice/video) simulation.
- Salary negotiation guidance or offer-comparison tooling.
- Team/recruiter-facing features (e.g., applicant tracking, candidate comparison).
- Analytics dashboards or tracking of application outcomes over time.
- Internationalization/localization of generated documents into multiple languages.

## 9. Main User Workflows

**Workflow A — New application preparation**
1. User uploads their current resume (PDF/DOCX).
2. User pastes a job description or provides its URL.
3. System runs JD Analyst and Company Researcher agents.
4. System runs Resume Agent to produce a tailored resume.
5. System runs Interview Coach to produce interview prep materials.
6. User reviews all generated documents.

**Workflow B — Conversational refinement**
1. User reviews a generated document (e.g., tailored resume or interview prep sheet).
2. User requests a change via chat (e.g., "shorten this bullet", "add more questions about system design").
3. Editor Agent applies the change and returns the updated document.
4. User repeats until satisfied.

**Workflow C — Export and use**
1. User downloads the tailored resume as a PDF.
2. User reviews the interview-day cheat sheet ahead of the interview.

## 10. Expected Deliverables

- Tailored resume, exported as a PDF.
- Company research report (document).
- Interview preparation document (questions + STAR answers).
- Interview-day cheat sheet (condensed summary).
- A working local application (FastAPI backend + React front end) that produces the above from user-supplied inputs.

## 11. MVP Scope vs Future Enhancements

**MVP (first working version):**
- Resume upload (PDF/DOCX) and parsing.
- Job description input via pasted text (URL fetching may be deferred if parsing proves unreliable; see Assumptions).
- JD Analyst agent (requirement/keyword extraction).
- Resume Agent (tailoring, no fabrication).
- Interview Coach agent (question + STAR answer generation).
- Single end-to-end LangGraph pipeline coordinating the above agents.
- FastAPI backend exposing the pipeline, with a minimal React UI sufficient to input data and view/download outputs.
- Local persistence of a single user's sessions (SQLite).
- Tailored resume PDF export.

**Future enhancements (post-MVP):**
- Company Researcher agent with live web search and scraping.
- Chat-based Editor Agent for conversational refinement of any document.
- Interview-day cheat sheet generation as a distinct condensed artifact.
- Job description ingestion directly from a URL.
- ChromaDB-backed retrieval if resume/JD matching quality needs semantic search beyond keyword extraction.
- Support for multiple resume versions or multiple concurrent applications tracked side by side.
- Richer resume templates/formatting options via RenderCV.
- Polished, richer React UI (e.g., document previews, drag-and-drop uploads, inline chat editing panel).

## 12. Development Phases and Priorities

**Phase 1 — Core pipeline (MVP backbone)**
Priority: Highest.
Resume parsing, JD input (text), JD Analyst, Resume Agent, basic LangGraph orchestration, a FastAPI backend exposing it, and a minimal React UI to run the pipeline end-to-end and view output.

**Phase 2 — Interview preparation**
Priority: High.
Interview Coach agent, integrated into the same pipeline, API, and UI.

**Phase 3 — Output polish and persistence**
Priority: Medium.
PDF export via RenderCV, SQLite persistence of sessions/outputs, basic error handling/fallback across agents.

**Phase 4 — Research and refinement**
Priority: Medium-low.
Company Researcher agent (search + scraping), chat-based Editor Agent for document refinement.

**Phase 5 — Service separation and extras**
Priority: Low (stretch).
URL-based JD ingestion, ChromaDB integration if needed, interview-day cheat sheet as a dedicated artifact, React UI polish.

## 13. Assumptions, Constraints, and Dependencies

**Assumptions:**
- The user runs the system on their own machine with Ollama installed and at least one suitable open-source model pulled locally.
- "Job Description via URL" may initially be unreliable across arbitrary sites; pasted-text input is assumed as the dependable baseline, with URL fetching treated as a best-effort enhancement.
- The resume is assumed to be in English and in a reasonably standard PDF/DOCX layout that PyMuPDF/python-docx can parse; heavily graphical or non-standard resume designs are not guaranteed to parse well.
- "Without fabricating information" is interpreted as: the Resume Agent may rephrase, reorder, and emphasize existing resume content to match the JD, but must not introduce skills, employers, titles, or achievements not present in the source resume.
- A single local SQLite database is sufficient for this single-user tool; no concurrent multi-user access is assumed.
- DuckDuckGo (or an equivalent free search provider) is assumed to be available and sufficient for company research; no paid search API is assumed.
- The React front end runs as a separate local web app (dev server or static build) talking to the FastAPI backend over HTTP, rather than a single combined Python process.

**Constraints:**
- No paid LLM API may be a required/core dependency — only free, open-source, locally-run models via Ollama.
- The system is built and run by a single individual developer; scope and timelines must stay realistic for solo development.
- Local LLM performance (speed, quality) depends on the user's hardware and chosen Ollama model; output quality may vary accordingly.
- Choosing React over a Python-only UI (e.g., Streamlit) means the FastAPI backend must be built from Phase 1 onward, rather than deferred, and the developer must maintain both a Python backend and a JavaScript/TypeScript front end.

**Dependencies:**
- Python, LangGraph, Ollama, FastAPI, React, PyMuPDF, python-docx, RenderCV, SQLite, BeautifulSoup, a free search provider (e.g., DuckDuckGo), Pydantic, Pytest, and optionally ChromaDB — as listed in the project's planned technology stack.
- Availability and continued free access of the chosen web search provider for the Company Researcher agent (Phase 4+).
