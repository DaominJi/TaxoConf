/**
 * api.js — API base URL, fetch helpers, and response parsing utilities.
 */

export const API_BASE = window.API_BASE
  || ((window.location.protocol === "file:" || !window.location.hostname)
    ? "http://127.0.0.1:8000/api"
    : `${window.location.origin}/api`);

export async function parseApiResponse(res) {
  const raw = await res.text();
  let data = null;
  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch (_) {
      data = null;
    }
  }

  if (!res.ok) {
    const fallback = raw && raw.trim()
      ? `Request failed (${res.status}): ${raw.trim().slice(0, 180)}`
      : `Request failed (${res.status})`;
    const msg = data && data.error ? data.error : fallback;
    throw new Error(msg);
  }

  if (!data || typeof data !== "object") {
    const suffix = raw && raw.trim()
      ? ` Response body starts with: ${raw.trim().slice(0, 180)}`
      : " Response body was empty.";
    throw new Error(`Backend returned an invalid JSON response.${suffix}`);
  }

  return data;
}

export async function apiFetch(path, options) {
  const url = `${API_BASE}${path}`;
  try {
    return await fetch(url, options);
  } catch (_) {
    throw new Error(
      `Failed to reach ${url}. Check the /api proxy, backend process, and network path between the web server and backend.`
    );
  }
}

export async function apiPost(path, payload) {
  const res = await apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return parseApiResponse(res);
}

export async function apiGet(path) {
  const res = await apiFetch(path);
  return parseApiResponse(res);
}

export function requireApiResult(resp, label) {
  if (!resp || typeof resp !== "object" || !Object.prototype.hasOwnProperty.call(resp, "result")) {
    throw new Error(`${label} returned no result payload.`);
  }
  return resp.result;
}
