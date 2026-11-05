import { useState } from 'react'
import { submitJD, triggerRun, uploadResume } from '../api/client.js'
import ErrorBanner from '../components/ErrorBanner.jsx'

// FR-049: upload form (resume + JD text; URL field reserved).
export default function UploadPage({ onSessionReady }) {
  const [file, setFile] = useState(null)
  const [jdText, setJdText] = useState('')
  const [jdUrl, setJdUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(event) {
    event.preventDefault()
    setError(null)

    if (!file) {
      setError('Please choose a resume file (PDF or DOCX).')
      return
    }
    if (jdText.trim().length < 50) {
      setError('Job description text must be at least 50 characters.')
      return
    }

    setSubmitting(true)
    try {
      const uploadResult = await uploadResume(file)
      const sessionId = uploadResult.session_id
      await submitJD(sessionId, jdText)
      await triggerRun(sessionId)
      onSessionReady(sessionId)
    } catch (err) {
      setError(err.message || 'Something went wrong while starting your session.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="card">
      <h1>NextRole</h1>
      <p>Upload your resume and paste a job description to generate a tailored resume and interview prep.</p>
      <ErrorBanner message={error} />
      <form onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="resume-file">Resume (PDF or DOCX)</label>
          <input
            id="resume-file"
            type="file"
            accept=".pdf,.docx"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
          />
        </div>

        <div className="field">
          <label htmlFor="jd-text">Job description</label>
          <textarea
            id="jd-text"
            value={jdText}
            onChange={(event) => setJdText(event.target.value)}
            placeholder="Paste the job description here (50-20,000 characters)..."
          />
          <p className="field-hint">{jdText.trim().length} characters</p>
        </div>

        <div className="field">
          <label htmlFor="jd-url">Job description URL (reserved for a future update)</label>
          <input
            id="jd-url"
            type="text"
            value={jdUrl}
            onChange={(event) => setJdUrl(event.target.value)}
            placeholder="Not yet supported - paste the job description text above instead"
            disabled
          />
        </div>

        <button type="submit" className="primary" disabled={submitting}>
          {submitting ? 'Starting...' : 'Generate tailored resume & interview prep'}
        </button>
      </form>
    </div>
  )
}
