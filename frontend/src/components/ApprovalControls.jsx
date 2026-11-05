// FR-053: Approve / Request-changes actions on the resume; export gated on
// approval (FR-008, ERR-007).
export default function ApprovalControls({
  approvalStatus,
  hasFlags,
  busy,
  onApprove,
  onReject,
  onExport,
}) {
  if (!approvalStatus) return null

  const canExport = approvalStatus === 'APPROVED' && !hasFlags

  return (
    <div className="card">
      <h3>Resume Approval</h3>
      <p className="field-hint">
        No document other than the tailored resume requires approval (FR-008). Export is only
        enabled once the resume is approved{hasFlags ? ' and all flagged items are resolved' : ''}.
      </p>
      <button type="button" className="primary" disabled={busy} onClick={onApprove}>
        Approve
      </button>
      <button type="button" className="danger" disabled={busy} onClick={onReject}>
        Request changes
      </button>
      <button type="button" className="secondary" disabled={!canExport || busy} onClick={onExport}>
        Export PDF
      </button>
    </div>
  )
}
