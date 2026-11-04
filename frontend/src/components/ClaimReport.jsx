import { useState } from 'react';
import ResultCard from './ResultCard';
import DamageList from './DamageList';
import WorkflowStatus from './WorkflowStatus';
import { API_BASE } from '../api/config';

/** Resolve a backend-relative image path (e.g. "/uploads/x.jpg") to a full URL. */
function resolveImage(url) {
  if (!url) return null;
  if (url.startsWith('http') || url.startsWith('blob:')) return url;
  return `${API_BASE}${url}`;
}

/**
 * Presentational claim report: workflow stepper, annotated/original image,
 * repair estimate, and findings. Shared by the post-upload results view and
 * the "open an existing claim" detail view.
 *
 * Props:
 *   result        — claim object (Claim.to_dict shape)
 *   localPreview  — optional object URL to fall back to for the image
 */
export default function ClaimReport({ result, localPreview }) {
  const annotatedUrl = resolveImage(result?.annotated_image_url);
  const originalUrl = resolveImage(result?.image_url) || localPreview;
  const hasAnnotated = Boolean(annotatedUrl);

  const [showAnnotated, setShowAnnotated] = useState(hasAnnotated);
  const displayUrl = showAnnotated && hasAnnotated ? annotatedUrl : originalUrl;

  return (
    <>
      {/* Workflow progression */}
      <WorkflowStatus claim={result} />

      <div className="results-page__layout">
        {/* Left: image (annotated if available) */}
        <section className="results-page__image-section">
          {displayUrl ? (
            <img
              src={displayUrl}
              alt={showAnnotated ? 'Car with detected damage highlighted' : 'Claim photo'}
              className="results-page__image"
            />
          ) : (
            <div className="results-page__image results-page__image--missing">
              Image unavailable
            </div>
          )}

          {hasAnnotated && (
            <div className="results-page__image-toggle" role="group" aria-label="Image view">
              <button
                className={`btn btn--ghost ${showAnnotated ? 'is-active' : ''}`}
                onClick={() => setShowAnnotated(true)}
                aria-pressed={showAnnotated}
              >
                Annotated
              </button>
              <button
                className={`btn btn--ghost ${!showAnnotated ? 'is-active' : ''}`}
                onClick={() => setShowAnnotated(false)}
                aria-pressed={!showAnnotated}
              >
                Original
              </button>
            </div>
          )}

          {result.damage_confidence != null && (
            <p className="results-page__confidence">
              Detection confidence: {(result.damage_confidence * 100).toFixed(0)}%
            </p>
          )}
        </section>

        {/* Right: findings + quote */}
        <section className="results-page__details">
          <div className="results-page__cards">
            <ResultCard label="Car Color" value={result.color} />
            <ResultCard label="Car Model" value={result.model} />
            {result.license_plate && (
              <ResultCard label="License Plate" value={result.license_plate} />
            )}
            <ResultCard
              label="Estimated Repair Cost"
              value={result.repair_cost_estimate}
              highlight
            />
          </div>

          <div className="results-page__damage">
            <h2 className="results-page__section-title">
              Damage &amp; Itemized Cost
            </h2>
            <DamageList damages={result.damages} />
            {Array.isArray(result.damages) && result.damages.length > 0 && (
              <div className="results-page__item-total">
                <span>Total repair cost</span>
                <strong>{result.repair_cost_estimate}</strong>
              </div>
            )}
          </div>

          {result.notes && (
            <div className="results-page__notes">
              <h2 className="results-page__section-title">Notes</h2>
              <p>{result.notes}</p>
            </div>
          )}

          {result.needs_human_review && (
            <div className="results-page__review-flag" role="status">
              <strong>Pending manual review.</strong>{' '}
              {result.review_reason ||
                'This claim needs a human reviewer before it can be approved.'}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
