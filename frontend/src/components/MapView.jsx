import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { GeoJSON, ImageOverlay, MapContainer, Pane, Polygon, TileLayer, useMap } from 'react-leaflet'
import L from 'leaflet'
import { API_BASE } from '../api.js'
import { COPY } from '../i18n.js'

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function signedDirection(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null
  if (Math.abs(Number(value)) < 0.5) return 'showed little net movement'
  return `moved ${Number(value) > 0 ? 'outward' : 'inward'} about ${Math.abs(Number(value)).toFixed(digits)} m`
}

function zoneSentence(p) {
  const net = signedDirection(p.net_m)
  const recent = signedDirection(p.recent_10y_m)
  const recentPart = recent ? `; over the last ${p.recent_years} years it ${recent}` : ''
  return `Between ${p.years[0]} and ${p.years[1]} this ${p.side === 'L' ? 'left' : 'right'} bank ${net}${recentPart} (${p.confidence}).`
}

function zonePopup(p) {
  return `
    <div class="river-popup-body">
      <strong>${escapeHtml(p.tier_label)}</strong>
      <p>${escapeHtml(zoneSentence(p))}</p>
    </div>`
}

function predictedRange(p) {
  const low = Math.abs(Number(p.min_predicted_m))
  const high = Math.abs(Number(p.max_predicted_m))
  if (!Number.isFinite(low) || !Number.isFinite(high)) return 'an unknown distance'
  return low === high ? `${low.toFixed(0)} m` : `${low.toFixed(0)}–${high.toFixed(0)} m`
}

function riskPopup(p, originYear) {
  const direction = p.risk_class === 'erosion'
    ? 'outward, toward the land'
    : 'inward, toward the river'
  const flagNote = p.flagged_segments
    ? ` ${p.flagged_segments} of ${p.segment_count} segment(s) carry a flagged 2023 starting point.`
    : ''
  const uncertainty = p.mean_uncertainty_m
    ? ` The average model spread is about ±${Number(p.mean_uncertainty_m).toFixed(0)} m.`
    : ''
  return `
    <div class="river-popup-body">
      <strong>${escapeHtml(p.label)}</strong>
      <p>Between ${originYear} and ${p.year}, this ${escapeHtml(p.side_label)} bank stretch is predicted to move ${direction} by about ${predictedRange(p)}.${uncertainty}${flagNote}</p>
      <p class="popup-note">Scenario area, not a safety rating.</p>
    </div>`
}

function styleForRisk(p) {
  return {
    color: p.outline,
    weight: p.risk_class === 'erosion' ? 3.2 : 2.8,
    opacity: 0.96,
    fillColor: p.fill,
    fillOpacity: p.fill_opacity,
    lineJoin: 'round',
  }
}

function styleForTier(p) {
  const styles = {
    strong: { weight: 2.4, dashArray: null },
    moderate: { weight: 1.8, dashArray: '7 4' },
    land_gained: { weight: 2, dashArray: '2 3', lineCap: 'round' },
    no_clear: { weight: 0.7, dashArray: null },
  }
  const s = styles[p.tier] || styles.no_clear
  return {
    color: p.outline,
    weight: s.weight,
    opacity: p.tier === 'no_clear' ? 0.7 : 0.95,
    fillColor: p.fill,
    fillOpacity: p.fill_opacity,
    dashArray: s.dashArray,
    lineCap: s.lineCap || 'butt',
  }
}

function pointInRing(latlng, ring) {
  let inside = false
  const x = latlng.lng
  const y = latlng.lat
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0]
    const yi = ring[i][1]
    const xj = ring[j][0]
    const yj = ring[j][1]
    const crosses = ((yi > y) !== (yj > y)) && (x < ((xj - xi) * (y - yi)) / (yj - yi) + xi)
    if (crosses) inside = !inside
  }
  return inside
}

