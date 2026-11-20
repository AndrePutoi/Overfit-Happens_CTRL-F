// Cliente da API CTRL+F. Em desenvolvimento e no Docker, /api é encaminhado para a API.
const BASE = import.meta.env.VITE_API_URL || '/api'
export const DEFAULT_TOKEN = import.meta.env.VITE_TECNICO_TOKEN || 'demo-ana'

let token = DEFAULT_TOKEN
export function setToken(t) {
  token = t
}

function authHeaders() {
  return token ? { 'X-Tecnico-Token': token } : {}
}

async function errorMessage(res) {
  let msg = `${res.status} ${res.statusText}`
  try {
    const j = await res.json()
    if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
  } catch {
    /* resposta sem JSON */
  }
  return msg
}

async function request(method, path, body, isForm = false) {
  const headers = authHeaders()
  let payload
  if (isForm) payload = body
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const res = await fetch(BASE + path, { method, headers, body: payload })
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.json()
}

// Ficheiros (exportações, fotos): pedidos com o token do técnico, que um link <a href> não envia
async function requestBlob(path) {
  const res = await fetch(BASE + path, { headers: authHeaders() })
  if (!res.ok) throw new Error(await errorMessage(res))
  const cd = res.headers.get('Content-Disposition') || ''
  const m = cd.match(/filename="?([^";]+)"?/)
  return { blob: await res.blob(), filename: m ? m[1] : path.split('/').pop().split('?')[0] }
}

export async function download(path) {
  const { blob, filename } = await requestBlob(path)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

const enc = encodeURIComponent
const qs = (params = {}) => {
  const s = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')).toString()
  return s ? `?${s}` : ''
}

export const api = {
  elements: () => request('GET', '/elements'),
  element: (id) => request('GET', `/elements/${enc(id)}`),
  taxonomy: () => request('GET', '/taxonomy'),
  config: () => request('GET', '/config'),
  stats: () => request('GET', '/stats'),
  me: () => request('GET', '/me'),
  jobs: () => request('GET', '/jobs'),
  imports: () => request('GET', '/imports'),

  patch: (id, body) => request('PATCH', `/elements/${enc(id)}`, body),
  validate: (id) => request('POST', `/elements/${enc(id)}/validate`),
  reject: (id) => request('POST', `/elements/${enc(id)}/reject`),
  restore: (id) => request('POST', `/elements/${enc(id)}/restore`),
  setBest: (id, detectionId) => request('PUT', `/elements/${enc(id)}/best-detection`, { detection_id: detectionId }),
  merge: (id, into) => request('POST', `/elements/${enc(id)}/merge`, { into }),
  split: (id, detectionIds) => request('POST', `/elements/${enc(id)}/split`, { detection_ids: detectionIds }),

  uploadVideo: (video, gpx, name) => {
    const fd = new FormData()
    fd.append('video', video)
    if (gpx) fd.append('gpx', gpx)
    if (name) fd.append('name', name)
    return request('POST', '/jobs/video', fd, true)
  },
  sourceJob: (source, name) => request('POST', '/jobs/source', { source, name }),

  history: (params) => request('GET', `/history${qs(params)}`),

  // reclamações dos cidadãos
  complaints: (params) => request('GET', `/complaints${qs(params)}`),
  createComplaint: (fields, photo) => {
    const fd = new FormData()
    Object.entries(fields).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') fd.append(k, v) })
    if (photo) fd.append('photo', photo)
    return request('POST', '/complaints', fd, true)
  },
  patchComplaint: (id, body) => request('PATCH', `/complaints/${id}`, body),
  complaintPhotoUrl: async (id) => URL.createObjectURL((await requestBlob(`/complaints/${id}/photo`)).blob),
}

export const exportPath = (fmt, params = {}) => `/export.${fmt}${qs(params)}`
export const decisionsPath = () => '/decisions'
export const complaintsExportPath = () => '/complaints/export.csv'
export const historyExportPath = () => '/history/export.csv'
