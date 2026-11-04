import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { listClaims } from '../api/claims';

const STATUS_BADGE = {
  pending:  { label: 'Pending',  color: '#f59e0b' },
  approved: { label: 'Approved', color: '#22c55e' },
  rejected: { label: 'Rejected', color: '#ef4444' },
};

function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

/**
 * Read-only table of claims currently in the system, shown under the upload
 * area so an owner can see claims that have been filed.
 *
 * Props:
 *   refreshKey — change this value to trigger a reload (e.g. after a new
 *                claim is filed).
 */
export default function ClaimsTable({ refreshKey }) {
  const [claims, setClaims] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // No status filter → all claims, most recent first (backend orders desc).
      const data = await listClaims({ pageSize: 25 });
      setClaims(data.results || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  return (
    <section className="claims-table-wrap" aria-label="Claims in the system">
      <div className="claims-table-wrap__header">
        <h2 className="claims-table-wrap__title">Claims in the system</h2>
        <button
          className="btn btn--ghost"
          onClick={load}
          disabled={loading}
        >
          {loading ? 'Refreshing…' : '↻ Refresh'}
        </button>
      </div>

      {error && <p className="upload-page__error" role="alert">{error}</p>}

      {!error && !loading && claims.length === 0 && (
        <p className="claims-table__empty">
          No claims filed yet. Upload a photo above to file your first claim.
        </p>
      )}

      {!error && claims.length > 0 && (
        <div className="claims-table__scroll">
          <table className="claims-table">
            <thead>
              <tr>
                <th scope="col">Vehicle</th>
                <th scope="col">Damage</th>
                <th scope="col">Estimate</th>
                <th scope="col">Filed</th>
                <th scope="col">Status</th>
                <th scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {claims.map((claim) => {
                const badge = STATUS_BADGE[claim.status] || { label: claim.status, color: '#94a3b8' };
                const damageCount = (claim.damages || []).length;
                return (
                  <tr key={claim.id} className="claims-table__row">
                    <td>
                      <span className="claims-table__vehicle">
                        {claim.model || 'Unknown vehicle'}
                      </span>
                      {claim.color && (
                        <span className="claims-table__sub">{claim.color}</span>
                      )}
                    </td>
                    <td>{damageCount} area{damageCount !== 1 ? 's' : ''}</td>
                    <td>{claim.repair_cost_estimate || '—'}</td>
                    <td className="claims-table__date">{formatDate(claim.created_at)}</td>
                    <td>
                      <span
                        className="claim-list__badge"
                        style={{ backgroundColor: badge.color }}
                      >
                        {badge.label}
                      </span>
                    </td>
                    <td>
                      <Link
                        to={`/owner/claims/${claim.id}`}
                        className="claims-table__link"
                      >
                        View →
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
