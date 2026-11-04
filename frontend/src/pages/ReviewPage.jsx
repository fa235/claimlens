import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getClaim,
  reviewClaim,
  approveClaim,
  rejectClaim,
} from '../api/claims';

const SEVERITY_OPTIONS = ['low', 'medium', 'high'];

// Statuses that require a per-line note before the claim can be saved/decided.
const NOTE_REQUIRED = new Set(['modified', 'declined', 'added']);

function formatUSD(n) {
  const v = Number(n) || 0;
  return `$${v.toLocaleString()}`;
}

function newItem() {
  return {
    type: '',
    severity: 'medium',
    location: '',
    cost: 0,
    status: 'added',
    note: '',
  };
}

export default function ReviewPage() {
  const { claimId } = useParams();
  const navigate = useNavigate();

  const [claim, setClaim] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const [color, setColor] = useState('');
  const [model, setModel] = useState('');
  const [damages, setDamages] = useState([]);
  const [finalNote, setFinalNote] = useState('');
  const [decisionReason, setDecisionReason] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getClaim(claimId);
      setClaim(data);
      setColor(data.color || '');
      setModel(data.model || '');
      // Normalize each damage to the line-item shape the UI edits.
      setDamages(
        (data.damages || []).map((d) => ({
          type: d.type || '',
          severity: d.severity || 'medium',
          location: d.location || '',
          cost: Number(d.cost) || 0,
          status: d.status || 'pending',
          note: d.note || '',
        }))
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [claimId]);

  useEffect(() => { load(); }, [load]);

  // ── Line-item handlers ──────────────────────────────────────
  const setItem = (idx, patch) =>
    setDamages((list) => list.map((d, i) => (i === idx ? { ...d, ...patch } : d)));

  // Editing a field on an auto-detected line marks it "modified".
  const editField = (idx, key, value) =>
    setDamages((list) =>
      list.map((d, i) => {
        if (i !== idx) return d;
        const next = { ...d, [key]: value };
        if (d.status !== 'added') next.status = 'modified';
        return next;
      })
    );

  const setStatus = (idx, status) => setItem(idx, { status });
  const setNote = (idx, note) => setItem(idx, { note });
  const addItem = () => setDamages((list) => [...list, newItem()]);
  const removeItem = (idx) =>
    setDamages((list) => list.filter((_, i) => i !== idx));

  // ── Derived ─────────────────────────────────────────────────
  const total = damages
    .filter((d) => d.status !== 'declined')
    .reduce((sum, d) => sum + (Number(d.cost) || 0), 0);

  // Any modified/declined/added line missing its note?
  const missingNotes = damages.some(
    (d) => NOTE_REQUIRED.has(d.status) && !String(d.note || '').trim()
  );

  const isProcessed = claim && claim.status !== 'pending';

  // ── Actions ─────────────────────────────────────────────────
  const persist = async () => {
    const payload = {
      color,
      model,
      damages: damages.map((d) => ({
        type: d.type,
        severity: d.severity,
        location: d.location,
        cost: Number(d.cost) || 0,
        status: d.status,
        note: d.note || null,
      })),
      final_note: finalNote.trim() || undefined,
    };
    const updated = await reviewClaim(claimId, payload);
    setClaim(updated);
    return updated;
  };

  const saveReview = async () => {
    setSaving(true);
    setError(null);
    try {
      await persist();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const decide = async (action) => {
    setSaving(true);
    setError(null);
    try {
      await persist();
      const fn = action === 'approve' ? approveClaim : rejectClaim;
      await fn(claimId, { reason: decisionReason || undefined });
      navigate('/processor');
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  if (loading) return <main className="page"><p>Loading claim…</p></main>;
  if (error && !claim) return (
    <main className="page">
      <p className="review-page__error">{error}</p>
      <button className="btn btn--secondary" onClick={() => navigate('/processor')}>
        Back to queue
      </button>
    </main>
  );

  return (
    <main className="page review-page">
      <header className="review-page__header">
        <button className="review-page__back" onClick={() => navigate('/processor')}>
          ← Queue
        </button>
        <h1 className="review-page__title">Review Claim</h1>
        <span className={`review-page__status review-page__status--${claim.status}`}>
          {claim.status}
        </span>
      </header>

      <div className="review-page__layout">
        {/* Left: image */}
        <section className="review-page__image-section">
          <img src={claim.image_url} alt="Claim" className="review-page__image" />
          {claim.damage_confidence != null && (
            <p className="review-page__confidence">
              Model confidence: {(claim.damage_confidence * 100).toFixed(0)}%
            </p>
          )}
        </section>

        {/* Right: review form */}
        <section className="review-page__form">
          <label className="field">
            <span className="field__label">Car Color</span>
            <input className="field__input" value={color}
              onChange={(e) => setColor(e.target.value)} disabled={isProcessed} />
          </label>

          <label className="field">
            <span className="field__label">Car Model</span>
            <input className="field__input" value={model}
              onChange={(e) => setModel(e.target.value)} disabled={isProcessed} />
          </label>

          {/* ── Line-item damage review ───────────────────────── */}
          <div className="field">
            <span className="field__label">Damage Items &amp; Repair Cost</span>

            {damages.length === 0 && (
              <p className="damage-list__empty">No damage items.</p>
            )}

            <ul className="line-items">
              {damages.map((d, idx) => {
                const noteNeeded = NOTE_REQUIRED.has(d.status) && !String(d.note || '').trim();
                return (
                  <li
                    key={idx}
                    className={`line-item line-item--${d.status}`}
                  >
                    <div className="line-item__fields">
                      <input
                        className="line-item__type"
                        placeholder="Type (e.g. dent)"
                        value={d.type}
                        onChange={(e) => editField(idx, 'type', e.target.value)}
                        disabled={isProcessed}
                      />
                      <select
                        className="line-item__severity"
                        value={d.severity}
                        onChange={(e) => editField(idx, 'severity', e.target.value)}
                        disabled={isProcessed}
                      >
                        {SEVERITY_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                      <input
                        className="line-item__location"
                        placeholder="Location"
                        value={d.location}
                        onChange={(e) => editField(idx, 'location', e.target.value)}
                        disabled={isProcessed}
                      />
                      <div className="line-item__cost">
                        <span className="line-item__cost-prefix">$</span>
                        <input
                          type="number"
                          min="0"
                          className="line-item__cost-input"
                          value={d.cost}
                          onChange={(e) => editField(idx, 'cost', Number(e.target.value))}
                          disabled={isProcessed || d.status === 'declined'}
                        />
                      </div>
                    </div>

                    {!isProcessed && (
                      <div className="line-item__actions">
                        <button
                          type="button"
                          className={`line-item__btn line-item__btn--approve ${d.status === 'approved' ? 'is-active' : ''}`}
                          onClick={() => setStatus(idx, 'approved')}
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          className={`line-item__btn line-item__btn--modify ${d.status === 'modified' ? 'is-active' : ''}`}
                          onClick={() => setStatus(idx, 'modified')}
                        >
                          Modify
                        </button>
                        <button
                          type="button"
                          className={`line-item__btn line-item__btn--decline ${d.status === 'declined' ? 'is-active' : ''}`}
                          onClick={() => setStatus(idx, 'declined')}
                        >
                          Decline
                        </button>
                        {d.status === 'added' && (
                          <span className="line-item__tag">added</span>
                        )}
                        <button
                          type="button"
                          className="line-item__remove"
                          onClick={() => removeItem(idx)}
                          aria-label="Remove item"
                        >
                          ✕
                        </button>
                      </div>
                    )}

                    {/* Per-line note — required for modified/declined/added */}
                    {!isProcessed && NOTE_REQUIRED.has(d.status) && (
                      <input
                        className={`line-item__note ${noteNeeded ? 'line-item__note--error' : ''}`}
                        placeholder={
                          d.status === 'declined'
                            ? 'Why is this declined? (e.g. no such damage)'
                            : d.status === 'added'
                            ? 'Why add this item?'
                            : 'Why modified?'
                        }
                        value={d.note || ''}
                        onChange={(e) => setNote(idx, e.target.value)}
                      />
                    )}

                    {/* Read-only note display after processing */}
                    {isProcessed && d.note && (
                      <p className="line-item__note-ro">
                        <strong>{d.status}:</strong> {d.note}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>

            {!isProcessed && (
              <button className="btn btn--ghost" onClick={addItem}>
                + Add damage not detected
              </button>
            )}
          </div>

          {/* Running total */}
          <div className="review-page__total">
            <span>Total repair cost (excludes declined)</span>
            <strong>{formatUSD(total)}</strong>
          </div>

          {error && <p className="review-page__error" role="alert">{error}</p>}

          {/* Decision controls */}
          {isProcessed ? (
            <div className="review-page__decided">
              <p>
                This claim was <strong>{claim.status}</strong>
                {claim.decision_reason && ` — ${claim.decision_reason}`}
              </p>
            </div>
          ) : (
            <>
              <label className="field">
                <span className="field__label">Final note</span>
                <textarea
                  className="field__input"
                  rows={2}
                  value={finalNote}
                  onChange={(e) => setFinalNote(e.target.value)}
                  placeholder="Overall note on this claim (optional)"
                />
              </label>

              <label className="field">
                <span className="field__label">Decision note (optional)</span>
                <input
                  className="field__input"
                  value={decisionReason}
                  onChange={(e) => setDecisionReason(e.target.value)}
                  placeholder="Reason for approval/rejection"
                />
              </label>

              {missingNotes && (
                <p className="field__hint field__hint--error">
                  Every modified, declined, or added item needs a note before you can save or decide.
                </p>
              )}

              <div className="review-page__actions">
                <button className="btn btn--secondary" onClick={saveReview}
                  disabled={saving || missingNotes}>
                  Save Review
                </button>
                <button className="btn btn--danger" onClick={() => decide('reject')}
                  disabled={saving || missingNotes}>
                  Reject Claim
                </button>
                <button className="btn btn--primary" onClick={() => decide('approve')}
                  disabled={saving || missingNotes}>
                  Approve Claim
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
