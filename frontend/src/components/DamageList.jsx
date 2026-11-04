/**
 * Renders a list of detected damage items with severity badges.
 */
const SEVERITY_COLOR = {
  low: '#22c55e',
  medium: '#f59e0b',
  high: '#ef4444',
};

export default function DamageList({ damages }) {
  if (!damages || damages.length === 0) {
    return <p className="damage-list__empty">No damage detected.</p>;
  }

  return (
    <ul className="damage-list">
      {damages.map((item, idx) => {
        const declined = (item.status || '').toLowerCase() === 'declined';
        const cost = Number(item.cost) || 0;
        return (
          <li
            key={idx}
            className={`damage-list__item ${declined ? 'damage-list__item--declined' : ''}`}
          >
            <span className="damage-list__name">{item.type}</span>
            <span
              className="damage-list__badge"
              style={{ backgroundColor: SEVERITY_COLOR[item.severity] || '#94a3b8' }}
            >
              {item.severity}
            </span>
            {item.location && (
              <span className="damage-list__location">{item.location}</span>
            )}
            <span className="damage-list__cost">
              {declined ? 'declined' : cost ? `$${cost.toLocaleString()}` : '—'}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
