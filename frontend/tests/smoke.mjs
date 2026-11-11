import assert from 'node:assert/strict'
import { existsSync, mkdirSync, readdirSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const UI_URL = process.env.RIVER_UI_URL || 'http://localhost:5173'
const API_URL = process.env.RIVER_API_URL || 'http://127.0.0.1:8000'
const ROOT = dirname(dirname(dirname(fileURLToPath(import.meta.url))))
const SHOT_DIR = process.env.RIVER_SHOT_DIR || join(ROOT, 'demo', 'ui-v2')

const BANNED = [
  ['forecast', /\bforecast/i],
  ['validated', /\bvalidated\b/i],
  ['accurate', /\baccurate\b/i],
  ['low risk', /\blow risk\b/i],
  ['safe', /\bsafe\b/i],
  ['MAE', /\bmae\b/i],
  ['RMSE', /\brmse\b/i],
  ['F1', /\bf1\b/i],
  ['directional', /\bdirectional\b/i],
  ['random forest', /\brandom forest\b/i],
  ['hash', /\bhash\b/i],
  ['origin', /\borigin\b/i],
  ['cutoff', /\bcutoff\b/i],
  ['tolerance', /\btolerance\b/i],
  ['tree spread', /\btree spread\b/i],
  ['prediction', /\bprediction\b/i],
]

function installedChromium() {
  if (process.env.CHROMIUM_PATH) return process.env.CHROMIUM_PATH
  const common = ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/snap/bin/chromium']
  const found = common.find((path) => existsSync(path))
  if (found) return found
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH || join(homedir(), '.cache', 'ms-playwright')
  if (!existsSync(root)) return undefined
  return readdirSync(root)
    .filter((name) => name.startsWith('chromium-'))
    .sort()
    .reverse()
    .flatMap((name) => [
      join(root, name, 'chrome-linux64', 'chrome'),
      join(root, name, 'chrome-linux', 'chrome'),
    ])
    .find((path) => existsSync(path))
}

async function getJson(path) {
  const response = await fetch(`${API_URL}${path}`)
  assert.equal(response.status, 200, `${path} returned HTTP ${response.status}`)
  return response.json()
}

function assertNoBanned(text, where) {
  const found = BANNED.filter(([, pattern]) => pattern.test(text)).map(([word]) => word)
  assert.deepEqual(found, [], `${where} contains banned words: ${found.join(', ')}`)
}

function pointInRing(latlng, ring) {
  const x = latlng.lng
  const y = latlng.lat
  let inside = false
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

async function pageMetrics(page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    scrollHeight: document.documentElement.scrollHeight,
    clientHeight: document.documentElement.clientHeight,
    innerHeight: window.innerHeight,
    innerWidth: window.innerWidth,
  }))
}

async function assertNoPageScroll(page, where) {
  const size = await pageMetrics(page)
  assert.ok(size.scrollWidth <= size.clientWidth + 1, `${where} overflows horizontally: ${JSON.stringify(size)}`)
  assert.ok(size.scrollHeight <= size.clientHeight + 1, `${where} scrolls vertically: ${JSON.stringify(size)}`)
}

async function waitForMap(page) {
  await page.waitForFunction(() => Boolean(window.__riverMap), null, { timeout: 20000 })
  await page.waitForTimeout(900)
}

async function mapView(page) {
  return page.evaluate(() => {
    const map = window.__riverMap
    const bounds = map.getBounds()
    const center = map.getCenter()
    return {
      zoom: map.getZoom(),
      minZoom: map.getMinZoom(),
      maxZoom: map.getMaxZoom(),
      west: bounds.getWest(),
      south: bounds.getSouth(),
      east: bounds.getEast(),
      north: bounds.getNorth(),
      center: { lng: center.lng, lat: center.lat },
      state: window.__riverState,
    }
  })
}

