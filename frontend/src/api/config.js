/**
 * API base URL.
 *
 * Local dev: empty string → relative "/api/..." paths go through the Vite proxy.
 * Production: set VITE_API_BASE_URL to the backend's public URL at build time,
 *             e.g. https://xxxx.us-east-1.awsapprunner.com
 */
export const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
