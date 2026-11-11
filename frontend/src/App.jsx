import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import EvidencePanels from './components/EvidencePanels.jsx'
import LayersPanel from './components/LayersPanel.jsx'
import MapView from './components/MapView.jsx'
import { COPY } from './i18n.js'

const DEFAULT_VISIBLE = {
  risk: true,
  zones: false,
  edge2023: true,
  observed: false,
  model: false,
}

function LoadingScreen() {
  return (
    <div className="loading-screen" data-testid="loading">
      <div>
        <p className="eyebrow">{COPY.kicker}</p>
        <h1>{COPY.title}</h1>
        <p>{COPY.loading}</p>
      </div>
    </div>
  )
}

function ErrorScreen({ message, onRetry }) {
  return (
    <div className="loading-screen" data-testid="error">
      <div className="error-card">
        <p className="eyebrow">Data check</p>
        <h1>{COPY.unavailable}</h1>
        <p>{message}</p>
        <button type="button" className="primary-button" onClick={onRetry}>{COPY.retry}</button>
      </div>
    </div>
  )
}

function RiskPanel({ riskData, riskError, scenarioYear, forecastYears, onYear, onLargest, onPast, zones }) {
  if (riskError) {
    return (
      <div className="risk-panel-body" data-testid="risk-panel">
        <p className="risk-error">{COPY.riskUnavailable}</p>
        <button type="button" className="text-button" onClick={onPast}>{COPY.pastChange}</button>
      </div>
    )
  }
  if (!riskData) {
    return (
      <div className="risk-panel-body" data-testid="risk-panel">
        <p className="risk-loading">{COPY.riskLoading}</p>
      </div>
    )
  }
  const year = riskData.year || scenarioYear
  const counts = riskData.segment_counts || {}
  const hasLargest = Boolean(riskData.largest?.center)
  return (
    <div className="risk-panel-body" data-testid="risk-panel">
      <div className="scenario-head">
        <div>
          <span className="eyebrow">Scenario</span>
          <strong>{riskData.origin_year} → {year}</strong>
        </div>
        <button type="button" className="jump-risk" onClick={onLargest} disabled={!hasLargest}>
          {COPY.largestShift}
        </button>
      </div>

      <div className="scenario-years" role="group" aria-label={COPY.scenarioYear}>
        {forecastYears.map((item) => (
          <button
            key={item}
            type="button"
            className={item === scenarioYear ? 'year-pill active' : 'year-pill'}
            onClick={() => onYear(item)}
            aria-pressed={item === scenarioYear}
            data-testid={`risk-year-${item}`}
          >
            {item}
          </button>
        ))}
      </div>

      <div className="risk-stat-grid" data-testid="risk-counts" aria-label="Predicted bank segments">
        <div className="risk-stat erosion">
          <strong data-testid="risk-count-erosion">{counts.erosion ?? 0}</strong>
          <span>{COPY.potentialErosion}</span>
          <small>outward</small>
        </div>
        <div className="risk-stat accretion">
          <strong data-testid="risk-count-accretion">{counts.accretion ?? 0}</strong>
          <span>{COPY.potentialAccretion}</span>
          <small>inward</small>
        </div>
        <div className="risk-stat quiet">
          <strong data-testid="risk-count-low">{counts.low_movement ?? 0}</strong>
          <span>{COPY.littleChange}</span>
          <small>{COPY.notDrawn}</small>
        </div>
      </div>

      <div className="legend risk-legend">
        <div className="legend-row">
          <i className="risk-swatch risk-erosion" />
          <span>{COPY.potentialErosion} <b>·</b> outward</span>
        </div>
        <div className="legend-row">
          <i className="risk-swatch risk-accretion" />
          <span>{COPY.potentialAccretion} <b>·</b> inward</span>
        </div>
        <div className="legend-divider" />
        <div className="legend-row">
          <i className="edge-swatch edge-start" />
          <span>{riskData.origin_year} edge</span>
        </div>
        <div className="legend-row">
          <i className="edge-swatch edge-predicted" />
          <span>{year} predicted bank</span>
        </div>
      </div>

      <p className="risk-note">{COPY.riskNote}</p>

      <div className="past-snapshot">
        <div>
          <span>{COPY.pastSnapshot} · 1989–2026</span>
          <strong>{COPY.pastSnapshotNote(zones.counts.land_gained, zones.counts.no_clear)}</strong>
        </div>
        <button type="button" className="text-button" onClick={onPast}>{COPY.pastChange} →</button>
      </div>
    </div>
  )
}

