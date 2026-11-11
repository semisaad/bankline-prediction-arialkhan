export default function YearSelector({ years, value, onChange }) {
  return (
    <div className="year-selector" role="group" aria-label="Forecast year">
      {years.map((year) => (
        <button
          key={year}
          type="button"
          className={year === value ? 'year active' : 'year'}
          onClick={() => onChange(year)}
          aria-pressed={year === value}
        >
          <span>{year}</span>
          <small>{year - 2023 === 1 ? '1 year ahead' : `${year - 2023} years ahead`}</small>
        </button>
      ))}
    </div>
  )
}
