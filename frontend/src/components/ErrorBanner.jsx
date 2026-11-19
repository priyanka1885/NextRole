// FR-054: clear, actionable error states with a retry affordance.
export default function ErrorBanner({ message, onRetry }) {
  if (!message) return null
  return (
    <div className="error-banner" role="alert">
      <span className="error-banner__icon" aria-hidden="true">!</span>
      <span className="error-banner__message">{message}</span>
      {onRetry && (
        <button type="button" className="secondary" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  )
}