function PastLegend({ zones, visible, showObserved, observedYear, view }) {
  return (
    <>
      <div className="legend-head">
        <span>{COPY.measuredPast}</span>
        <strong>{zones.years[0]}–{zones.latest_year}</strong>
      </div>
      <p className="legend-intro">{COPY.measuredPastNote}</p>
      {zones.tier_order.map((tier) => (
        <div className="legend-row" key={tier}>
          <i
            className={`zone-swatch tier-${tier}`}
            style={{ background: zones.tier_colors[tier].fill, borderColor: zones.tier_colors[tier].outline }}
          />
          <span>{zones.tier_labels[tier]}</span>
          <em data-testid={`legend-count-${tier}`}>{zones.counts[tier]}</em>
        </div>
      ))}
      <div className="legend-divider" />
      <div className="legend-row">
        <i className="edge-swatch edge-start" />
        <span>{zones.starting_year} edge</span>
      </div>
      {showObserved ? (
        <div className="legend-row">
          <i className="edge-swatch edge-observed" />
          <span>{observedYear} observed edge</span>
        </div>
      ) : null}
      {visible.model && view !== 'observed' ? (
        <div className="legend-row">
          <i className="edge-swatch edge-model" />
          <span>{COPY.modelLayer}</span>
        </div>
      ) : null}
    </>
  )
}

function ObservedLegend({ zones, observedYear }) {
  return (
    <>
      <div className="legend-head">
        <span>{COPY.observedYears}</span>
        <strong>{zones.starting_year} → {observedYear}</strong>
      </div>
      <p className="legend-intro">{COPY.observedNote}</p>
      <div className="legend-row">
        <i className="edge-swatch edge-start" />
        <span>{zones.starting_year} edge</span>
      </div>
      <div className="legend-row">
        <i className="edge-swatch edge-observed" />
        <span>{observedYear} measured edge</span>
      </div>
    </>
  )
}

