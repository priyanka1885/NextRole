import { useState } from 'react'
import UploadPage from './pages/UploadPage.jsx'
import ReviewPage from './pages/ReviewPage.jsx'

// No heavy global state library / router at MVP scope (spec.md Section 2
// Assumption); a single piece of state ("which session is active") is
// enough to switch between the Upload and Review/Approval pages.
export default function App() {
  const [sessionId, setSessionId] = useState(null)

  if (!sessionId) {
    return <UploadPage onSessionReady={setSessionId} />
  }

  return <ReviewPage sessionId={sessionId} onStartOver={() => setSessionId(null)} />
}
