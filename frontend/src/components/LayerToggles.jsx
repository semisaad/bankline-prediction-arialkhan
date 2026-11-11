const OPTIONS = [
  ['segments', 'Movement segments'],
  ['forecast', 'Forecast banklines'],
  ['corridor', 'Forecast corridor'],
  ['points', 'Bank points'],
  ['observed', 'Observed test banks'],
]

export default function LayerToggles({ visible, onToggle }) {
  return (
    <section className="card compact">
      <p className="eyebrow">Map layers</p>
      <div className="toggle-list">
        {OPTIONS.map(([key, label]) => (
          <label className="toggle" key={key}>
            <input
              type="checkbox"
              checked={visible[key]}
              onChange={() => onToggle(key)}
            />
            <span>{label}</span>
          </label>
        ))}
      </div>
    </section>
  )
}
