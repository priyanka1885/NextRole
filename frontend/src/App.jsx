import { useState } from 'react'
import AppHeader from './components/AppHeader.jsx'
import UploadPage from './pages/UploadPage.jsx'
import ReviewPage from './pages/ReviewPage.jsx'

// No heavy global state library / router at MVP scope (spec.md Section 2
// Assumption); a single piece of state ("which session is active") is
// enough to switch between the Upload and Review/Approval pages. A shared
// AppHeader renders around both pages for a consistent, branded shell.
export default function App() {
  const [sessionId, setSessionId] = useState(null)
  const step = sessionId ? 2 : 1
  const startOver = () => setSessionId(null)

  return (
    <div className="app-shell">
      <AppHeader step={step} onStartOver={sessionId ? startOver : null} />
      <main className="app-main">
        {!sessionId ? (
          <UploadPage onSessionReady={setSessionId} />
        ) : (
          <ReviewPage sessionId={sessionId} />
        )}
      </main>
    </div>
  )
}
