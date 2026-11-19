import { useEffect, useRef, useState } from 'react'

// FR-050: per-document viewer. Renders whichever generated documents are
// available as tabs within a single card, so related output (JD analysis,
// tailored resume, interview prep) reads as one cohesive workspace instead
// of a stack of separate boxes; each is still viewable/copyable (FR-048).

function Bulleted({ items }) {
  if (!items || items.length === 0) return <p className="field-hint">None extracted.</p>
  return (
    <ul>
      {items.map((item, idx) => (
        <li key={idx}>{item}</li>
      ))}
    </ul>
  )
}

function JDExtractionView({ jd }) {
  if (!jd) return null
  return (
    <div className="doc-section">
      <h3>Job Description Analysis</h3>
      <p className="section-title">Required skills</p>
      <Bulleted items={jd.required_skills} />
      <p className="section-title">Responsibilities</p>
      <Bulleted items={jd.responsibilities} />
      <p className="section-title">Experience requirements</p>
      <Bulleted items={jd.experience_requirements} />
      <p className="section-title">Keywords</p>
      <Bulleted items={jd.keywords} />
      <p className="section-title">Preferred qualifications</p>
      <Bulleted items={jd.preferred_qualifications} />
    </div>
  )
}

function FlaggedItems({ items }) {
  if (!items || items.length === 0) return null
  return (
    // ERR-008: fabrication guardrail flags surfaced at/before the approval gate.
    <div className="flag-banner">
      <strong>Flagged for review (not auto-corrected):</strong>
      <ul>
        {items.map((item, idx) => (
          <li key={idx}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

function TailoredResumeView({ resume }) {
  if (!resume) return null
  return (
    <div className="doc-section">
      <h3>
        Tailored Resume
        <span className={`approval-badge ${resume.approval_status}`}>{resume.approval_status}</span>
      </h3>
      <FlaggedItems items={resume.flagged_items} />
      {Object.entries(resume.sections || {}).map(([section, bullets]) => (
        <div key={section}>
          <p className="section-title">{section}</p>
          <Bulleted items={bullets} />
        </div>
      ))}
    </div>
  )
}

function QAList({ title, items }) {
  if (!items || items.length === 0) return null
  return (
    <div>
      <p className="section-title">{title}</p>
      {items.map((qa, idx) => (
        <div key={idx} className="qa-item">
          <div className="question">{qa.question}</div>
          <div className="answer">{qa.star_answer}</div>
        </div>
      ))}
    </div>
  )
}

function InterviewPrepView({ prep }) {
  if (!prep) return null
  return (
    <div className="doc-section">
      <h3>Interview Preparation</h3>
      <FlaggedItems items={prep.flagged_items} />
      <p className="section-title">Self-introduction</p>
      <p>{prep.self_introduction}</p>
      <QAList title="Technical questions" items={prep.technical_questions} />
      <QAList title="HR / behavioral questions" items={prep.hr_questions} />
      <QAList title="Project questions" items={prep.project_questions} />
    </div>
  )
}

const TAB_DEFS = [
  { key: 'jd', label: 'JD Analysis', has: (docs) => Boolean(docs?.jd_extraction) },
  { key: 'resume', label: 'Tailored Resume', has: (docs) => Boolean(docs?.tailored_resume) },
  { key: 'interview', label: 'Interview Prep', has: (docs) => Boolean(docs?.interview_prep) },
]

export default function DocumentViewer({ documents }) {
  const availableTabs = TAB_DEFS.filter((tab) => tab.has(documents))
  const availableKeys = availableTabs.map((tab) => tab.key).join(',')
  const [activeTab, setActiveTab] = useState(null)
  const prevKeysRef = useRef('')

  // Auto-select the newest available document as each pipeline stage
  // completes (matching the original behavior of showing every finished
  // document as it arrived), but leave the user's manual tab choice alone
  // when nothing new has shown up since the last poll.
  useEffect(() => {
    if (availableTabs.length === 0) {
      setActiveTab(null)
      prevKeysRef.current = ''
      return
    }
    const prevCount = prevKeysRef.current ? prevKeysRef.current.split(',').length : 0
    const grew = availableKeys !== prevKeysRef.current && availableTabs.length > prevCount
    const newestKey = availableTabs[availableTabs.length - 1].key

    setActiveTab((current) => {
      if (!current || grew || !availableTabs.some((tab) => tab.key === current)) {
        return newestKey
      }
      return current
    })
    prevKeysRef.current = availableKeys
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availableKeys])

  if (!documents || availableTabs.length === 0) return null

  return (
    <section className="card document-viewer">
      <div className="doc-tabs" role="tablist" aria-label="Generated documents">
        {availableTabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.key}
            className={`doc-tab ${activeTab === tab.key ? 'is-active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="doc-tab-panel" role="tabpanel">
        {activeTab === 'jd' && <JDExtractionView jd={documents.jd_extraction} />}
        {activeTab === 'resume' && <TailoredResumeView resume={documents.tailored_resume} />}
        {activeTab === 'interview' && <InterviewPrepView prep={documents.interview_prep} />}
      </div>
    </section>
  )
}
