export function m(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return `${Number(value).toFixed(digits)} m`
}

export function num(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return Number(value).toFixed(digits)
}

export function pct(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return `${(Number(value) * 100).toFixed(digits)}%`
}

export function area(m2) {
  if (m2 === null || m2 === undefined) return '—'
  return `${(Number(m2) / 1_000_000).toFixed(2)} km²`
}

export function count(value, total) {
  if (value === null || value === undefined || total === null || total === undefined) return '—'
  return `${value} / ${total}`
}

export function titleCase(value) {
  if (!value) return '—'
  return String(value).replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function shortHash(value, n = 12) {
  if (!value) return '—'
  return value.length > n ? `${value.slice(0, n)}…` : value
}

export function utc(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.toISOString().slice(0, 16).replace('T', ' ')} UTC`
}