function MapLock({ corridorBounds, corridorRing, onReady }) {
  const map = useMap()
  useEffect(() => {
    map.options.zoomSnap = 0.25
    map.options.zoomDelta = 0.5
    map.options.boxZoom = false
    map.options.maxBoundsViscosity = 1
    map.setMaxBounds(corridorBounds, { viscosity: 1 })
    const container = map.getContainer()
    let timer = null
    let guardTimer = null
    let guardPending = false
    let lastInside = map.getCenter()
    const centerInside = () => pointInRing(map.getCenter(), corridorRing)
    const update = () => {
      map.invalidateSize({ pan: false })
      map.setMinZoom(0)
      const raw = map.getBoundsZoom(corridorBounds, false)
      const min = Math.floor(raw * 4) / 4
      map.setMinZoom(min)
      if (map.getZoom() < min) map.setZoom(min, { animate: false })
      if (!centerInside()) {
        map.fitBounds(corridorBounds, { animate: false, padding: [0, 0] })
      }
      if (centerInside()) lastInside = map.getCenter()
    }
    const apply = () => {
      update()
      window.clearTimeout(timer)
      timer = window.setTimeout(() => {
        map.fitBounds(corridorBounds, { animate: false, padding: [0, 0] })
        update()
        if (centerInside()) lastInside = map.getCenter()
      }, 0)
    }
    const keepInside = () => {
      if (centerInside()) {
        lastInside = map.getCenter()
        return
      }
      if (guardPending) return
      guardPending = true
      window.clearTimeout(guardTimer)
      guardTimer = window.setTimeout(() => {
        guardPending = false
        if (!centerInside()) map.setView(lastInside, map.getZoom(), { animate: false })
      }, 0)
    }
    apply()
    map.on('moveend', keepInside)
    const observer = new ResizeObserver(update)
    observer.observe(container)
    window.addEventListener('resize', update)
    window.addEventListener('orientationchange', update)
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') map.closePopup()
    }
    window.addEventListener('keydown', closeOnEscape)
    window.__riverMap = map
    onReady?.(map)
    return () => {
      window.clearTimeout(timer)
      window.clearTimeout(guardTimer)
      observer.disconnect()
      window.removeEventListener('resize', update)
      window.removeEventListener('orientationchange', update)
      window.removeEventListener('keydown', closeOnEscape)
      map.off('moveend', keepInside)
    }
  }, [map, corridorBounds, corridorRing, onReady])
  return null
}

function layerStyleForEdges(feature, observedView) {
  const isStart = feature.properties.year === feature.properties.starting_year
  return {
    color: isStart ? '#ffe3a0' : '#ff7a45',
    weight: isStart ? (observedView ? 1.5 : 1.3) : 2.1,
    opacity: isStart && observedView ? 0.6 : 0.95,
    dashArray: isStart ? null : '8 5',
    fill: false,
    lineCap: 'round',
  }
}

