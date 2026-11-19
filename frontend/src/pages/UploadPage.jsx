import { useState } from 'react'
import { submitJD, triggerRun, uploadResume } from '../api/client.js'
import ErrorBanner from '../components/ErrorBanner.jsx'

const JD_MIN_CHARS = 50

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
    if (jdText.trim().length < JD_MIN_CHARS) {
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

  const jdLength = jdText.trim().length
  const jdProgress = Math.min(100, Math.round((jdLength / JD_MIN_CHARS) * 100))

  return (
    <>
      <section className="card hero-card">
        <h1>NextRole</h1>
        <p className="hero-subtitle">
          Upload your resume and paste a job description to generate a tailored resume and interview prep.
        </p>
        <ul className="hero-highlights">
          <li>Analyze the job description</li>
          <li>Tailor your resume</li>
          <li>Prep for the interview</li>
        </ul>
      </section>

      <section className="card">
        <div className="panel-heading">
          <h2>Start your session</h2>
          <p className="field-hint">Takes about a minute — nothing is sent outside your machine.</p>
        </div>
        <ErrorBanner message={error} />
        <form onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="resume-file">Resume (PDF or DOCX)</label>
            <div className="dropzone">
              <input
                id="resume-file"
                type="file"
                accept=".pdf,.docx"
                className="dropzone__input"
                onChange={(event) => setFile(event.target.files?.[0] || null)}
              />
              <label htmlFor="resume-file" className="dropzone__label">
                <span className="dropzone__icon" aria-hidden="true">⬆</span>
                <span className="dropzone__text">
                  {file ? file.name : 'Click to choose a file, or drag it here'}
                </span>
                <span className="field-hint">PDF or DOCX</span>
              </label>
            </div>
          </div>

          <div className="field">
            <label htmlFor="jd-text">Job description</label>
            <textarea
              id="jd-text"
              value={jdText}
              onChange={(event) => setJdText(event.target.value)}
              placeholder="Paste the job description here (50-20,000 characters)..."
            />
            <div className="char-meter" aria-hidden="true">
              <div className="char-meter__bar" style={{ width: `${jdProgress}%` }} />
            </div>
            <p className="field-hint">{jdLength} characters</p>
          </div>

          <div className="field">
            <label htmlFor="jd-url">
              Job description URL (reserved for a future update)
              <span className="badge-soon">Soon</span>
            </label>
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
      </section>
    </>
  )
}
