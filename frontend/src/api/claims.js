/**
 * API client for claim processing endpoints.
 */
import { API_BASE } from './config';

async function handle(response, fallbackMsg) {
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || fallbackMsg);
  }
  return response.json();
}

/**
 * Fetch a paginated list of claims, optionally filtered by status.
 * @param {Object} opts
 * @param {'pending'|'approved'|'rejected'} [opts.status]
 * @param {number} [opts.page]
 * @param {number} [opts.pageSize]
 */
export async function listClaims({ status, page = 1, pageSize = 20 } = {}) {
  const params = new URLSearchParams({ page, page_size: pageSize });
  if (status) params.append('status', status);

  const response = await fetch(`${API_BASE}/api/claims?${params}`);
  return handle(response, 'Failed to load claims.');
}

/** Fetch a single claim by ID. */
export async function getClaim(claimId) {
  const response = await fetch(`${API_BASE}/api/claims/${claimId}`);
  return handle(response, 'Failed to load claim.');
}

/**
 * Save processor corrections to a claim.
 * Only send fields that changed.
 * @param {string} claimId
 * @param {Object} corrections {color, model, damages, repair_cost_estimate, update_reason}
 *   update_reason is required by the backend whenever a field actually changes.
 */
export async function reviewClaim(claimId, corrections) {
  const response = await fetch(`${API_BASE}/api/claims/${claimId}/review`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(corrections),
  });
  return handle(response, 'Failed to save corrections.');
}

/** Approve a claim. */
export async function approveClaim(claimId, { processedBy, reason } = {}) {
  const response = await fetch(`${API_BASE}/api/claims/${claimId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ processed_by: processedBy, reason }),
  });
  return handle(response, 'Failed to approve claim.');
}

/** Reject a claim. */
export async function rejectClaim(claimId, { processedBy, reason } = {}) {
  const response = await fetch(`${API_BASE}/api/claims/${claimId}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ processed_by: processedBy, reason }),
  });
  return handle(response, 'Failed to reject claim.');
}
