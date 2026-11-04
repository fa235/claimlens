/**
 * WorkflowStatus — a horizontal stepper showing a claim's progress through
 * the ClaimLens pipeline:
 *
 *   Image Uploaded → Damage Evaluated → Claim Prepared → Claim Approved
 *
 * Each step is derived from the claim data rather than hard-coded, so the
 * same component works right after upload (claim pending) and later in the
 * processor flow (approved/rejected).
 *
 * Step states: 'done' (✓), 'active' (current), 'pending' (upcoming),
 *              'rejected' (final step when the claim was rejected).
 */

function deriveSteps(claim) {
  const hasResult = Boolean(claim);
  // "Evaluated" = the pipeline ran and produced a damage result (even if empty).
  const evaluated = hasResult && claim.damages !== undefined;
  // "Prepared" = a persisted claim exists (it has an id from the backend).
  const prepared = Boolean(claim?.id);
  const status = claim?.status; // 'pending' | 'approved' | 'rejected'

  const steps = [
    { key: 'uploaded', label: 'Image Uploaded', done: hasResult },
    { key: 'evaluated', label: 'Damage Evaluated', done: evaluated },
    { key: 'prepared', label: 'Claim Submitted', done: prepared },
    {
      // Final step is a human gate: a claim processor reviews and decides.
      // The system never auto-approves — it stays "pending" until a processor acts.
      key: 'approved',
      label:
        status === 'approved'
          ? 'Approved by Processor'
          : status === 'rejected'
          ? 'Rejected by Processor'
          : 'Awaiting Processor Review',
      done: status === 'approved',
      rejected: status === 'rejected',
    },
  ];

  // Mark the first not-done, non-rejected step as the active one.
  const firstPending = steps.find((s) => !s.done && !s.rejected);
  return steps.map((s) => {
    let state = 'pending';
    if (s.rejected) state = 'rejected';
    else if (s.done) state = 'done';
    else if (s === firstPending) state = 'active';
    return { ...s, state };
  });
}

const ICON = { done: '✓', active: '●', pending: '', rejected: '✕' };

export default function WorkflowStatus({ claim }) {
  const steps = deriveSteps(claim);

  return (
    <ol className="workflow" aria-label="Claim progress">
      {steps.map((step, idx) => (
        <li
          key={step.key}
          className={`workflow__step workflow__step--${step.state}`}
          aria-current={step.state === 'active' ? 'step' : undefined}
        >
          <span className="workflow__marker" aria-hidden="true">
            {ICON[step.state] || idx + 1}
          </span>
          <span className="workflow__label">{step.label}</span>
          {idx < steps.length - 1 && (
            <span className="workflow__connector" aria-hidden="true" />
          )}
        </li>
      ))}
    </ol>
  );
}
