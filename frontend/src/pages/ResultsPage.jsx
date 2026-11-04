import { useLocation, useNavigate } from 'react-router-dom';
import ClaimReport from '../components/ClaimReport';

export default function ResultsPage() {
  const { state } = useLocation();
  const navigate = useNavigate();

  const result = state?.result;
  const imageUrl = state?.imageUrl;

  // Guard: if navigated to directly without data, go back to upload
  if (!result) {
    return (
      <main className="page results-page">
        <p>No results found.</p>
        <button className="btn btn--secondary" onClick={() => navigate('/owner')}>
          Go back
        </button>
      </main>
    );
  }

  return (
    <main className="page results-page">
      <h1 className="results-page__title">Your claim report</h1>

      <ClaimReport result={result} localPreview={imageUrl} />

      <button className="btn btn--secondary" onClick={() => navigate('/owner')}>
        File another claim
      </button>
    </main>
  );
}
