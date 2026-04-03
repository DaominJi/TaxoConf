/**
 * settings.js
 *
 * Settings page logic: provider/model selection, API key management,
 * load/save settings, and LLM connection testing.
 */

import { API_BASE } from "../api.js";
import { showToast } from "../toast.js";

/* ═══════════════════ Constants ═══════════════════ */

export const PROVIDER_KEY_PLACEHOLDERS = {
  openai:    "sk-...",
  google:    "AI...",
  anthropic: "sk-ant-...",
  xai:       "xai-...",
};

export const PROVIDER_MODELS = {
  openai:    ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "gpt-5", "gpt-5.4", "gpt-5.4-nano", "o3-mini", "o3", "o4-mini"],
  google:    ["gemini-2.0-flash", "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-3-flash-preview", "gemini-3.1-flash-lite-preview", "gemini-3.1-pro-preview"],
  anthropic: ["claude-sonnet-4-6", "claude-sonnet-4-5", "claude-sonnet-4", "claude-opus-4-6", "claude-opus-4-5", "claude-haiku-4-5"],
  xai:       ["grok-3-mini", "grok-3", "grok-4", "grok-4-fast"],
};

/* Tracks which providers have API keys configured (populated by loadSettings) */
export let _apiKeysStatus = {};

/* ═══════════════════ Internal helpers ═══════════════════ */

function _populateModelSelect(models, keepValue) {
  const sel = document.getElementById("settingsModel");
  const prev = keepValue || sel.value;
  sel.innerHTML = "";
  models.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    sel.appendChild(opt);
  });
  if (models.includes(prev)) {
    sel.value = prev;
  }
}

/* ═══════════════════ Public functions ═══════════════════ */

export async function updateModelDropdown(keepValue) {
  const prov = document.getElementById("settingsProvider").value;
  updateKeyStatus();
  updateKeyPlaceholder();

  /* Try fetching live models from the provider API */
  try {
    const res = await fetch(`${API_BASE}/models?provider=${prov}`);
    const data = await res.json();
    if (data.success && data.models && data.models.length > 0) {
      _populateModelSelect(data.models, keepValue);
      return;
    }
  } catch (_) {
    /* fall through to hardcoded list */
  }

  /* Fallback: use hardcoded list */
  _populateModelSelect(PROVIDER_MODELS[prov] || [], keepValue);
}

export function updateKeyStatus() {
  const prov = document.getElementById("settingsProvider").value;
  const el = document.getElementById("settingsKeyStatus");
  const hasKey = _apiKeysStatus[prov];
  if (hasKey) {
    el.textContent = "(Key configured)";
    el.style.color = "var(--accent)";
  } else {
    el.textContent = "(No key)";
    el.style.color = "var(--danger, #c44)";
  }
}

export function updateKeyPlaceholder() {
  const prov = document.getElementById("settingsProvider").value;
  document.getElementById("settingsApiKey").placeholder = PROVIDER_KEY_PLACEHOLDERS[prov] || "API key...";
}

export function toggleManualKeyRow() {
  const manual = document.querySelector('input[name="apiKeySource"][value="manual"]').checked;
  document.getElementById("settingsManualKeyRow").style.display = manual ? "block" : "none";
}

export async function loadSettings() {
  try {
    const res = await fetch(`${API_BASE}/settings`);
    const data = await res.json();
    const s = data.result || data;
    if (s.llm) {
      if (s.llm.api_keys_status) _apiKeysStatus = s.llm.api_keys_status;
      document.getElementById("settingsProvider").value = s.llm.provider || "openai";
      await updateModelDropdown(s.llm.model || "");
      const src = s.llm.api_key_source || "environment";
      document.querySelectorAll('input[name="apiKeySource"]').forEach((r) => (r.checked = r.value === src));
      toggleManualKeyRow();
    }
  } catch (e) {
    console.warn("Failed to load settings:", e);
  }
}

