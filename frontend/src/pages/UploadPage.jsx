import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import ImageUploader from '../components/ImageUploader';
import ClaimProgress from '../components/ClaimProgress';
import ClaimsTable from '../components/ClaimsTable';
import { analyzeImage } from '../api/analyze';

/** The steps shown to reassure the owner what happens after they submit. */
const NEXT_STEPS = [
  { icon: '📷', label: 'Upload a photo of the damage' },
  { icon: '🔍', label: 'We assess the damage automatically' },
  { icon: '💲', label: 'You get an instant repair estimate' },
  { icon: '📝', label: 'Your claim is filed for review' },
];

export default function UploadPage() {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false); // request in flight
  const [done, setDone] = useState(false);       // request succeeded
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  const handleFileClaim = async () => {
    if (!file) return;
    setError(null);
    setDone(false);
    setLoading(true);

    const localPreview = URL.createObjectURL(file);

    try {
      const result = await analyzeImage(file);

      // Mark the progress as complete, then advance to the full report after
      // a short "Claim filed" beat so the completion is visible.
      setDone(true);
      setTimeout(() => {
        navigate('/owner/results', { state: { result, imageUrl: localPreview } });
      }, 1400);
    } catch (err) {
      setError(err.message);
      setLoading(false);
      setDone(false);
    }
  };

  const inProgress = loading || done;

  return (
    <main className="page upload-page">
      <header className="upload-page__header">
        <h1 className="upload-page__title">ClaimLens</h1>
        <p className="upload-page__tagline">File an accident claim</p>
        <p className="upload-page__subtitle">
          Had an accident? Upload a photo of the damage and we'll start your
          claim right away — no forms, no phone calls.
        </p>
      </header>

      {/* Before submitting: show the "how it works" steps */}
      {!inProgress && (
        <ol className="upload-steps" aria-label="How it works">
          {NEXT_STEPS.map((step, idx) => (
            <li key={idx} className="upload-steps__item">
              <span className="upload-steps__icon" aria-hidden="true">{step.icon}</span>
              <span className="upload-steps__label">{step.label}</span>
            </li>
          ))}
        </ol>
      )}

      {/* The uploader (shows the selected image preview). Kept mounted during
          progress so the owner still sees their photo. */}
      <ImageUploader onFileSelected={setFile} />

      {/* While filing: staged progress bar, right here on the same page */}
      {inProgress && <ClaimProgress active={loading} done={done} />}

      {error && (
        <p className="upload-page__error" role="alert">
          {error}
        </p>
      )}

      {!inProgress && (
        <>
          <button
            className="btn btn--primary"
            onClick={handleFileClaim}
            disabled={!file}
          >
            File Claim
          </button>

          {!file && (
            <p className="upload-page__hint">
              Tip: a clear, well-lit photo of the damaged area gives the best estimate.
            </p>
          )}
        </>
      )}

      {/* Claims currently in the system */}
      <ClaimsTable />
    </main>
  );
}
