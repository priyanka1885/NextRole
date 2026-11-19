// Persistent branded header shown on every screen. Purely presentational —
// it owns no session/pipeline state of its own; App.jsx tells it which step
// is active and gives it the same "start over" handler already used
// elsewhere, so no application behavior changes, only where the control
// lives visually.
export default function AppHeader({ step, onStartOver }) {
  return (
    <header className="app-header">
      <div className="app-header__brand">
        <span className="brand-mark" aria-hidden="true">N</span>
        <div className="brand-copy">
          <span className="brand-name">NextRole</span>
          <span className="brand-tagline">AI resume tailoring &amp; interview prep</span>
        </div>
      </div>

      <ol className="app-header__steps" aria-label="Progress">
        <li className={`step-chip ${step === 1 ? 'is-active' : 'is-done'}`}>
          <span className="step-chip__num">{step === 1 ? '1' : '✓'}</span>
          <span className="step-chip__label">Upload</span>
        </li>
        <li className="step-divider" aria-hidden="true" />
        <li className={`step-chip ${step === 2 ? 'is-active' : ''}`}>
          <span className="step-chip__num">2</span>
          <span className="step-chip__label">Review &amp; approve</span>
        </li>
      </ol>

      {step === 2 && onStartOver ? (
        <button type="button" className="ghost-link" onClick={onStartOver}>
          Start over
        </button>
      ) : (
        <span className="app-header__spacer" aria-hidden="true" />
      )}
    </header>
  )
}