async function assertCorridorFits(page, zones, where) {
  const view = await mapView(page)
  assert.ok(view.zoom >= view.minZoom, `${where} is below its minimum zoom`)
  assert.ok(view.west <= zones.bounds[0] + 1e-6, `${where} cuts the west edge of the corridor`)
  assert.ok(view.south <= zones.bounds[1] + 1e-6, `${where} cuts the south edge of the corridor`)
  assert.ok(view.east >= zones.bounds[2] - 1e-6, `${where} cuts the east edge of the corridor`)
  assert.ok(view.north >= zones.bounds[3] - 1e-6, `${where} cuts the north edge of the corridor`)
  return view
}

async function openZone(page, id) {
  const opened = await page.evaluate((zoneId) => window.__openZone?.(zoneId) === true, id)
  assert.ok(opened, `zone ${id} has no popup layer`)
  await page.locator('.leaflet-popup-content').waitFor({ timeout: 5000 })
  return page.locator('.leaflet-popup-content').innerText()
}

async function openRiskZone(page, id) {
  const opened = await page.evaluate((zoneId) => window.__openRiskZone?.(zoneId) === true, id)
  assert.ok(opened, `risk zone ${id} has no popup layer`)
  await page.locator('.leaflet-popup-content').waitFor({ timeout: 5000 })
  return page.locator('.leaflet-popup-content').innerText()
}

function checkRiskRules(risk, expectedYear = 2026) {
  assert.equal(risk.year, expectedYear)
  assert.equal(risk.origin_year, 2023)
  assert.equal(risk.threshold_m, 15)
  assert.equal(risk.total_segments, 150)
  assert.deepEqual(risk.segment_counts, risk.year === 2026
    ? { erosion: 9, accretion: 11, low_movement: 130 }
    : risk.segment_counts)
  assert.equal(risk.zones.type, 'FeatureCollection')
  assert.equal(risk.zones.features.length, Object.values(risk.zone_counts).reduce((total, count) => total + count, 0))
  assert.equal(risk.low_movement_segments_drawn, false)
  assert.ok(risk.predicted_banklines.features.length > 0)
  assert.ok(risk.limitations.length > 0)
  assert.ok(risk.largest)
  assert.ok(risk.largest.center.length === 2)
  for (const feature of risk.zones.features) {
    const p = feature.properties
    assert.equal(p.year, risk.year)
    assert.ok(['erosion', 'accretion'].includes(p.risk_class))
    assert.ok(['Polygon', 'MultiPolygon'].includes(feature.geometry.type))
    assert.ok(p.max_abs_m > risk.threshold_m)
    assert.ok(p.segment_count > 0)
    assert.ok(p.fill.startsWith('#'))
    assert.ok(p.outline.startsWith('#'))
  }
  return risk
}

function checkZoneRules(zones) {
  assert.equal(zones.total_stretches, 50)
  assert.deepEqual(zones.counts, { strong: 0, moderate: 0, land_gained: 11, no_clear: 39 })
  assert.equal(zones.features_with_geometry, 49)
  assert.equal(zones.zones.features.length, 49)
  assert.equal(zones.undefined_intervals, 4)
  assert.equal(zones.relative_available, false)
  assert.equal(zones.diagnostics.land_gained_opposite_outward, 9)
  assert.equal(zones.diagnostics.land_gained_both_inward, 0)
  assert.equal(zones.diagnostics.period_rank.n, 39)
  assert.equal(Number(zones.diagnostics.period_rank.spearman.toFixed(4)), 0.1463)
  assert.equal(zones.diagnostics.period_rank.p > 0.3, true)
  assert.equal(zones.diagnostics.net_m.median, 0)
  assert.equal(zones.diagnostics.interval_width_m.median > 135, true)
  assert.equal(Number(zones.diagnostics.median_width_by_year['1989'].toFixed(2)), 338.75)
  assert.equal(Number(zones.diagnostics.median_width_by_year['2026'].toFixed(2)), 197.72)

  const tiers = { strong: 0, moderate: 0, land_gained: 0, no_clear: 0 }
  for (const feature of zones.zones.features) {
    const p = feature.properties
    tiers[p.tier] += 1
    if (p.tier === 'strong') assert.ok(p.lower_m >= 150, `${p.id} strong below 150 m`)
    if (p.tier === 'moderate') {
      assert.ok(p.lower_m > 0 && p.lower_m >= 30, `${p.id} moderate below 30 m`)
      assert.ok(p.lower_m > 0 || p.upper_m < 0, `${p.id} moderate crosses zero`)
    }
    if (p.tier === 'land_gained') assert.ok(p.upper_m <= -30, `${p.id} land gained above -30 m`)
    if (p.tier === 'no_clear') {
      assert.ok(
        p.lower_m === null
        || p.lower_m < 150
        || (p.upper_m !== null && p.upper_m > -30),
        `${p.id} no_clear contradicts the fixed rule`,
      )
    }
  }
  assert.deepEqual(tiers, { strong: 0, moderate: 0, land_gained: 11, no_clear: 38 })
}

