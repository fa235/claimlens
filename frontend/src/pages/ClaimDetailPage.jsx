import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ClaimReport from '../components/ClaimReport';
import { getClaim } from '../api/claims';

/**
 * Owner-facing claim detail page. Fetches a single claim by id (from the
 * claims table link) and renders the same report used after upload.
 */
export default function ClaimDetailPage() {
  const { claimId } = useParams();
  const navigate = useNavigate();

  const [claim, setClaim] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getClaim(claimId)
      .then((data) => { if (!cancelled) setClaim(data); })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [claimId]);

  return (
    <main className="page results-page">
      <h1 className="results-page__title">Claim report</h1>

      {loading && <p className="queue-page__msg">Loading claim…</p>}
      {error && <p className="upload-page__error" role="alert">{error}</p>}

      {!loading && !error && claim && <ClaimReport result={claim} />}

      <button className="btn btn--secondary" onClick={() => navigate('/owner')}>
        ← Back to claims
      </button>
    </main>
  );
}
