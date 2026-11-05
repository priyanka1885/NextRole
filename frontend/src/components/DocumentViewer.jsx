// FR-050: per-document viewer. Renders whichever generated documents are
// available; each is viewable/copyable (FR-048).

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
    <div className="card">
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
    <div className="card">
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
    <div className="card">
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

export default function DocumentViewer({ documents }) {
  if (!documents) return null
  return (
    <>
      <JDExtractionView jd={documents.jd_extraction} />
      <TailoredResumeView resume={documents.tailored_resume} />
      <InterviewPrepView prep={documents.interview_prep} />
    </>
  )
}