async function desktopProof(browser, zones, risk, metrics) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  const errors = []
  const satelliteRequests = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('request', (request) => {
    if (request.url().includes('server.arcgisonline.com')) satelliteRequests.push(request.url())
  })

  try {
    await page.goto(UI_URL, { waitUntil: 'domcontentloaded' })
    await page.getByTestId('title').waitFor({ timeout: 15000 })
    await page.getByTestId('risk-count-erosion').waitFor({ timeout: 15000 })
    await waitForMap(page)
    await page.waitForFunction(
      () => document.querySelectorAll('img.leaflet-tile-loaded').length > 0,
      null,
      { timeout: 20000 },
    )

    assert.equal(await page.title(), 'Riverbank Change Monitor · Arial Khan')
    assert.match(await page.getByTestId('title').innerText(), /Riverbank Change Monitor/)
    assert.match(await page.getByTestId('status').innerText(), /not a safety rating/)
    assert.ok(satelliteRequests.length > 0, 'no Esri satellite tiles were requested')
    assert.match(await page.locator('.leaflet-control-attribution').innerText(), /Esri/)
    await assertNoPageScroll(page, 'desktop')

    assert.equal(await page.getByTestId('view-risk').getAttribute('aria-selected'), 'true')
    assert.equal(await page.getByTestId('risk-year-2026').getAttribute('aria-pressed'), 'true')
    assert.equal(await page.getByTestId('risk-count-erosion').innerText(), String(risk.segment_counts.erosion))
    assert.equal(await page.getByTestId('risk-count-accretion').innerText(), String(risk.segment_counts.accretion))
    assert.equal(await page.getByTestId('risk-count-low').innerText(), String(risk.segment_counts.low_movement))
    assert.equal(await page.locator('.leaflet-risk-pane-pane path').count() > 0, true, 'risk zones did not render')

    const mainText = await page.locator('[data-main-screen]').innerText()
    assertNoBanned(mainText, 'main screen')
    assert.match(mainText, /Only stretches predicted to move more than 15 m are drawn/)
    assert.ok(!/\baccuracy\b/i.test(mainText), 'main screen shows an accuracy claim')
    assert.ok(!/\bforecast\b/i.test(mainText), 'main screen shows the banned word forecast')

    await assertCorridorFits(page, zones, 'desktop')
    const ring = zones.corridor.features[0].geometry.coordinates[0]
    const initial = await mapView(page)
    assert.ok(pointInRing(initial.center, ring), 'initial map center is outside the corridor')

    await page.getByRole('button', { name: 'Zoom out' }).click()
    await page.getByRole('button', { name: 'Zoom out' }).click()
    await page.getByRole('button', { name: 'Zoom out' }).click()
    await page.waitForTimeout(300)
    let locked = await mapView(page)
    assert.ok(locked.zoom >= locked.minZoom, 'button zoom escaped the minimum zoom')
    assert.ok(pointInRing(locked.center, ring), 'button zoom moved the center outside the corridor')

    await page.evaluate(() => window.__riverMap.setZoom(window.__riverMap.getMinZoom() + 1))
    await page.mouse.move(720, 450)
    await page.mouse.wheel(0, 1200)
    await page.waitForTimeout(350)
    locked = await mapView(page)
    assert.ok(locked.zoom >= locked.minZoom, 'wheel zoom escaped the minimum zoom')
    assert.ok(pointInRing(locked.center, ring), 'wheel zoom moved the center outside the corridor')

    await page.locator('.leaflet-container').click({ position: { x: 500, y: 350 } })
    await page.keyboard.press('-')
    await page.waitForTimeout(300)
    locked = await mapView(page)
    assert.ok(locked.zoom >= locked.minZoom, 'keyboard zoom escaped the minimum zoom')

    await page.mouse.move(720, 450)
    await page.mouse.down()
    await page.mouse.move(1120, 700, { steps: 12 })
    await page.mouse.up()
    await page.waitForFunction(
      (corridorRing) => {
        const center = window.__riverMap.getCenter()
        let inside = false
        for (let i = 0, j = corridorRing.length - 1; i < corridorRing.length; j = i++) {
          const xi = corridorRing[i][0]
          const yi = corridorRing[i][1]
          const xj = corridorRing[j][0]
          const yj = corridorRing[j][1]
          const crosses = ((yi > center.lat) !== (yj > center.lat))
            && (center.lng < ((xj - xi) * (center.lat - yi)) / (yj - yi) + xi)
          if (crosses) inside = !inside
        }
        return inside
      },
      ring,
      { timeout: 5000 },
    )
    await page.waitForTimeout(300)
    locked = await mapView(page)
    assert.ok(pointInRing(locked.center, ring), 'drag moved the map center outside the corridor')

    const zoomBeforeShiftDrag = locked.zoom
    await page.keyboard.down('Shift')
    await page.mouse.move(720, 450)
    await page.mouse.down()
    await page.mouse.move(360, 260, { steps: 12 })
    await page.mouse.up()
    await page.keyboard.up('Shift')
    await page.waitForFunction(
      (corridorRing) => {
        const center = window.__riverMap.getCenter()
        let inside = false
        for (let i = 0, j = corridorRing.length - 1; i < corridorRing.length; j = i++) {
          const xi = corridorRing[i][0]
          const yi = corridorRing[i][1]
          const xj = corridorRing[j][0]
          const yj = corridorRing[j][1]
          const crosses = ((yi > center.lat) !== (yj > center.lat))
            && (center.lng < ((xj - xi) * (center.lat - yi)) / (yj - yi) + xi)
          if (crosses) inside = !inside
        }
        return inside
      },
      ring,
      { timeout: 5000 },
    )
    locked = await mapView(page)
    assert.equal(locked.zoom, zoomBeforeShiftDrag, 'shift-drag changed the zoom')

    await page.getByRole('button', { name: 'Reset view' }).click()
    await page.waitForTimeout(500)
    await assertCorridorFits(page, zones, 'desktop after reset')

    const riskPopup = await openRiskZone(page, risk.largest.id)
    assert.match(riskPopup, /Between 2023 and 2026/)
    assert.match(riskPopup, /predicted to move (outward|inward)/)
    assert.match(riskPopup, /Scenario area, not a safety rating/)
    assertNoBanned(riskPopup, 'risk popup')
    await page.keyboard.press('Escape')
    await page.waitForTimeout(300)
    assert.equal(await page.locator('.leaflet-popup').count(), 0, 'Esc did not close the risk popup')
    await page.screenshot({ path: join(SHOT_DIR, 'desktop-risk.png') })

    await page.getByTestId('view-past').click()
    await page.waitForFunction(() => window.__riverState.view === 'past', null, { timeout: 5000 })
    const pastState = await mapView(page)
    assert.equal(pastState.state.visible.risk, false)
    assert.equal(pastState.state.visible.zones, true)
    for (const tier of zones.tier_order) {
      assert.equal(
        Number(await page.getByTestId(`legend-count-${tier}`).innerText()),
        zones.counts[tier],
        `legend count for ${tier} does not match the API`,
      )
    }
    assert.equal(await page.getByTestId('legend-count-land_gained').innerText(), '11')
    assert.equal(await page.getByTestId('legend-count-no_clear').innerText(), '39')

    const zoneId = zones.zones.features.find((f) => f.properties.tier === 'land_gained').properties.id
    const popup = await openZone(page, zoneId)
    assert.match(popup, /Between 1989 and 2026/)
    assert.match(popup, /(moved (outward|inward)|little net movement)/)
    assert.match(popup, /\d+(?:\.\d+)? m/)
    assertNoBanned(popup, 'zone popup')
    await page.keyboard.press('Escape')
    await page.waitForTimeout(300)
    assert.equal(await page.locator('.leaflet-popup').count(), 0, 'Esc did not close the zone popup')

    await openZone(page, zoneId)
    await page.locator('.leaflet-popup-close-button').click()
    await page.waitForTimeout(300)
    assert.equal(await page.locator('.leaflet-popup').count(), 0, 'the popup close button did not close the popup')

    await page.screenshot({ path: join(SHOT_DIR, 'desktop-past.png') })

    const zoomBeforePanel = (await mapView(page)).zoom
    await page.getByTestId('open-reliability').click()
    const reliability = page.getByTestId('panel-reliability')
    await reliability.waitFor({ state: 'visible' })
    assert.match(await reliability.innerText(), /0\s+Strong past movement/)
    assert.match(await reliability.innerText(), /0\s+Moderate past movement/)
    assert.match(await reliability.innerText(), /11\s+Land gained/)
    assert.match(await reliability.innerText(), /39\s+No clear movement/)
    assert.match(await reliability.innerText(), /338\.75|339 m/)
    assert.match(await reliability.innerText(), /0\.15/)
    assert.match(await reliability.innerText(), /9 outward segments and 11 inward segments for 2026/)
    assert.match(await reliability.innerText(), /no-change answer is the stronger overall test result/)
    const panelFocus = await page.evaluate(() => Boolean(document.activeElement?.closest('dialog')))
    assert.ok(panelFocus, 'focus did not move into the evidence panel')
    assert.equal((await mapView(page)).zoom, zoomBeforePanel, 'map zoom changed while the panel was open')
    await page.screenshot({ path: join(SHOT_DIR, 'desktop-reliability.png') })
    await page.keyboard.press('Escape')
    await reliability.waitFor({ state: 'hidden' })
    assert.equal(
      await page.evaluate(() => document.activeElement?.getAttribute('data-testid')),
      'open-reliability',
      'focus did not return to the panel trigger',
    )

    await page.getByTestId('open-tested').click()
    const tested = page.getByTestId('panel-tested')
    await tested.waitFor({ state: 'visible' })
    const testedText = await tested.innerText()
    assert.match(testedText, /fixed before the 2024–2026 observations/)
    assert.match(testedText, /398/)
    assert.match(testedText, /Test years\s+2024–2026/)
    assert.match(testedText, /POST-2023 EXTRACTION/i)
    assertNoBanned(testedText.replace(/POST-2023 EXTRACTION/i, ''), 'tested panel')
    await page.screenshot({ path: join(SHOT_DIR, 'desktop-tested.png') })
    await page.keyboard.press('Escape')
    await tested.waitFor({ state: 'hidden' })

    await page.getByTestId('layers-button').click()
    const layers = page.getByTestId('layers-panel')
    await layers.waitFor({ state: 'visible' })
    assert.match(await layers.innerText(), /0 \/ 0 \/ 11 \/ 39/)
    assert.match(await layers.innerText(), /9 outward \/ 11 inward/)
    assert.equal(await page.getByTestId('toggle-risk').isChecked(), false)
    assert.equal(await page.getByTestId('toggle-zones').isChecked(), true)
    assert.equal(await page.getByTestId('toggle-model').count(), 0, 'model control should be collapsed by default')
    await page.getByText('Advanced', { exact: true }).click()
    assert.equal(await page.getByTestId('toggle-model').count(), 1)
    assert.equal(await page.getByTestId('toggle-model').isChecked(), false)
    await page.getByTestId('toggle-model').check()
    await page.waitForFunction(() => window.__riverState.visible.model === true, null, { timeout: 5000 })
    await page.waitForFunction(() => document.querySelectorAll('.leaflet-model-pane-pane path').length > 0, null, { timeout: 10000 })
    assert.equal(await page.locator('.leaflet-model-pane-pane path').count() > 0, true, 'model layer did not render')
    await page.getByTestId('toggle-model').uncheck()
    await page.waitForFunction(() => window.__riverState.visible.model === false, null, { timeout: 5000 })
    await page.getByTestId('toggle-zones').uncheck()
    await page.waitForFunction(() => window.__riverState.visible.zones === false, null, { timeout: 5000 })
    await page.getByTestId('toggle-zones').check()
    await page.keyboard.press('Escape')
    await layers.waitFor({ state: 'hidden' })

    await page.getByTestId('view-observed').click()
    await page.waitForFunction(() => window.__riverState.view === 'observed', null, { timeout: 5000 })
    let state = (await mapView(page)).state
    assert.equal(state.visible.zones, false)
    assert.equal(state.visible.risk, false)
    assert.equal(state.visible.model, false)
    assert.equal(await page.getByTestId('toggle-model').count(), 0)
    assert.equal(await page.getByTestId('observed-year-2024').count(), 1)
    assert.equal(await page.getByTestId('observed-year-2025').count(), 1)
    assert.equal(await page.getByTestId('observed-year-2026').count(), 1)
    await page.getByTestId('observed-year-2024').click()
    await page.waitForFunction(() => window.__riverState.observedYear === 2024, null, { timeout: 5000 })
    state = (await mapView(page)).state
    assert.equal(state.observedYear, 2024)
    await page.screenshot({ path: join(SHOT_DIR, 'desktop-observed.png') })

    await page.getByTestId('view-past').click()
    await page.waitForFunction(() => window.__riverState.view === 'past', null, { timeout: 5000 })
    await page.getByTestId('basemap-street').click()
    await page.waitForFunction(() => window.__riverState.basemap === 'street', null, { timeout: 5000 })
    assert.match(await page.locator('.leaflet-control-attribution').innerText(), /OpenStreetMap/)
    await page.getByTestId('basemap-satellite').click()
    await page.waitForFunction(() => window.__riverState.basemap === 'satellite', null, { timeout: 5000 })

    assert.deepEqual(errors, [], `desktop browser errors:\n${errors.join('\n')}`)
    return { satelliteRequests: satelliteRequests.length }
  } finally {
    await context.close()
  }
}

