import { API_BASE } from './config';

/**
 * Sends a car image to the FastAPI backend for analysis.
 * Returns color, model, damage, and estimated repair cost.
 */
export async function analyzeImage(file) {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(`${API_BASE}/api/analyze`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Analysis failed. Please try again.');
  }

  return response.json();
}
