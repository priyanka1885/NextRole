"""
LangGraph multi-agent pipeline (spec.md Section 3, FR-063-066).

Graph shape (mirrors the stateDiagram in spec.md Section 3):

    ParseResume -> JDAnalyst -> ResumeAgent -> ApprovalGate -> InterviewCoach -> END
                                      ^              |
                                      |   rejected   |
                                      +--------------+

- Each node reads/writes the shared PipelineState (FR-063).
- Conditional edges inspect each node's success/failure flag before
  advancing (FR-064).
- Bounded retries (FR-065, up to 2) happen *inside* each agent-calling node,
  via OllamaClient.generate_structured's own retry loop (spec.md Section 8);
  this is the mechanism the stateDiagram's "JDAttempt -> JDAttempt: retry"
  self-loop represents, kept as a single node invocation rather than a
  separate outer graph loop for simplicity (documented assumption).
- On unrecoverable node failure, the branch halts (routes to END) while
  already-completed outputs from earlier nodes remain in state (FR-066).
- ApprovalGate is implemented as a real interrupt point: the compiled graph
  pauses *before* executing the "approval_gate" node (interrupt_before).
  The approval service resumes the run after writing the user's decision
  into state via `update_state`. Company Researcher and Editor Agent are
  intentionally not present in this graph: both are Future-phase per
  scope.md/requirements.md and out of scope for Phases 1-3.
"""
from __future__ import annotations

from typing import Callable, Optional

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from backend.agents.interview_coach import run_interview_coach
from backend.agents.jd_analyst import run_jd_analyst
from backend.agents.resume_agent import run_resume_agent
from backend.llm.ollama_client import LLMOutputError, OllamaClient
from backend.models.schemas import ApprovalStatusEnum, NodeStatus, NodeStatusEnum
from backend.pipeline.state import PipelineState

NodeName = str


def _status_dict(state: PipelineState) -> dict:
    return dict(state.get("node_status", {}))


def _success(node_status: dict, name: NodeName) -> dict:
    node_status[name] = NodeStatus(status=NodeStatusEnum.SUCCESS)
    return node_status


def _failed(node_status: dict, name: NodeName, error: str) -> dict:
    node_status[name] = NodeStatus(
        status=NodeStatusEnum.FAILED, retry_count=0, error_message=error
    )
    return node_status


def build_graph(llm_client: Optional[OllamaClient] = None):
    """Build and compile the NextRole pipeline graph.

    `llm_client` can be injected (e.g. a fake in tests, per NFR-007) so the
    orchestration logic is testable independent of a live Ollama server.
    """
    client = llm_client or OllamaClient()

    # -- Node implementations -------------------------------------------------

    def parse_resume_node(state: PipelineState) -> dict:
        node_status = _status_dict(state)
        if state.get("resume_data") is not None:
            node_status = _success(node_status, "parse_resume")
            return {"node_status": node_status}
        node_status = _failed(
            node_status, "parse_resume", "No parsed resume data available in session state."
        )
        return {"node_status": node_status, "halted": True, "halt_reason": "parse_resume failed"}

    def jd_analyst_node(state: PipelineState) -> dict:
        node_status = _status_dict(state)
        try:
            extraction = run_jd_analyst(state["jd_text"], client)
            node_status = _success(node_status, "jd_analyst")
            return {"jd_extraction": extraction, "node_status": node_status}
        except LLMOutputError as exc:
            node_status = _failed(node_status, "jd_analyst", str(exc))
            return {"node_status": node_status, "halted": True, "halt_reason": f"jd_analyst: {exc}"}

    def resume_agent_node(state: PipelineState) -> dict:
        node_status = _status_dict(state)
        try:
            tailored = run_resume_agent(state["resume_data"], state["jd_extraction"], client)
            node_status = _success(node_status, "resume_agent")
            return {"tailored_resume": tailored, "node_status": node_status}
        except LLMOutputError as exc:
            node_status = _failed(node_status, "resume_agent", str(exc))
            return {"node_status": node_status, "halted": True, "halt_reason": f"resume_agent: {exc}"}

    def approval_gate_node(state: PipelineState) -> dict:
        node_status = _status_dict(state)
        node_status = _success(node_status, "approval_gate")
        return {"node_status": node_status}

    def interview_coach_node(state: PipelineState) -> dict:
        node_status = _status_dict(state)
        try:
            prep = run_interview_coach(state["resume_data"], state["jd_extraction"], client)
            node_status = _success(node_status, "interview_coach")
            return {"interview_prep": prep, "node_status": node_status}
        except LLMOutputError as exc:
            node_status = _failed(node_status, "interview_coach", str(exc))
            return {"node_status": node_status, "halted": True, "halt_reason": f"interview_coach: {exc}"}

    # -- Routers (FR-064: conditional routing on per-node success/failure) --

    def route_after_parse(state: PipelineState) -> str:
        return "halt" if state.get("halted") else "continue"

    def route_after_jd(state: PipelineState) -> str:
        return "halt" if state.get("halted") else "continue"

    def route_after_resume(state: PipelineState) -> str:
        return "halt" if state.get("halted") else "continue"

    def route_after_approval(state: PipelineState) -> str:
        status = state.get("approval_status")
        if status == ApprovalStatusEnum.APPROVED:
            return "approved"
        if status == ApprovalStatusEnum.CHANGES_REQUESTED:
            return "rejected"
        return "pending"

    # -- Graph assembly -------------------------------------------------------

    graph = StateGraph(PipelineState)
    graph.add_node("parse_resume", parse_resume_node)
    graph.add_node("jd_analyst", jd_analyst_node)
    graph.add_node("resume_agent", resume_agent_node)
    graph.add_node("approval_gate", approval_gate_node)
    graph.add_node("interview_coach", interview_coach_node)

    graph.set_entry_point("parse_resume")
    graph.add_conditional_edges("parse_resume", route_after_parse, {"continue": "jd_analyst", "halt": END})
    graph.add_conditional_edges("jd_analyst", route_after_jd, {"continue": "resume_agent", "halt": END})
    graph.add_conditional_edges("resume_agent", route_after_resume, {"continue": "approval_gate", "halt": END})
    graph.add_conditional_edges(
        "approval_gate",
        route_after_approval,
        {"approved": "interview_coach", "rejected": "resume_agent", "pending": END},
    )
    graph.add_edge("interview_coach", END)

    return graph.compile(checkpointer=InMemorySaver(), interrupt_before=["approval_gate"])


# Process-wide compiled graph. A single InMemorySaver-backed checkpointer is
# fine for a single-user, single-process local tool (NFR-008); each session
# is addressed by its own LangGraph thread_id (the session_id).
_compiled_graph = None


def get_compiled_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


def reset_compiled_graph(llm_client: Optional[OllamaClient] = None) -> None:
    """Testing hook: rebuild the process-wide compiled graph, optionally with
    an injected LLM client (e.g. a fake, per NFR-007). Not used in production
    code paths -- backend/main.py never calls this."""
    global _compiled_graph
    _compiled_graph = build_graph(llm_client)


def thread_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}