async function responsiveProof(browser, zones, risk) {
  const context = await browser.newContext({ viewport: { width: 1024, height: 768 } })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
  try {
    await page.goto(UI_URL, { waitUntil: 'domcontentloaded' })
    await page.getByTestId('title').waitFor({ timeout: 15000 })
    await page.getByTestId('risk-count-erosion').waitFor({ timeout: 15000 })
    await waitForMap(page)
    await assertNoPageScroll(page, 'tablet')
    await assertCorridorFits(page, zones, 'tablet')
    assert.equal(await page.getByTestId('risk-count-erosion').innerText(), String(risk.segment_counts.erosion))
    assert.equal(await page.locator('.leaflet-risk-pane-pane path').count() > 0, true, 'tablet risk zones did not render')
    await page.screenshot({ path: join(SHOT_DIR, 'tablet-risk.png') })

    await page.setViewportSize({ width: 390, height: 844 })
    await page.waitForTimeout(800)
    await assertNoPageScroll(page, 'mobile')
    await assertCorridorFits(page, zones, 'mobile')
    const mainText = await page.locator('[data-main-screen]').innerText()
    assertNoBanned(mainText, 'mobile main screen')
    assert.ok(await page.getByTestId('risk-panel').isVisible(), 'mobile risk panel is hidden')
    assert.ok(await page.getByTestId('side-panel').isVisible(), 'mobile legend panel is hidden')
    assert.ok(await page.getByTestId('open-reliability').isVisible(), 'mobile evidence trigger is hidden')
    assert.ok(await page.locator('.leaflet-control-attribution').isVisible(), 'mobile attribution is hidden')
    const attribution = await page.locator('.leaflet-control-attribution').boundingBox()
    assert.ok(attribution.y + attribution.height <= 844, 'mobile attribution is below the viewport')
    await page.screenshot({ path: join(SHOT_DIR, 'mobile-risk.png') })

    await page.getByRole('button', { name: 'Zoom out' }).click()
    await page.getByRole('button', { name: 'Zoom out' }).click()
    await page.waitForTimeout(300)
    const locked = await mapView(page)
    assert.ok(locked.zoom >= locked.minZoom, 'mobile zoom escaped the minimum zoom')
    assert.ok(pointInRing(locked.center, zones.corridor.features[0].geometry.coordinates[0]))

    await page.getByTestId('open-tested').click()
    const tested = page.getByTestId('panel-tested')
    await tested.waitFor({ state: 'visible' })
    await page.screenshot({ path: join(SHOT_DIR, 'mobile-tested.png') })
    await page.keyboard.press('Escape')
    await tested.waitFor({ state: 'hidden' })
    assert.equal(
      await page.evaluate(() => document.activeElement?.getAttribute('data-testid')),
      'open-tested',
      'mobile focus did not return to the evidence trigger',
    )
    assert.deepEqual(errors, [], `responsive browser errors:\n${errors.join('\n')}`)
  } finally {
    await context.close()
  }
}

