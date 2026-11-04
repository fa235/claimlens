import { useState, useEffect } from 'react';

/**
 * Staged progress indicator shown while a claim is being filed.
 *
 * The backend /api/analyze is a single request, so these stages are
 * indicative (they mirror the real pipeline order) rather than driven by
 * live backend events. The component auto-advances through the stages while
 * `active` is true, but parks on the last stage until the parent signals the
 * request actually finished via the `done` prop — so it never claims "filed"
 * before the server responds.
 *
 * Props:
 *   active — true while the request is in flight (drives the animation)
 *   done   — true once the request has succeeded (jumps to completion)
 */
const STAGES = [
  { key: 'upload',   label: 'Uploading image…' },
  { key: 'detect',   label: 'Detecting damage…' },
  { key: 'estimate', label: 'Estimating repair cost…' },
  { key: 'file',     label: 'Filing claim…' },
];

// How long to linger on each non-final stage (ms) while waiting on the server.
const STAGE_MS = 1100;

export default function ClaimProgress({ active, done }) {
  const [stage, setStage] = useState(0);

  // Auto-advance through stages while the request is running. Stop at the
  // last stage (index STAGES.length - 1) and wait for `done`.
  useEffect(() => {
    if (!active || done) return;
    if (stage >= STAGES.length - 1) return;
    const t = setTimeout(() => setStage((s) => Math.min(s + 1, STAGES.length - 1)), STAGE_MS);
    return () => clearTimeout(t);
  }, [active, done, stage]);

  const isComplete = done;
  // When complete, show all stages done; otherwise fill up to current stage.
  const completedCount = isComplete ? STAGES.length : stage;
  const pct = isComplete
    ? 100
    : Math.round(((stage + 0.5) / STAGES.length) * 100);

  return (
    <div className="claim-progress" role="status" aria-live="polite">
      <div className="claim-progress__bar" aria-hidden="true">
        <div
          className={`claim-progress__fill ${isComplete ? 'claim-progress__fill--done' : ''}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <ol className="claim-progress__stages">
        {STAGES.map((s, idx) => {
          let state = 'pending';
          if (idx < completedCount) state = 'done';
          else if (idx === stage && !isComplete) state = 'active';
          return (
            <li
              key={s.key}
              className={`claim-progress__stage claim-progress__stage--${state}`}
            >
              <span className="claim-progress__marker" aria-hidden="true">
                {state === 'done' ? '✓' : state === 'active' ? '●' : ''}
              </span>
              <span className="claim-progress__label">{s.label}</span>
            </li>
          );
        })}
      </ol>

      <p className="claim-progress__caption">
        {isComplete
          ? 'Claim filed — opening your report…'
          : STAGES[stage].label}
      </p>
    </div>
  );
}
