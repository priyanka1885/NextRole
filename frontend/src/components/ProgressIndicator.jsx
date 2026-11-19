// FR-052: loading/progress indicator for the long-running pipeline run,
// shown per LangGraph node (FR-058 status polling). Rendered as a
// connected stepper so the user can see, at a glance, where the run is in
// the pipeline instead of scanning a plain list.
const NODE_LABELS = {
  parse_resume: 'Parse resume',
  jd_analyst: 'Analyze job description',
  resume_agent: 'Tailor resume',
  approval_gate: 'Await approval',
  interview_coach: 'Generate interview prep',
}

const STATUS_ICON = {
  PENDING: '○',
  RUNNING: '◐',
  SUCCESS: '✓',
  FAILED: '✕',
}

export default function ProgressIndicator({ nodeStatus }) {
  const entries = Object.entries(nodeStatus || {})
  if (entries.length === 0) {
    return <p className="field-hint">Waiting for the pipeline to start...</p>
  }

  return (
    <ol className="pipeline-stepper" aria-label="Pipeline progress">
      {entries.map(([name, info]) => (
        <li key={name} className={`pipeline-step pipeline-step--${info.status}`}>
          <span className="pipeline-step__node" aria-hidden="true">
            {STATUS_ICON[info.status] || '○'}
          </span>
          <span className="pipeline-step__label">
            {NODE_LABELS[name] || name}
            {info.status === 'FAILED' && info.error_message && (
              <span className="field-hint pipeline-step__error"> - {info.error_message}</span>
            )}
          </span>
        </li>
      ))}
    </ol>
  )
}