async function pinchProof(browser, zones) {
  const context = await browser.newContext({ viewport: { width: 1024, height: 768 }, hasTouch: true })
  const page = await context.newPage()
  try {
    await page.goto(UI_URL, { waitUntil: 'domcontentloaded' })
    await page.getByTestId('title').waitFor({ timeout: 15000 })
    await waitForMap(page)
    await page.evaluate(() => window.__riverMap.setZoom(window.__riverMap.getMinZoom() + 1))
    const client = await context.newCDPSession(page)
    await client.send('Input.synthesizePinchGesture', {
      x: 512,
      y: 384,
      scaleFactor: 0.5,
      relativeSpeed: 800,
      gestureSourceType: 'touch',
    })
    await page.waitForTimeout(700)
    const locked = await mapView(page)
    assert.ok(locked.zoom >= locked.minZoom, 'pinch escaped the minimum zoom')
    assert.ok(pointInRing(locked.center, zones.corridor.features[0].geometry.coordinates[0]))
  } finally {
    await context.close()
  }
}

async function offlineProof(browser, zones) {
  const context = await browser.newContext({ viewport: { width: 1024, height: 768 } })
  const page = await context.newPage()
  const pageErrors = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.route('**/server.arcgisonline.com/**', (route) => route.abort())
  try {
    await page.goto(UI_URL, { waitUntil: 'domcontentloaded' })
    await page.getByTestId('title').waitFor({ timeout: 15000 })
    await page.getByTestId('risk-count-erosion').waitFor({ timeout: 15000 })
    await waitForMap(page)
    const banner = page.getByTestId('satellite-message')
    await banner.waitFor({ timeout: 15000 })
    assert.equal(await banner.innerText(), zones.basemap.fallback_message)
    assert.equal((await mapView(page)).state.offline, true)
    assert.equal(await page.locator('.leaflet-risk-pane-pane path').count() > 0, true, 'risk zones disappeared offline')
    await page.screenshot({ path: join(SHOT_DIR, 'tablet-offline.png') })
    await page.getByTestId('basemap-street').click()
    await page.waitForFunction(() => window.__riverState.offline === false, null, { timeout: 5000 })
    await banner.waitFor({ state: 'detached', timeout: 5000 })
    assert.deepEqual(pageErrors, [], `offline page errors:\n${pageErrors.join('\n')}`)
  } finally {
    await context.close()
  }
}

