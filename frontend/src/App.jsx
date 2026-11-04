import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import UploadPage from './pages/UploadPage';
import ResultsPage from './pages/ResultsPage';
import ClaimDetailPage from './pages/ClaimDetailPage';
import QueuePage from './pages/QueuePage';
import ReviewPage from './pages/ReviewPage';

/**
 * Two independent portals, each under its own base path:
 *
 *   /owner       → Car owner / policyholder portal (upload + results)
 *   /processor   → Insurance claim-processor portal (queue + review)
 *
 * The portals do not link to each other. The root path redirects to the
 * owner portal (the public-facing entry point).
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Root → owner portal */}
        <Route path="/" element={<Navigate to="/owner" replace />} />

        {/* ── Car owner portal ─────────────────────────────── */}
        <Route path="/owner" element={<UploadPage />} />
        <Route path="/owner/results" element={<ResultsPage />} />
        <Route path="/owner/claims/:claimId" element={<ClaimDetailPage />} />

        {/* ── Insurance claim-processor portal ─────────────── */}
        <Route path="/processor" element={<QueuePage />} />
        <Route path="/processor/review/:claimId" element={<ReviewPage />} />

        {/* Fallback → owner portal */}
        <Route path="*" element={<Navigate to="/owner" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
