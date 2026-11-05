// API client (spec.md Section 2: "API client module centralizes calls to
// the FastAPI endpoints"). Every function maps 1:1 to a spec.md Section 7
// endpoint.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

async function handleResponse(response) {
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`
    try {
      const body = await response.json()
      detail = body.detail || detail
    } catch {
      // response body wasn't JSON; keep the generic message
    }
    const error = new Error(detail)
    error.status = response.status
    throw error
  }
  return response
}

// FR-055: upload + parse resume
export async function uploadResume(file) {
  const formData = new FormData()
  formData.append('file', file)
  const response = await fetch(`${API_BASE_URL}/resumes`, {
    method: 'POST',
    body: formData,
  })
  await handleResponse(response)
  return response.json()
}

// FR-056 (text): submit JD text
export async function submitJD(sessionId, jdText) {
  const response = await fetch(`${API_BASE_URL}/sessions/${sessionId}/jd`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jd_text: jdText }),
  })
  await handleResponse(response)
  return response.json()
}

// FR-057: trigger pipeline run
export async function triggerRun(sessionId) {
  const response = await fetch(`${API_BASE_URL}/sessions/${sessionId}/run`, {
    method: 'POST',
  })
  await handleResponse(response)
  return response.json()
}

// FR-058: poll run/per-node status
export async function getStatus(sessionId) {
  const response = await fetch(`${API_BASE_URL}/sessions/${sessionId}/status`)
  await handleResponse(response)
  return response.json()
}

// FR-058: fetch generated documents
export async function getDocuments(sessionId) {
  const response = await fetch(`${API_BASE_URL}/sessions/${sessionId}/documents`)
  await handleResponse(response)
  return response.json()
}

// FR-060: approve tailored resume
export async function approveResume(sessionId) {
  const response = await fetch(`${API_BASE_URL}/sessions/${sessionId}/resume/approve`, {
    method: 'POST',
  })
  await handleResponse(response)
  return response.json()
}

// FR-060 / ERR-007: request changes on tailored resume
export async function rejectResume(sessionId) {
  const response = await fetch(`${API_BASE_URL}/sessions/${sessionId}/resume/reject`, {
    method: 'POST',
  })
  await handleResponse(response)
  return response.json()
}

// FR-007/FR-044: download approved resume PDF
export function exportResumeUrl(sessionId) {
  return `${API_BASE_URL}/sessions/${sessionId}/resume/export`
}

export async function fetchExportBlob(sessionId) {
  const response = await fetch(exportResumeUrl(sessionId))
  await handleResponse(response)
  return response.blob()
}
