// FR-052: loading/progress indicator for the long-running pipeline run,
// shown per LangGraph node (FR-058 status polling).
const NODE_LABELS = {
  parse_resume: 'Parse resume',
  jd_analyst: 'Analyze job description',
  resume_agent: 'Tailor resume',
  approval_gate: 'Await approval',
  interview_coach: 'Generate interview prep',
}

export default function ProgressIndicator({ nodeStatus }) {
  const entries = Object.entries(nodeStatus || {})
  if (entries.length === 0) {
    return <p className="field-hint">Waiting for the pipeline to start...</p>
  }

  return (
    <ul className="status-list">
      {entries.map(([name, info]) => (
        <li key={name}>
          <span className={`status-pill ${info.status}`}>{info.status}</span>
          <span>{NODE_LABELS[name] || name}</span>
          {info.status === 'FAILED' && info.error_message && (
            <span className="field-hint">- {info.error_message}</span>
          )}
        </li>
      ))}
    </ul>
  )
}