export async function saveSettings() {
  const statusEl = document.getElementById("settingsSaveStatus");
  statusEl.textContent = "Saving...";
  statusEl.style.color = "var(--ink-soft)";

  const apiKeySource = document.querySelector('input[name="apiKeySource"]:checked').value;
  const body = {
    llm: {
      provider: document.getElementById("settingsProvider").value,
      model: document.getElementById("settingsModel").value,
      api_key_source: apiKeySource,
    },
      enable_conflict_avoidance: document.getElementById("settingsPosterConflict").checked,
      proximity: document.getElementById("settingsPosterProximity").checked,
    },
    similarity: {
      method: document.getElementById("settingsSimilarity").value,
      embedding_model: document.getElementById("settingsEmbeddingModel").value,
      cache_enabled: document.getElementById("settingsEmbeddingCache").checked,
    },
  };

  if (apiKeySource === "manual") {
    const key = document.getElementById("settingsApiKey").value.trim();
    if (key) body.llm.api_key = key;
  }

  try {
    const res = await fetch(`${API_BASE}/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    statusEl.textContent = "Saved!";
    statusEl.style.color = "var(--accent)";
    /* Refresh key status if a manual key was just saved */
    if (body.llm.api_key) {
      _apiKeysStatus[body.llm.provider] = true;
      updateKeyStatus();
    }
    showToast("Settings saved successfully.");
  } catch (e) {
    statusEl.textContent = "Save failed: " + e.message;
    statusEl.style.color = "var(--danger)";
  }
  setTimeout(() => {
    statusEl.textContent = "";
  }, 4000);
}

export async function testLLMConnection() {
  const btn = document.getElementById("settingsTestLLMBtn");
  const resultEl = document.getElementById("settingsTestResult");
  btn.disabled = true;
  resultEl.textContent = "Testing...";
  resultEl.style.color = "var(--ink-soft)";

  const apiKeySource = document.querySelector('input[name="apiKeySource"]:checked').value;
  const prov = document.getElementById("settingsProvider").value;
  const body = {
    provider: prov,
    model: document.getElementById("settingsModel").value,
  };
  if (apiKeySource === "manual") {
    const key = document.getElementById("settingsApiKey").value.trim();
    if (!key) {
      resultEl.textContent = "Please enter an API key first.";
      resultEl.style.color = "var(--danger, #c44)";
      btn.disabled = false;
      return;
    }
    body.api_key = key;
  } else if (!_apiKeysStatus[prov]) {
    resultEl.textContent =
      "No API key found. Set "
      + ({ openai: "OPENAI_API_KEY", google: "GOOGLE_API_KEY", anthropic: "ANTHROPIC_API_KEY", xai: "XAI_API_KEY" }[prov] || "the env var")
      + " or enter one manually.";
    resultEl.style.color = "var(--danger, #c44)";
    btn.disabled = false;
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/settings/test-llm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.success) {
      resultEl.textContent = "Connection successful! " + (data.message || "");
      resultEl.style.color = "var(--accent)";
    } else {
      resultEl.textContent = "Failed: " + (data.error || "Unknown error");
      resultEl.style.color = "var(--danger)";
    }
  } catch (e) {
    resultEl.textContent = "Error: " + e.message;
    resultEl.style.color = "var(--danger)";
  }
  btn.disabled = false;
  setTimeout(() => {
    resultEl.textContent = "";
  }, 8000);
}

/* ═══════════════════ Event setup ═══════════════════ */

export function setupSettingsEvents() {
  document.getElementById("settingsProvider").addEventListener("change", () => updateModelDropdown());
  document.querySelectorAll('input[name="apiKeySource"]').forEach((r) => {
    r.addEventListener("change", toggleManualKeyRow);
  });
  document.getElementById("settingsSaveBtn").addEventListener("click", saveSettings);
  document.getElementById("settingsTestLLMBtn").addEventListener("click", testLLMConnection);

  /* Load settings when tab is activated */
  import("../router.js").then(({ onTaskEnter }) => {
    onTaskEnter("settings", loadSettings);
  });
}
