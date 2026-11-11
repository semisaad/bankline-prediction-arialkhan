import { area, shortHash, titleCase, utc } from '../format.js'

export default function QualityPanel({ quality }) {
  if (!quality) {
    return <section className="card panel"><p className="muted">Loading data quality…</p></section>
  }
  const inventory = quality.inventory || {}
  const qa = quality.historical_qa || {}
  const freeze = quality.freeze || {}
  const tests = quality.test_extraction || []

  const checks = [
    ['Mask recreation', qa.all_recomputed_masks_match],
    ['Polygon validity', qa.all_polygons_valid],
    ['River inside water', qa.all_selected_subset_of_valid_water],
    ['Excluded layer disjoint', qa.all_excluded_disjoint],
    ['Excluded inside water', qa.all_excluded_subset_of_water],
    ['River + excluded = water', qa.all_river_plus_excluded_equals_water],
  ]

  return (
    <section className="card panel" id="quality">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Data quality</p>
          <h2>What to trust</h2>
        </div>
        <span className={`status-chip ${freeze.ok ? 'good' : 'bad'}`}>
          {freeze.ok ? 'Provenance verified' : 'Provenance issue'}
        </span>
      </div>

      <div className="quality-grid">
        <div>
          <h3>Freeze</h3>
          <dl className="stat-list tight">
            <div><dt>Manifest</dt><dd>{freeze.ok ? 'All hashes match' : freeze.errors?.join(', ')}</dd></div>
            <div><dt>READY hash</dt><dd className="mono" title={freeze.ready_sha256}>{shortHash(freeze.ready_sha256, 18)}</dd></div>
            <div><dt>Frozen</dt><dd>{utc(freeze.frozen_utc)}</dd></div>
            <div><dt>Forecast years</dt><dd>{freeze.forecast_years?.join(', ')}</dd></div>
          </dl>
        </div>
        <div>
          <h3>Input audit</h3>
          <dl className="stat-list tight">
            <div><dt>GeoTIFFs</dt><dd>{inventory.file_count}</dd></div>
            <div><dt>Missing years</dt><dd>{inventory.missing_years?.join(', ') || 'None'}</dd></div>
            <div><dt>Historical pairs</dt><dd>{qa.n_pairs}</dd></div>
            <div><dt>Flagged pairs</dt><dd>{qa.n_flagged_pairs}</dd></div>
            <div><dt>Polygon repair years</dt><dd>{qa.polygon_repair_years?.length ?? 0}</dd></div>
          </dl>
        </div>
      </div>

      <div className="check-grid">
        {checks.map(([label, ok]) => (
          <div className={`check ${ok ? 'ok' : 'fail'}`} key={label}>
            <span className="check-dot" />
            <span>{label}</span>
          </div>
        ))}
      </div>

      <h3>Post-freeze test extraction</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Year</th><th>Selected area</th><th>Parts</th><th>Fallback</th><th>Repair</th></tr>
          </thead>
          <tbody>
            {tests.map((row) => (
              <tr key={row.year}>
                <td>{row.year}</td>
                <td>{area(row.selected_river_area_m2)}</td>
                <td>{row.selected_component_count}</td>
                <td>{row.anchor_fallback_used ? 'Yes' : 'No'}</td>
                <td>{row.polygon_repair_applied ? 'Yes' : 'No'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="callout neutral">
        <strong>Assumptions</strong>
        <ul>
          {quality.warnings?.map((text) => <li key={text}>{text}</li>)}
        </ul>
      </div>

      <details className="limitations">
        <summary>Flagged interval pairs ({qa.flagged_pairs?.length ?? 0})</summary>
        <ul>
          {qa.flagged_pairs?.map((pair) => (
            <li key={`${pair.from_year}-${pair.to_year}`}>
              {pair.from_year} → {pair.to_year}: {pair.flags?.map(titleCase).join(', ')}
              {pair.best_iou_shift && ` · best shift (${pair.best_iou_shift.dx_px}, ${pair.best_iou_shift.dy_px}) px`}
            </li>
          ))}
        </ul>
      </details>
    </section>
  )
}