export default function MapView({
  zones,
  view,
  visible,
  observedYear,
  basemap,
  modelData,
  modelError,
  riskData,
  riskError,
  scenarioYear,
  onMapReady,
}) {
  const bounds = useMemo(() => {
    const [west, south, east, north] = zones.bounds
    return L.latLngBounds([south, west], [north, east])
  }, [zones.bounds])
  const corridorRing = zones.corridor.features[0].geometry.coordinates[0]
  const fallbackBounds = useMemo(() => {
    const [west, south, east, north] = zones.fallback_bounds || zones.bounds
    return L.latLngBounds([south, west], [north, east])
  }, [zones.fallback_bounds, zones.bounds])
  const corridorOutline = useMemo(
    () => [
      ...corridorRing.map(([lng, lat]) => [lat, lng]),
      [corridorRing[0][1], corridorRing[0][0]],
    ],
    [corridorRing],
  )
  const [offline, setOffline] = useState(
    typeof navigator !== 'undefined' && navigator.onLine === false,
  )
  const tileErrors = useRef(0)
  const zoneLayers = useRef({})
  const riskLayers = useRef({})
  const mapRef = useRef(null)
  const maxErrors = Number(zones.map.fallback_tile_error_limit || 3)
  const baseUrl = zones.basemap.satellite_url
  const streetUrl = zones.basemap.street_url

  useEffect(() => {
    tileErrors.current = 0
    if (basemap === 'street') setOffline(false)
  }, [basemap])

  useEffect(() => {
    const goOnline = () => setOffline(false)
    const goOffline = () => setOffline(true)
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [])

  useEffect(() => {
    window.__riverState = {
      basemap,
      offline,
      observedYear,
      scenarioYear,
      view,
      visible,
    }
  }, [basemap, offline, observedYear, scenarioYear, view, visible])

  useEffect(() => {
    window.__openZone = (id) => {
      const layer = zoneLayers.current[id]
      if (layer) {
        layer.openPopup()
        return true
      }
      return false
    }
    return () => { delete window.__openZone }
  }, [zones.zones.features])

  useEffect(() => {
    window.__openRiskZone = (id) => {
      const layer = riskLayers.current[id]
      if (layer) {
        layer.openPopup()
        return true
      }
      return false
    }
    return () => { delete window.__openRiskZone }
  }, [riskData])

  const onTileError = useCallback(() => {
    tileErrors.current += 1
    if (tileErrors.current >= maxErrors) setOffline(true)
  }, [maxErrors])

  const zoneFeatures = useMemo(() => {
    const rank = { no_clear: 0, land_gained: 1, moderate: 2, strong: 3 }
    return [...zones.zones.features].sort(
      (a, b) => (rank[a.properties.tier] ?? 0) - (rank[b.properties.tier] ?? 0),
    )
  }, [zones.zones.features])

  const edgeFeatures = useMemo(() => {
    return zones.edges.features
      .filter((f) => f.properties.year === zones.starting_year || f.properties.year === observedYear)
      .map((f) => ({
        ...f,
        properties: { ...f.properties, starting_year: zones.starting_year },
      }))
  }, [zones.edges.features, zones.starting_year, observedYear])

  const edgesKey = `${view}-${observedYear}-${visible.edge2023}-${visible.observed}`
  const handleReady = useCallback((map) => {
    mapRef.current = map
    onMapReady?.(map)
  }, [onMapReady])

  return (
    <div className="map-stage" id="map-stage">
      <MapContainer
        id="map"
        className="map"
        center={[23.2, 90.22]}
        zoom={13}
        zoomControl={false}
        maxBounds={bounds}
        maxBoundsViscosity={1}
        boxZoom={false}
        zoomSnap={0.25}
        zoomDelta={0.5}
        worldCopyJump={false}
        preferCanvas={false}
        attributionControl
      >
        <Pane name="fallback-pane" style={{ zIndex: 240 }} />
        <Pane name="corridor-pane" style={{ zIndex: 360 }} />
        <Pane name="risk-line-pane" style={{ zIndex: 405 }} />
        <Pane name="risk-pane" style={{ zIndex: 415 }} />
        <Pane name="zone-pane" style={{ zIndex: 420 }} />
        <Pane name="edge-pane" style={{ zIndex: 430 }} />
        <Pane name="model-pane" style={{ zIndex: 440 }} />

        <MapLock corridorBounds={bounds} corridorRing={corridorRing} onReady={handleReady} />

        {basemap === 'satellite' && !offline ? (
          <TileLayer
            key="satellite"
            url={baseUrl}
            attribution={zones.basemap.satellite_attribution}
            maxNativeZoom={zones.map.max_native_zoom}
            maxZoom={zones.map.max_zoom}
            eventHandlers={{ tileerror: onTileError, tileload: () => { tileErrors.current = 0 } }}
          />
        ) : null}
        {basemap === 'street' ? (
          <TileLayer
            key="street"
            url={streetUrl}
            attribution={zones.basemap.street_attribution}
            maxZoom={zones.map.max_zoom}
          />
        ) : null}
        {basemap === 'satellite' && offline && zones.fallback_available ? (
          <ImageOverlay
            url={`${API_BASE}${zones.fallback_image_url}`}
            bounds={fallbackBounds}
            opacity={1}
            pane="fallback-pane"
          />
        ) : null}

        <Polygon
          pane="corridor-pane"
          positions={corridorOutline}
          pathOptions={{
            stroke: true,
            color: '#7a8f99',
            weight: 0.8,
            opacity: 0.45,
            fill: false,
            interactive: false,
          }}
        />

        {view === 'risk' && visible.risk && riskData?.predicted_banklines ? (
          <GeoJSON
            key={`risk-banks-${riskData.year}`}
            data={riskData.predicted_banklines}
            style={{
              color: riskData.legend?.predicted_bank || '#173b57',
              weight: 1.7,
              opacity: 0.8,
              dashArray: '5 5',
              fill: false,
            }}
            pane="risk-line-pane"
            interactive={false}
          />
        ) : null}

        {view === 'risk' && visible.risk && riskData?.zones ? (
          <GeoJSON
            key={`risk-zones-${riskData.year}-${riskData.zones.features.length}`}
            data={riskData.zones}
            style={(feature) => styleForRisk(feature.properties)}
            pane="risk-pane"
            onEachFeature={(feature, layer) => {
              riskLayers.current[feature.properties.id] = layer
              layer.bindPopup(riskPopup(feature.properties, riskData.origin_year), {
                maxWidth: 320,
                className: 'river-popup',
                autoPan: true,
                closeButton: true,
              })
            }}
          />
        ) : null}

        {visible.zones && view !== 'observed' ? (
          <GeoJSON
            key={`zones-${zones.total_stretches}-${zones.counts.land_gained}`}
            data={{ type: 'FeatureCollection', features: zoneFeatures }}
            style={(feature) => styleForTier(feature.properties)}
            pane="zone-pane"
            onEachFeature={(feature, layer) => {
              zoneLayers.current[feature.properties.id] = layer
              layer.bindPopup(zonePopup(feature.properties), {
                maxWidth: 310,
                className: 'river-popup',
                autoPan: true,
                closeButton: true,
              })
            }}
          />
        ) : null}

        {view === 'observed' ? (
          <GeoJSON
            key={`edges-${edgesKey}`}
            data={{ type: 'FeatureCollection', features: edgeFeatures }}
            style={(feature) => layerStyleForEdges(feature, true)}
            pane="edge-pane"
            interactive={false}
          />
        ) : null}
        {visible.edge2023 && view !== 'observed' ? (
          <GeoJSON
            key={`start-edge-${zones.starting_year}`}
            data={{
              type: 'FeatureCollection',
              features: edgeFeatures
                .filter((f) => f.properties.year === zones.starting_year)
                .map((f) => ({ ...f, properties: { ...f.properties, starting_year: zones.starting_year } })),
            }}
            style={(feature) => layerStyleForEdges(feature, false)}
            pane="edge-pane"
            interactive={false}
          />
        ) : null}
        {visible.observed && view !== 'observed' ? (
          <GeoJSON
            key={`observed-edge-${observedYear}`}
            data={{
              type: 'FeatureCollection',
              features: edgeFeatures
                .filter((f) => f.properties.year === observedYear)
                .map((f) => ({ ...f, properties: { ...f.properties, starting_year: zones.starting_year } })),
            }}
            style={(feature) => layerStyleForEdges(feature, false)}
            pane="edge-pane"
            interactive={false}
          />
        ) : null}

        {visible.model && view !== 'observed' && modelData?.banklines ? (
          <GeoJSON
            key={`model-${modelData.year}`}
            data={{
              type: 'FeatureCollection',
              features: modelData.banklines.features.filter((f) => f.properties.kind !== 'corridor'),
            }}
            style={{
              color: '#8a5bc4',
              weight: 1.5,
              opacity: 0.8,
              dashArray: '1 5',
              fill: false,
            }}
            pane="model-pane"
            interactive={false}
          />
        ) : null}
      </MapContainer>

      {basemap === 'satellite' && offline ? (
        <div className="satellite-banner" role="status" data-testid="satellite-message">
          {zones.basemap.fallback_message}
        </div>
      ) : null}
      {modelError ? <div className="model-banner" role="status">{modelError}</div> : null}
      {riskError ? <div className="risk-banner" role="status">{riskError}</div> : null}

      <div className="map-tools" aria-label="Map controls">
        <button type="button" onClick={() => mapRef.current?.zoomIn()} aria-label={COPY.zoomIn}>+</button>
        <button type="button" onClick={() => mapRef.current?.zoomOut()} aria-label={COPY.zoomOut}>−</button>
        <button type="button" className="reset" onClick={() => mapRef.current?.fitBounds(bounds, { animate: false })} aria-label={COPY.reset}>⌂</button>
      </div>
    </div>
  )
}
