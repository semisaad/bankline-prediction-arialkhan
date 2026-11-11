import { useEffect, useRef } from 'react'
import { COPY } from '../i18n.js'

export default function LayersPanel({
  open,
  onClose,
  visible,
  onToggle,
  zones,
  riskData,
  advanced,
  onAdvanced,
  modelYear,
  modelYears,
  onModelYear,
}) {
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const handler = (event) => {
      if (event.key === 'Escape') onClose()
    }
    const outside = (event) => {
      if (ref.current && !ref.current.contains(event.target) && !event.target.closest('[data-layers-trigger]')) {
        onClose()
      }
    }
    window.addEventListener('keydown', handler)
    document.addEventListener('pointerdown', outside)
    return () => {
      window.removeEventListener('keydown', handler)
      document.removeEventListener('pointerdown', outside)
    }
  }, [open, onClose])
  if (!open) return null
  const count = (tier) => zones.counts[tier]
  return (
    <div className="layers-panel" ref={ref} role="dialog" aria-label={COPY.layers} data-testid="layers-panel">
      <div className="layers-head">
        <h2>{COPY.layers}</h2>
        <button type="button" className="icon-button" onClick={onClose} aria-label={COPY.close}>×</button>
      </div>
      <label className="layer-row">
        <input type="checkbox" checked={visible.risk} onChange={() => onToggle('risk')} data-testid="toggle-risk" />
        <span>
          {COPY.riskZones}
          <small>
            {riskData
              ? `${riskData.segment_counts.erosion} outward / ${riskData.segment_counts.accretion} inward`
              : COPY.riskLoading}
          </small>
        </span>
      </label>
      <label className="layer-row">
        <input type="checkbox" checked={visible.zones} onChange={() => onToggle('zones')} data-testid="toggle-zones" />
        <span>
          {COPY.zoneLayer}
          <small>{count('strong')} / {count('moderate')} / {count('land_gained')} / {count('no_clear')}</small>
        </span>
      </label>
      <label className="layer-row">
        <input type="checkbox" checked={visible.edge2023} onChange={() => onToggle('edge2023')} data-testid="toggle-edge2023" />
        <span>{COPY.edgeStart(zones.starting_year)}</span>
      </label>
      <label className="layer-row">
        <input type="checkbox" checked={visible.observed} onChange={() => onToggle('observed')} data-testid="toggle-observed" />
        <span>{COPY.observedEdge}</span>
      </label>
      <div className="advanced-block">
        <button type="button" className="advanced-toggle" onClick={onAdvanced} aria-expanded={advanced}>
          <span>{COPY.advanced}</span>
          <span aria-hidden="true">{advanced ? '−' : '+'}</span>
        </button>
        {advanced ? (
          <div className="advanced-body">
            <label className="layer-row">
              <input type="checkbox" checked={visible.model} onChange={() => onToggle('model')} data-testid="toggle-model" />
              <span>{COPY.modelLayer}</span>
            </label>
            <p>{COPY.modelNote}</p>
            <div className="year-inline" role="group" aria-label="Model year">
              {modelYears.map((year) => (
                <button
                  key={year}
                  type="button"
                  className={year === modelYear ? 'year-pill active' : 'year-pill'}
                  onClick={() => onModelYear(year)}
                >
                  {year}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
