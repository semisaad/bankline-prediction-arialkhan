import { useEffect, useRef } from 'react'
import { COPY } from '../i18n.js'
import { area, m, num } from '../format.js'

function formatCount(value) {
  return Number(value).toLocaleString('en-GB')
}

function yearRange(years) {
  if (!years?.length) return 'not available'
  return years.length === 1 ? String(years[0]) : `${years[0]}–${years.at(-1)}`
}

function plainMetres(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'not available'
  return `${Number(value).toFixed(digits)} m`
}

function PanelDialog({ open, title, testId, onClose, children }) {
  const ref = useRef(null)
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])
  return (
    <dialog
      ref={ref}
      className="sheet"
      data-testid={testId}
      onClose={onClose}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      aria-labelledby={`${testId}-title`}
    >
      <div className="sheet-head">
        <div>
          <p className="eyebrow">{COPY.kicker}</p>
          <h2 id={`${testId}-title`}>{title}</h2>
        </div>
        <button type="button" className="icon-button" onClick={onClose} aria-label={COPY.close}>
          ×
        </button>
      </div>
      <div className="sheet-body">{children}</div>
    </dialog>
  )
}

function Reliability({ zones, metrics, riskData }) {
  const d = zones.diagnostics
  const counts = zones.counts
  const firstYear = zones.years[0]
  const lastYear = zones.latest_year
  const widthStart = d.median_width_by_year[String(firstYear)]
  const widthEnd = d.median_width_by_year[String(lastYear)]
  const rank = d.period_rank
  const rf = metrics?.models?.random_forest
  const zero = metrics?.models?.zero
  return (
    <>
      <p className="lead">{COPY.reliabilityIntro}</p>
      <div className="quiet-box">
        <strong>About the risk zones</strong>
        <p>
          {riskData
            ? `The default risk map shows ${riskData.segment_counts.erosion} outward segments and ${riskData.segment_counts.accretion} inward segments for ${riskData.year}. Low-change segments (${riskData.segment_counts.low_movement}) are counted but not drawn.`
            : 'The risk map uses the fixed model. Low-change segments are counted but not drawn.'}
          {' '}A zone is a scenario area, not an observed measurement or a safety rating.
        </p>
      </div>
      <div className="count-grid" data-testid="zone-counts">
        <div><strong>{counts.strong}</strong><span>{zones.tier_labels.strong}</span></div>
        <div><strong>{counts.moderate}</strong><span>{zones.tier_labels.moderate}</span></div>
        <div><strong>{counts.land_gained}</strong><span>{zones.tier_labels.land_gained}</span></div>
        <div><strong>{counts.no_clear}</strong><span>{zones.tier_labels.no_clear}</span></div>
      </div>
      <p>
        The measured-past layer found no strong or moderate outward stretches in this record. The
        empty classes stay visible rather than being lowered to make a fuller map. Of{' '}
        {zones.total_stretches} stretches, {counts.no_clear} cannot be separated from uncertainty.
      </p>
      <p>
        Each marker compares the same bank over {firstYear}–{lastYear}. A confidence interval is the
        range the method expects to contain the long-term movement. “No clear movement” means that
        range crosses zero or is too wide to call a direction.
      </p>
      <p>
        The opposite bank also moved outward in {d.land_gained_opposite_outward} of the{' '}
        {counts.land_gained} land-gained stretches. That pattern is channel movement, not proof that
        both banks are narrowing.
      </p>
      {widthStart && widthEnd ? (
        <p>
          The typical measured channel width was {plainMetres(widthStart)} in {firstYear} and{' '}
          {plainMetres(widthEnd)} in {lastYear}.
        </p>
      ) : null}
      <p>
        The order of stretches in the early period told us little about the order in the later
        period: rank score {num(rank.spearman, 2)} across {rank.n} stretches. A score close to the top
        means the same order; close to zero means no link. The minimum for showing the “{zones.relative_layer.label}”
        layer was {num(zones.relative_layer.min_spearman, 2)}, so that layer is not shown.
      </p>
      <p>
        The map can measure at most {plainMetres(zones.method.transect_half_m)} to each side of the
        channel centre. Movement beyond that is outside the record.
      </p>
      {rf && zero ? (
        <div className="quiet-box">
          <strong>About the model scenario</strong>
          <p>
            The risk zones use the frozen model. On the test years its average error was {m(rf.mae_m, 2)};
            a no-change answer scored {m(zero.mae_m, 2)}. The zones therefore show possible movement,
            not a validated field measurement, and the no-change answer is the stronger overall test result.
          </p>
        </div>
      ) : null}
    </>
  )
}

