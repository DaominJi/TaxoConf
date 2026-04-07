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

/**
 * POST with SSE streaming. Calls onProgress for each progress event,
 * returns the final result data.
 *
 * @param {string} path - API path (e.g., "/oral/run-stream")
 * @param {object} payload - POST body
 * @param {function} onProgress - Called with {step, total, msg} for each progress event
 * @returns {Promise<object>} The final response data
 */
export async function apiPostStream(path, payload, onProgress) {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Request failed (${res.status}): ${text.slice(0, 200)}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Process complete SSE lines
    const lines = buffer.split("\n");
    buffer = lines.pop() || ""; // Keep incomplete last line

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        const event = JSON.parse(line.slice(6));
        if (event.type === "progress" && onProgress) {
          onProgress(event);
        } else if (event.type === "result") {
          finalResult = event.data;
        } else if (event.type === "error") {
          throw new Error(event.error || "Backend error");
        }
      } catch (e) {
        if (e.message && !e.message.startsWith("Unexpected")) throw e;
        // Ignore JSON parse errors on partial data
      }
    }
  }

  if (!finalResult) {
    throw new Error("Stream ended without a result.");
  }
  return finalResult;
}
