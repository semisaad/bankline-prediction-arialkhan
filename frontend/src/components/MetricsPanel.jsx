import { m, num, pct, titleCase } from '../format.js'

function CaptureBar({ label, data }) {
  const rate = data?.capture_rate ?? 0
  return (
    <div className="capture-row">
      <div className="capture-label">
        <span>{label}</span>
        <strong>{data?.captured ?? 0} / {data?.n ?? 0}</strong>
      </div>
      <div className="bar-track" aria-hidden="true">
        <div className={`bar-fill ${label.toLowerCase().replace(' ', '-')}`} style={{ width: `${rate * 100}%` }} />
      </div>
      <small>{pct(rate, 1)} captured · MAE {m(data?.mae_m)}</small>
    </div>
  )
}

export default function MetricsPanel({ metrics, year }) {
  if (!metrics) {
    return <section className="card panel"><p className="muted">Loading retrospective metrics…</p></section>
  }

  const h = metrics.headline || {}
  const rf = metrics.models?.random_forest || {}
  const zero = metrics.models?.zero || {}
  const byYear = rf.by_year || {}
  const current = byYear[String(year)]
  const models = ['random_forest', 'zero', 'persistence', 'trend']

  return (
    <section className="card panel" id="metrics">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Post-freeze test evaluation</p>
          <h2>Retrospective skill</h2>
        </div>
        <span className={`status-chip ${h.frozen_model_improves_mae_over_zero ? 'good' : 'caution'}`}>
          {h.frozen_model_improves_mae_over_zero ? 'Beats baseline' : 'Baseline wins on MAE'}
        </span>
      </div>

      <p className="panel-intro">
        {metrics.n_good_pairs} good bank pairs from {metrics.test_years?.join('–')}.
        The forecast was frozen before these observations were opened.
      </p>

      <div className="metric-cards">
        <div className="metric-card">
          <span>Frozen RF MAE</span>
          <strong>{m(rf.mae_m, 2)}</strong>
          <small>RMSE {m(rf.rmse_m, 2)}</small>
        </div>
        <div className="metric-card">
          <span>Zero-change MAE</span>
          <strong>{m(zero.mae_m, 2)}</strong>
          <small>RMSE {m(zero.rmse_m, 2)}</small>
        </div>
        <div className="metric-card">
          <span>Low-movement F1</span>
          <strong>{num(rf.low_movement_f1, 3)}</strong>
          <small>precision {num(rf.low_movement_precision, 2)} · recall {num(rf.low_movement_recall, 2)}</small>
        </div>
        <div className="metric-card">
          <span>Directional accuracy</span>
          <strong>{pct(rf.directional_accuracy_moving, 1)}</strong>
          <small>only on observed movement &gt; 15 m</small>
        </div>
      </div>

      {!h.frozen_model_improves_mae_over_zero && (
        <div className="callout warning">
          <strong>Read this first</strong>
          <p>
            The frozen random forest is weaker than a zero-change baseline on overall MAE
            ({m(rf.mae_m, 2)} vs {m(zero.mae_m, 2)}). It is kept unchanged because it was selected
            and frozen before test access. It is useful for showing where movement is likely,
            not for precise displacement.
          </p>
        </div>
      )}

      <div className="two-col">
        <div>
          <h3>Event capture</h3>
          <CaptureBar label="Erosion" data={metrics.event_audit?.erosion} />
          <CaptureBar label="Accretion" data={metrics.event_audit?.accretion} />
          <CaptureBar label="Low movement" data={metrics.event_audit?.low_movement} />
          <p className="note">
            A large observed event is “captured” only when the model predicts the same class
            beyond the 15 m tolerance.
          </p>
        </div>
        <div>
          <h3>Selected year: {year}</h3>
          {current ? (
            <dl className="stat-list tight">
              <div><dt>Pairs</dt><dd>{current.n}</dd></div>
              <div><dt>MAE</dt><dd>{m(current.mae_m, 2)}</dd></div>
              <div><dt>RMSE</dt><dd>{m(current.rmse_m, 2)}</dd></div>
              <div><dt>Bias</dt><dd>{m(current.bias_m, 2)}</dd></div>
              <div><dt>Within ±15 m</dt><dd>{pct(current.within_15m, 1)}</dd></div>
              <div><dt>Directional</dt><dd>{pct(current.directional_accuracy_moving, 1)}</dd></div>
            </dl>
          ) : <p className="muted">No year metrics.</p>}
        </div>
      </div>

      <h3>Model comparison on the same 398 pairs</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Model</th><th>MAE</th><th>RMSE</th><th>Low F1</th><th>Directional</th></tr>
          </thead>
          <tbody>
            {models.map((name) => {
              const row = metrics.models?.[name]
              if (!row) return null
              return (
                <tr key={name} className={name === 'random_forest' ? 'selected-row' : ''}>
                  <td>{titleCase(name)}</td>
                  <td>{m(row.mae_m, 2)}</td>
                  <td>{m(row.rmse_m, 2)}</td>
                  <td>{num(row.low_movement_f1, 3)}</td>
                  <td>{pct(row.directional_accuracy_moving, 1)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <h3>Frozen RF by forecast year</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Year</th><th>n</th><th>MAE</th><th>RMSE</th><th>Low F1</th><th>Directional</th></tr>
          </thead>
          <tbody>
            {Object.entries(byYear).map(([y, row]) => (
              <tr key={y} className={String(year) === y ? 'selected-row' : ''}>
                <td>{y}</td>
                <td>{row.n}</td>
                <td>{m(row.mae_m, 2)}</td>
                <td>{m(row.rmse_m, 2)}</td>
                <td>{num(row.low_movement_f1, 3)}</td>
                <td>{pct(row.directional_accuracy_moving, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <details className="limitations">
        <summary>Limitations and interpretation</summary>
        <ul>
          {metrics.limitations?.map((text) => <li key={text}>{text}</li>)}
        </ul>
      </details>
    </section>
  )
}
