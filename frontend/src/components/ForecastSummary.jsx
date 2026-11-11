import { area, m, num, pct } from '../format.js'

const CLASSES = [
  ['erosion', 'Erosion'],
  ['accretion', 'Accretion'],
  ['low_movement', 'Low movement'],
]

export default function ForecastSummary({ summary, year }) {
  const data = summary?.by_year?.[String(year)]
  if (!data) return null
  return (
    <section className="card">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Frozen forecast</p>
          <h2>{year} bank scenario</h2>
        </div>
        <span className="horizon">+{data.horizon_years}y</span>
      </div>

      <div className="class-counts">
        {CLASSES.map(([key, label]) => (
          <div className={`count-box ${key}`} key={key}>
            <span>{label}</span>
            <strong>{data.counts?.[key] ?? 0}</strong>
            <small>of {data.n}</small>
          </div>
        ))}
      </div>

      <dl className="stat-list">
        <div>
          <dt>Mean displacement</dt>
          <dd>{m(data.mean_m, 2)}</dd>
        </div>
        <div>
          <dt>Range</dt>
          <dd>{m(data.min_m)} to {m(data.max_m)}</dd>
        </div>
        <div>
          <dt>Mean absolute</dt>
          <dd>{m(data.mean_abs_m, 2)}</dd>
        </div>
        <div>
          <dt>Mean tree spread</dt>
          <dd>{m(data.mean_ensemble_std_m, 1)}</dd>
        </div>
        <div>
          <dt>Corridor area</dt>
          <dd>{area(data.banklines?.corridor?.area_m2)}</dd>
        </div>
        <div>
          <dt>Usable origins</dt>
          <dd>{pct((data.quality_counts?.forecast ?? 0) / (data.n || 1), 0)}</dd>
        </div>
      </dl>

      {data.quality_counts?.flagged_origin > 0 && (
        <p className="inline-warning">
          {data.quality_counts.flagged_origin} segments start from flagged 2023 banks and are marked in the map.
        </p>
      )}

      <div className="reach-table">
        <div className="reach-row head">
          <span>Reach</span><span>Mean</span><span>Erode</span><span>Build</span>
        </div>
        {Object.entries(data.by_reach || {}).map(([reach, row]) => (
          <div className="reach-row" key={reach}>
            <span>{reach}</span>
            <span>{num(row.mean_m, 2)}</span>
            <span>{row.erosion}</span>
            <span>{row.accretion}</span>
          </div>
        ))}
      </div>
    </section>
  )
}