function Tested({ zones, metrics, quality }) {
  const audit = metrics?.event_audit
  const tests = quality?.test_extraction || []
  return (
    <>
      <p className="lead">{COPY.testedIntro(metrics?.test_years?.[0], metrics?.test_years?.at(-1))}</p>
      <dl className="facts">
        <div><dt>Good bank pairs compared</dt><dd>{formatCount(metrics?.n_good_pairs)}</dd></div>
        <div><dt>Test years</dt><dd>{yearRange(metrics?.test_years)}</dd></div>
        <div><dt>Measured stretches</dt><dd>{zones.total_stretches}</dd></div>
      </dl>
      {audit ? (
        <p>
          The fixed model marked {audit.erosion.captured} of {audit.erosion.n} large outward
          events, {audit.accretion.captured} of {audit.accretion.n} large inward events, and{' '}
          {audit.low_movement.captured} of {audit.low_movement.n} small movements.
        </p>
      ) : null}
      <p>
        A no-change answer is a serious comparison here. The fixed model’s average error was{' '}
        {m(metrics?.models?.random_forest?.mae_m, 2)}, while no change scored{' '}
        {m(metrics?.models?.zero?.mae_m, 2)} over the same pairs. The risk map shows the model’s
        scenario, but it does not claim that those zones are certain or safer than the measured past.
      </p>
      <h3>Input checks</h3>
      <ul className="check-list">
        <li className={quality?.freeze?.ok ? 'ok' : 'bad'}>
          Frozen data check: {quality?.freeze?.ok ? 'all files match' : 'needs attention'}
        </li>
        <li className={quality?.historical_qa?.all_recomputed_masks_match ? 'ok' : 'bad'}>
          Historical water masks: {quality?.historical_qa?.all_recomputed_masks_match ? 'recomputed' : 'not verified'}
        </li>
        <li className={quality?.historical_qa?.all_polygons_valid ? 'ok' : 'bad'}>
          River polygons: {quality?.historical_qa?.all_polygons_valid ? 'valid' : 'not valid'}
        </li>
        <li className={quality?.inventory?.missing_years?.length ? 'note' : 'ok'}>
          Missing years: {quality?.inventory?.missing_years?.join(', ') || 'none'}
        </li>
      </ul>
      <h3>Post-{zones.starting_year} extraction</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Year</th><th>Selected area</th><th>Parts</th><th>Repair</th></tr>
          </thead>
          <tbody>
            {tests.map((row) => (
              <tr key={row.year}>
                <td>{row.year}</td>
                <td>{area(row.selected_river_area_m2)}</td>
                <td>{row.selected_component_count}</td>
                <td>{row.polygon_repair_applied ? 'Yes' : 'No'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="small-note">
        The test record covers this reach and the test years. It is evidence for this reach, not a
        general guarantee.
      </p>
    </>
  )
}

function Technical({ zones, health, riskData }) {
  const d = zones.diagnostics
  const method = zones.method
  const t = method.thresholds_m
  return (
    <>
      <p className="lead">{COPY.technicalIntro}</p>
      <h3>Bank record</h3>
      <dl className="facts">
        <div><dt>Years used</dt><dd>{zones.years[0]}–{zones.years[1]}</dd></div>
        <div><dt>Missing years skipped</dt><dd>{method.skip_years.join(', ')}</dd></div>
        <div><dt>Transects</dt><dd>{formatCount(d.transect_half_m.n)}</dd></div>
        <div><dt>Half-length each side</dt><dd>{plainMetres(method.transect_half_m)}</dd></div>
        <div><dt>Stretch size</dt><dd>{method.stretch_transects} adjacent transects</dd></div>
        <div><dt>Stretches</dt><dd>{zones.total_stretches}</dd></div>
        <div><dt>Interval</dt><dd>{num(method.confidence * 100, 0)}%</dd></div>
        <div><dt>Resamples</dt><dd>{formatCount(method.bootstrap_replicates)}</dd></div>
        <div><dt>Block length</dt><dd>{method.block_years} years</dd></div>
      </dl>
      <h3>Fixed rule</h3>
      <p>
        Net movement is the Theil–Sen slope over the bank record multiplied by the years it spans.
        The interval comes from the resamples. The tier uses the lower bound unless stated:
      </p>
      <ul className="rule-list">
        <li><strong>{zones.tier_labels.strong}:</strong> lower bound at least {plainMetres(t.strong_lower)}</li>
        <li><strong>{zones.tier_labels.moderate}:</strong> lower bound above zero and at least {plainMetres(t.moderate_lower)}</li>
        <li><strong>{zones.tier_labels.land_gained}:</strong> upper bound at most {plainMetres(t.land_gained_upper)}</li>
        <li><strong>{zones.tier_labels.no_clear}:</strong> everything else</li>
      </ul>
      <h3>Risk-zone display</h3>
      <dl className="facts">
        <div><dt>Scenario year</dt><dd>{riskData?.year ?? 'not loaded'}</dd></div>
        <div><dt>Movement cut-off</dt><dd>{plainMetres(riskData?.threshold_m ?? 15)}</dd></div>
        <div><dt>Outward segments</dt><dd>{riskData?.segment_counts?.erosion ?? 'not loaded'}</dd></div>
        <div><dt>Inward segments</dt><dd>{riskData?.segment_counts?.accretion ?? 'not loaded'}</dd></div>
        <div><dt>Low-change segments</dt><dd>{riskData?.segment_counts?.low_movement ?? 'not loaded'} (not drawn)</dd></div>
        <div><dt>Drawn zone features</dt><dd>{riskData?.zones?.features?.length ?? 'not loaded'}</dd></div>
      </dl>
      <p>
        A segment is coloured when its predicted movement is more than the 15 m low-movement
        tolerance. A zone polygon spans the 2023 bank and the predicted bank; it is generated from
        the frozen segment file at request time and is not a re-run of the model.
      </p>
      <p className="mono-path">forecasts/frozen/segments_YYYY.geojson</p>
      <p className="mono-path">forecasts/frozen/observed_banklines_2023.geojson</p>
      <h3>Checks</h3>
      <dl className="facts">
        <div><dt>Median net movement</dt><dd>{plainMetres(d.net_m.median)}</dd></div>
        <div><dt>Net movement range</dt><dd>{plainMetres(d.net_m.min)} to {plainMetres(d.net_m.max)}</dd></div>
        <div><dt>Median interval width</dt><dd>{plainMetres(d.interval_width_m.median)}</dd></div>
        <div><dt>Undefined intervals</dt><dd>{zones.undefined_intervals} of {zones.total_stretches}</dd></div>
        <div><dt>Early/late rank score</dt><dd>{num(d.period_rank.spearman, 2)}</dd></div>
        <div><dt>Stretches in rank test</dt><dd>{d.period_rank.n}</dd></div>
        <div><dt>Corridor buffer</dt><dd>{plainMetres(method.corridor_buffer_m)}</dd></div>
        <div><dt>Map band width</dt><dd>{plainMetres(method.band_width_m)}</dd></div>
      </dl>
      <h3>Files</h3>
      <p className="mono-path">derived/zones/summary.json</p>
      <p className="mono-path">derived/zones/zones.geojson</p>
      <p className="mono-path">evaluation/metrics.json</p>
      <p className="mono-path">forecasts/frozen/</p>
      <p className="small-note">
        The frozen data check is {health?.frozen ? 'passing' : 'not passing'}. The API and this page
        read the checked files at request time.
      </p>
    </>
  )
}

export default function EvidencePanels({ zones, metrics, quality, health, riskData, openPanel, onClose }) {
  return (
    <>
      <PanelDialog
        open={openPanel === 'reliability'}
        title={COPY.reliability}
        testId="panel-reliability"
        onClose={onClose}
      >
        <Reliability zones={zones} metrics={metrics} riskData={riskData} />
      </PanelDialog>
      <PanelDialog
        open={openPanel === 'tested'}
        title={COPY.tested}
        testId="panel-tested"
        onClose={onClose}
      >
        <Tested zones={zones} metrics={metrics} quality={quality} />
      </PanelDialog>
      <PanelDialog
        open={openPanel === 'technical'}
        title={COPY.technical}
        testId="panel-technical"
        onClose={onClose}
      >
        <Technical zones={zones} health={health} riskData={riskData} />
      </PanelDialog>
    </>
  )
}
