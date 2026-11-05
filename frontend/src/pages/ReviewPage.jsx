import { useCallback, useEffect, useRef, useState } from 'react'
import {
  approveResume,
  exportResumeUrl,
  fetchExportBlob,
  getDocuments,
  getStatus,
  rejectResume,
} from '../api/client.js'
import ApprovalControls from '../components/ApprovalControls.jsx'
import DocumentViewer from '../components/DocumentViewer.jsx'
import ErrorBanner from '../components/ErrorBanner.jsx'
import ProgressIndicator from '../components/ProgressIndicator.jsx'

const POLL_INTERVAL_MS = 2000

// FR-050/052/053: review/approval page. Polls run status (FR-058) until the
// pipeline halts or pauses at the approval gate, then shows the generated
// documents and approval/export controls.
export default function ReviewPage({ sessionId, onStartOver }) {
  const [status, setStatus] = useState(null)
  const [documents, setDocuments] = useState(null)
  const [error, setError] = useState(null)
  const [actionBusy, setActionBusy] = useState(false)
  const pollTimer = useRef(null)

  const refresh = useCallback(async () => {
    try {
      const [statusBody, documentsBody] = await Promise.all([
        getStatus(sessionId),
        getDocuments(sessionId),
      ])
      setStatus(statusBody)
      setDocuments(documentsBody)
      setError(null)
      return statusBody
    } catch (err) {
      setError(err.message || 'Could not reach the server.')
      return null
    }
  }, [sessionId])

  useEffect(() => {
    let cancelled = false

    async function poll() {
      const statusBody = await refresh()
      if (cancelled) return

      const stillRunning =
        statusBody &&
        !statusBody.halted &&
        statusBody.approval_status !== 'APPROVED' &&
        !(documents && documents.interview_prep)

      if (stillRunning) {
        pollTimer.current = setTimeout(poll, POLL_INTERVAL_MS)
      }
    }

    poll()
    return () => {
      cancelled = true
      if (pollTimer.current) clearTimeout(pollTimer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  async function handleApprove() {
    setActionBusy(true)
    setError(null)
    try {
      await approveResume(sessionId)
      await refresh()
    } catch (err) {
      setError(err.message || 'Could not approve the resume.')
    } finally {
      setActionBusy(false)
    }
  }

  async function handleReject() {
    setActionBusy(true)
    setError(null)
    try {
      await rejectResume(sessionId)
      await refresh()
    } catch (err) {
      setError(err.message || 'Could not request changes.')
    } finally {
      setActionBusy(false)
    }
  }

  async function handleExport() {
    setActionBusy(true)
    setError(null)
    try {
      const blob = await fetchExportBlob(sessionId)
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'tailored_resume.pdf'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
    } catch (err) {
      setError(err.message || 'Could not export the resume PDF.')
    } finally {
      setActionBusy(false)
    }
  }

  const hasFlags = Boolean(documents?.tailored_resume?.flagged_items?.length)

  return (
    <div>
      <div className="card">
        <h2>Pipeline status</h2>
        <ErrorBanner message={error} onRetry={refresh} />
        <ProgressIndicator nodeStatus={status?.node_status} />
        {status?.halted && (
          <ErrorBanner message={`The pipeline stopped early: ${status.halt_reason}`} onRetry={refresh} />
        )}
        <button type="button" className="secondary" onClick={onStartOver}>
          Start over
        </button>
      </div>

      <DocumentViewer documents={documents} />

      <ApprovalControls
        approvalStatus={documents?.tailored_resume?.approval_status}
        hasFlags={hasFlags}
        busy={actionBusy}
        onApprove={handleApprove}
        onReject={handleReject}
        onExport={handleExport}
      />

      {documents?.tailored_resume?.approval_status === 'APPROVED' && (
        <p className="field-hint">
          Direct download link: <a href={exportResumeUrl(sessionId)}>{exportResumeUrl(sessionId)}</a>
        </p>
      )}
    </div>
  )
}
