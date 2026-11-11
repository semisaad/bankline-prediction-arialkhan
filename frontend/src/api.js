export const API_BASE = import.meta.env.VITE_API_BASE || ''
const BASE = API_BASE

async function get(path) {
  const response = await fetch(`${BASE}${path}`, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (body.error) detail = body.error
    } catch {
      detail = response.statusText || detail
    }
    throw new Error(detail)
  }
  return response.json()
}

export const api = {
  health: () => get('/api/health/'),
  summary: () => get('/api/forecast/summary/'),
  maps: (year) => get(`/api/forecast/maps/?year=${year}`),
  metrics: () => get('/api/forecast/metrics/'),
  riskZones: (year) => get(`/api/forecast/risk-zones/?year=${year}`),
  quality: () => get('/api/forecast/data-quality/'),
  zones: () => get('/api/zones/'),
}
