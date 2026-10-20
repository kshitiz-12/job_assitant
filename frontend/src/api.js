// Empty in local dev: Vite proxies /api to the API on port 8000.
// On Vercel this is the Render origin, with no trailing slash.
const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

export function apiUrl(path) {
  return `${API}${path}`;
}