async function derivedYearProof(browser) {
  const context = await browser.newContext({ viewport: { width: 1024, height: 768 } })
  const page = await context.newPage()
  await page.route('**/api/zones/', async (route) => {
    const response = await route.fetch()
    const data = await response.json()
    data.starting_year = 2022
    data.years = [1988, 2026]
    await route.fulfill({ response, json: data })
  })
  try {
    await page.goto(UI_URL, { waitUntil: 'domcontentloaded' })
    await page.getByTestId('title').waitFor({ timeout: 15000 })
    await page.getByTestId('risk-count-erosion').waitFor({ timeout: 15000 })
    await waitForMap(page)
    assert.equal(await page.getByTestId('view-observed').innerText(), 'Observed years')
    await page.getByTestId('view-past').click()
    await page.waitForFunction(() => window.__riverState.view === 'past', null, { timeout: 5000 })
    assert.match(await page.getByTestId('side-panel').innerText(), /2022 edge/)
    await page.getByTestId('layers-button').click()
    assert.match(await page.getByTestId('layers-panel').innerText(), /2022 edge/)
    await page.keyboard.press('Escape')
    await page.getByTestId('open-tested').click()
    await page.getByTestId('panel-tested').waitFor({ state: 'visible' })
    assert.match(await page.getByTestId('panel-tested').innerText(), /POST-2022 EXTRACTION/i)
    await page.keyboard.press('Escape')
  } finally {
    await context.close()
  }
}

