import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { listClaims } from '../api/claims';

const STATUS_TABS = ['pending', 'approved', 'rejected'];

const STATUS_BADGE = {
  pending:  { label: 'Pending',  color: '#f59e0b' },
  approved: { label: 'Approved', color: '#22c55e' },
  rejected: { label: 'Rejected', color: '#ef4444' },
};

export default function QueuePage() {
  const [status, setStatus] = useState('pending');
  const [claims, setClaims] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listClaims({ status, pageSize: 50 });
      setClaims(data.results);
      setTotal(data.total);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => { load(); }, [load]);

  return (
    <main className="page queue-page">
      <header className="queue-page__header">
        <h1 className="queue-page__title">Claim Queue</h1>
      </header>

      {/* Status tabs */}
      <nav className="queue-tabs" role="tablist">
        {STATUS_TABS.map((s) => (
          <button
            key={s}
            role="tab"
            aria-selected={status === s}
            className={`queue-tabs__tab ${status === s ? 'queue-tabs__tab--active' : ''}`}
            onClick={() => setStatus(s)}
          >
            {STATUS_BADGE[s].label}
          </button>
        ))}
      </nav>

      {loading && <p className="queue-page__msg">Loading claims…</p>}
      {error && <p className="queue-page__error" role="alert">{error}</p>}

      {!loading && !error && claims.length === 0 && (
        <p className="queue-page__msg">No {status} claims.</p>
      )}

      {!loading && !error && claims.length > 0 && (
        <>
          <p className="queue-page__count">{total} {status} claim{total !== 1 ? 's' : ''}</p>
          <ul className="claim-list">
            {claims.map((claim) => (
              <li
                key={claim.id}
                className="claim-list__item"
                onClick={() => navigate(`/processor/review/${claim.id}`)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === 'Enter' && navigate(`/processor/review/${claim.id}`)}
              >
                <img
                  src={claim.image_url}
                  alt="Claim thumbnail"
                  className="claim-list__thumb"
                />
                <div className="claim-list__info">
                  <span className="claim-list__model">{claim.model || 'Unknown vehicle'}</span>
                  <span className="claim-list__meta">
                    {claim.color} · {claim.repair_cost_estimate || 'No estimate'}
                  </span>
                  <span className="claim-list__damages">
                    {(claim.damages || []).length} damage area{(claim.damages || []).length !== 1 ? 's' : ''}
                  </span>
                </div>
                <span
                  className="claim-list__badge"
                  style={{ backgroundColor: STATUS_BADGE[claim.status]?.color || '#94a3b8' }}
                >
                  {STATUS_BADGE[claim.status]?.label || claim.status}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </main>
  );
}
