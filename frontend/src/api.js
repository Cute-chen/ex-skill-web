const BASE = ''  // same origin in prod; Vite proxy in dev

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { detail = (await res.json()).detail || detail } catch {}
    throw new Error(detail)
  }
  return res.json()
}

export const api = {
  // Settings
  getSettings: () => request('/api/settings'),
  saveSettings: (data) => request('/api/settings', { method: 'POST', body: JSON.stringify(data) }),
  testSettings: (data) => request('/api/settings/test', { method: 'POST', body: JSON.stringify(data) }),

  // Exes
  listExes: () => request('/api/exes'),
  getEx: (slug) => request(`/api/exes/${slug}`),
  deleteEx: (slug) => request(`/api/exes/${slug}`, { method: 'DELETE' }),
  addCorrection: (slug, text) => request(`/api/exes/${slug}/correct`, { method: 'POST', body: JSON.stringify({ text }) }),
  listVersions: (slug) => request(`/api/exes/${slug}/versions`),
  rollback: (slug, version) => request(`/api/exes/${slug}/rollback/${version}`, { method: 'POST' }),

  // Chat
  getHistory: (slug) => request(`/api/exes/${slug}/history`),
  clearHistory: (slug) => request(`/api/exes/${slug}/history`, { method: 'DELETE' }),

  // File upload (multipart)
  async uploadFile(type, file, extra = {}) {
    const fd = new FormData()
    fd.append('file', file)
    Object.entries(extra).forEach(([k, v]) => fd.append(k, v))
    const query = type === 'social' && extra.platform ? `?platform=${extra.platform}` : ''
    const res = await fetch(`${BASE}/api/upload/${type}${query}`, { method: 'POST', body: fd })
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try { detail = (await res.json()).detail || detail } catch {}
      throw new Error(detail)
    }
    return res.json()
  },

  async uploadPhotos(files) {
    const fd = new FormData()
    files.forEach(f => fd.append('files', f))
    const res = await fetch(`${BASE}/api/upload/photo`, { method: 'POST', body: fd })
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try { detail = (await res.json()).detail || detail } catch {}
      throw new Error(detail)
    }
    return res.json()
  },

  // Confirm creation
  confirmCreate: (data) => request('/api/create/confirm', { method: 'POST', body: JSON.stringify(data) }),

  // Background create jobs
  createCreateJob: (data) => request('/api/create/jobs', { method: 'POST', body: JSON.stringify(data) }),
  listCreateJobs: () => request('/api/create/jobs'),
  getCreateJob: (jobId) => request(`/api/create/jobs/${jobId}`),
  cancelCreateJob: (jobId) => request(`/api/create/jobs/${jobId}`, { method: 'DELETE' }),
}

// SSE helper: streams events, calls onEvent(data) for each
export function streamSSE(url, body, onEvent, onError) {
  let aborted = false
  const controller = new AbortController()

  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: controller.signal,
  }).then(async (res) => {
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try { detail = (await res.json()).detail || detail } catch {}
      onError && onError(new Error(detail))
      return
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (!aborted) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            onEvent(data)
          } catch {}
        }
      }
    }
  }).catch(err => {
    if (!aborted) onError && onError(err)
  })

  return () => { aborted = true; controller.abort() }
}