async function main() {
  mkdirSync(SHOT_DIR, { recursive: true })
  const health = await getJson('/api/health/')
  assert.equal(health.status, 'ok')
  assert.equal(health.frozen, true)
  const zones = await getJson('/api/zones/')
  const risk = await getJson('/api/forecast/risk-zones/?year=2026')
  const metrics = await getJson('/api/forecast/metrics/')
  checkZoneRules(zones)
  checkRiskRules(risk)
  assert.equal(metrics.n_good_pairs, 398)
  assert.deepEqual(metrics.test_years, [2024, 2025, 2026])
  assert.equal(Number(metrics.models.random_forest.mae_m.toFixed(2)), 9.15)
  assert.equal(Number(metrics.models.zero.mae_m.toFixed(2)), 5.82)
  assert.equal(metrics.event_audit.erosion.captured, 3)
  assert.equal(metrics.event_audit.erosion.n, 22)
  assert.equal(metrics.event_audit.accretion.captured, 2)
  assert.equal(metrics.event_audit.accretion.n, 42)

  const executablePath = installedChromium()
  assert.ok(executablePath, 'No Chromium binary found. Set CHROMIUM_PATH or run npx playwright install chromium.')
  const browser = await chromium.launch({ headless: true, executablePath })
  try {
    const desktop = await desktopProof(browser, zones, risk, metrics)
    await responsiveProof(browser, zones, risk)
    await pinchProof(browser, zones)
    await offlineProof(browser, zones)
    await derivedYearProof(browser)
    const summary = {
      checked_at: new Date().toISOString(),
      ui_url: UI_URL,
      api_status: health.status,
      frozen: health.frozen,
      counts: zones.counts,
      features_with_geometry: zones.features_with_geometry,
      undefined_intervals: zones.undefined_intervals,
      relative_available: zones.relative_available,
      satellite_requests: desktop.satelliteRequests,
      screenshots: readdirSync(SHOT_DIR).filter((name) => name.endsWith('.png')).sort(),
    }
    writeFileSync(join(SHOT_DIR, 'ui-check.json'), `${JSON.stringify(summary, null, 2)}\n`)
    console.log('ui-v2 proof ok')
    console.log(`screenshots: ${SHOT_DIR}`)
  } finally {
    await browser.close()
  }
}

main().catch((error) => {
  console.error(`ui-v2 proof failed: ${error.message}`)
  console.error('Start Django on 127.0.0.1:8000 and Vite on localhost:5173, and provide Chrome/Chromium.')
  process.exitCode = 1
})