export default function App() {
  const [health, setHealth] = useState(null)
  const [summary, setSummary] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [quality, setQuality] = useState(null)
  const [zones, setZones] = useState(null)
  const [riskData, setRiskData] = useState(null)
  const [riskError, setRiskError] = useState(null)
  const [error, setError] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [view, setView] = useState('risk')
  const [observedYear, setObservedYear] = useState(null)
  const [basemap, setBasemap] = useState('satellite')
  const [visible, setVisible] = useState(DEFAULT_VISIBLE)
  const [layersOpen, setLayersOpen] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const [openPanel, setOpenPanel] = useState(null)
  const [scenarioYear, setScenarioYear] = useState(null)
  const [modelData, setModelData] = useState(null)
  const [modelError, setModelError] = useState(null)
  const [map, setMap] = useState(null)

  useEffect(() => {
    let cancelled = false
    setError(null)
    Promise.all([api.health(), api.summary(), api.metrics(), api.quality(), api.zones()])
      .then(([healthData, summaryData, metricsData, qualityData, zonesData]) => {
        if (cancelled) return
        setHealth(healthData)
        setSummary(summaryData)
        setMetrics(metricsData)
        setQuality(qualityData)
        setZones(zonesData)
        setObservedYear(zonesData.observed_years[zonesData.observed_years.length - 1])
        const years = summaryData.forecast_years || []
        if (years.length) setScenarioYear(years[years.length - 1])
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
    return () => { cancelled = true }
  }, [reloadKey])

  useEffect(() => {
    if (!scenarioYear) return
    let cancelled = false
    setRiskData(null)
    setRiskError(null)
    api.riskZones(scenarioYear)
      .then((data) => { if (!cancelled) setRiskData(data) })
      .catch((err) => { if (!cancelled) setRiskError(err.message) })
    return () => { cancelled = true }
  }, [scenarioYear, reloadKey])

  useEffect(() => {
    if (!visible.model || view === 'observed' || !scenarioYear) {
      setModelData(null)
      setModelError(null)
      return
    }
    let cancelled = false
    setModelError(null)
    api.maps(scenarioYear)
      .then((data) => { if (!cancelled) setModelData(data) })
      .catch((err) => { if (!cancelled) setModelError(err.message) })
    return () => { cancelled = true }
  }, [visible.model, scenarioYear, view])

  const toggleLayer = useCallback((key) => {
    setVisible((prev) => ({ ...prev, [key]: !prev[key] }))
  }, [])

  const changeView = useCallback((next) => {
    setView(next)
    setLayersOpen(false)
    setVisible((prev) => ({
      ...prev,
      risk: next === 'risk',
      zones: next === 'past',
      edge2023: next !== 'observed',
      observed: next === 'observed',
      model: false,
    }))
  }, [])

  const onMapReady = useCallback((instance) => setMap(instance), [])

  const jumpTo = useCallback((jump) => {
    if (!map || !jump?.center) return
    const zoom = Math.max(map.getZoom(), Math.min(14.5, map.getMaxZoom()))
    map.flyTo(jump.center, zoom, { duration: 0.8 })
  }, [map])

  const retry = () => setReloadKey((key) => key + 1)

  if (error) return <ErrorScreen message={error} onRetry={retry} />
  if (!zones || !health || !summary || !metrics || !quality) return <LoadingScreen />

  const frozenOk = Boolean(health.frozen && quality.freeze?.ok)
  const status = frozenOk ? COPY.status : COPY.dataCheckFail
  const showObserved = view === 'observed' || visible.observed

  return (
    <div className="app">
      <main className="main-screen" data-main-screen>
        <MapView
          zones={zones}
          view={view}
          visible={visible}
          observedYear={observedYear}
          basemap={basemap}
          modelData={modelData}
          modelError={modelError}
          riskData={riskData}
          riskError={riskError}
          scenarioYear={scenarioYear}
          onMapReady={onMapReady}
        />

        <header className="topbar">
          <div className="brand-card">
            <div className="brand-mark" aria-hidden="true">R</div>
            <div className="brand-copy">
              <p className="eyebrow">{COPY.kicker}</p>
              <h1 data-testid="title">{COPY.title}</h1>
              <p className="subtitle">{COPY.subtitle}</p>
              <span className={`status-pill ${frozenOk ? 'ok' : 'bad'}`} data-testid="status">
                {status}
              </span>
            </div>
          </div>
          <div className="top-actions">
            <div className="basemap-switch" role="group" aria-label="Base map">
              <button
                type="button"
                className={basemap === 'satellite' ? 'active' : ''}
                aria-pressed={basemap === 'satellite'}
                onClick={() => setBasemap('satellite')}
                data-testid="basemap-satellite"
              >
                {COPY.satellite}
              </button>
              <button
                type="button"
                className={basemap === 'street' ? 'active' : ''}
                aria-pressed={basemap === 'street'}
                onClick={() => setBasemap('street')}
                data-testid="basemap-street"
              >
                {COPY.street}
              </button>
            </div>
            <button
              type="button"
              className="layers-button"
              aria-expanded={layersOpen}
              onClick={() => setLayersOpen((open) => !open)}
              data-layers-trigger
              data-testid="layers-button"
            >
              {COPY.layers}
            </button>
          </div>
        </header>

        <LayersPanel
          open={layersOpen}
          onClose={() => setLayersOpen(false)}
          visible={visible}
          onToggle={toggleLayer}
          zones={zones}
          riskData={riskData}
          advanced={advanced}
          onAdvanced={() => setAdvanced((open) => !open)}
          modelYear={scenarioYear}
          modelYears={summary.forecast_years || []}
          onModelYear={setScenarioYear}
        />

        <section className="side-panel" data-testid="side-panel" aria-label="Map view and legend">
          <div className="view-tabs" role="tablist" aria-label="Map view">
            <button
              type="button"
              role="tab"
              aria-selected={view === 'risk'}
              className={view === 'risk' ? 'active' : ''}
              onClick={() => changeView('risk')}
              data-testid="view-risk"
            >
              {COPY.riskZones}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === 'past'}
              className={view === 'past' ? 'active' : ''}
              onClick={() => changeView('past')}
              data-testid="view-past"
            >
              {COPY.pastChange}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === 'observed'}
              className={view === 'observed' ? 'active' : ''}
              onClick={() => changeView('observed')}
              data-testid="view-observed"
            >
              {COPY.observedYears}
            </button>
          </div>

          {view === 'risk' ? (
            <RiskPanel
              riskData={riskData}
              riskError={riskError}
              scenarioYear={scenarioYear}
              forecastYears={summary.forecast_years || []}
              onYear={setScenarioYear}
              onLargest={() => jumpTo(riskData?.largest)}
              onPast={() => changeView('past')}
              zones={zones}
            />
          ) : null}

          {view === 'observed' ? (
            <div className="observed-year" role="group" aria-label={COPY.observedYear}>
              <span>{COPY.observedYear}</span>
              <div>
                {zones.observed_years.map((year) => (
                  <button
                    key={year}
                    type="button"
                    className={year === observedYear ? 'year-pill active' : 'year-pill'}
                    onClick={() => setObservedYear(year)}
                    aria-pressed={year === observedYear}
                    data-testid={`observed-year-${year}`}
                  >
                    {year}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div className="legend" data-testid="legend">
            {view === 'past' ? (
              <PastLegend
                zones={zones}
                visible={visible}
                showObserved={showObserved}
                observedYear={observedYear}
                view={view}
              />
            ) : null}
            {view === 'observed' ? <ObservedLegend zones={zones} observedYear={observedYear} /> : null}
          </div>

          <div className="reach-jumps" aria-label="Jump to reach">
            <span>Jump</span>
            {zones.jumps.map((jump) => (
              <button key={jump.id} type="button" onClick={() => jumpTo(jump)}>
                {jump.id === 'north' ? COPY.upper : jump.id === 'middle' ? COPY.town : COPY.lower}
              </button>
            ))}
          </div>
          {view === 'risk' ? null : (
            <p className="panel-caption">
              {view === 'observed'
                ? `${zones.starting_year} edge and the selected measured edge. No model layer is shown here.`
                : `${zones.counts.no_clear} of ${zones.total_stretches} stretches show no clear direction.`}
            </p>
          )}
        </section>

        <div className="info-actions">
          <button type="button" onClick={() => setOpenPanel('reliability')} data-testid="open-reliability">
            {COPY.reliability}
          </button>
          <button type="button" onClick={() => setOpenPanel('tested')} data-testid="open-tested">
            {COPY.tested}
          </button>
          <button type="button" onClick={() => setOpenPanel('technical')} data-testid="open-technical">
            {COPY.technical}
          </button>
        </div>

        <EvidencePanels
          zones={zones}
          metrics={metrics}
          quality={quality}
          health={health}
          riskData={riskData}
          openPanel={openPanel}
          onClose={() => setOpenPanel(null)}
        />
      </main>
    </div>
  )
}
