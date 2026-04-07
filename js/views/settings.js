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
  openrouter: "sk-or-...",
};

/* Fallback models when OpenRouter API is not available (grouped by provider) */
export const PROVIDER_MODELS = {
  openrouter: [
    "openai/gpt-4o", "openai/gpt-4o-mini", "openai/gpt-4.1", "openai/gpt-4.1-mini",
    "openai/gpt-5.4", "openai/o3-mini", "openai/o4-mini",
    "anthropic/claude-sonnet-4-6", "anthropic/claude-sonnet-4-5",
    "anthropic/claude-opus-4-6", "anthropic/claude-haiku-4-5",
    "google/gemini-2.5-flash", "google/gemini-2.5-pro",
    "google/gemini-3-flash-preview", "google/gemini-3.1-pro-preview",
    "x-ai/grok-3", "x-ai/grok-4",
  ],
};

/* Tracks which providers have API keys configured (populated by loadSettings) */
export let _apiKeysStatus = {};

/* Cached pricing data from OpenRouter (model_id -> {prompt, completion}) */
let _modelPricingCache = {};

/* Full model list from last API fetch (for re-filtering without re-fetching) */
let _allFetchedModels = [];
let _allFetchedPricing = [];

/* ═══════════════════ Internal helpers ═══════════════════ */

function _populateModelSelect(models, keepValue, pricingList) {
  const sel = document.getElementById("settingsModel");
  const prev = keepValue || sel.value;
  sel.innerHTML = "";

  // Build pricing lookup if provided
  if (pricingList && Array.isArray(pricingList)) {
    pricingList.forEach((m) => {
      _modelPricingCache[m.id] = {
        prompt: m.prompt_price_per_1m,
        completion: m.completion_price_per_1m,
        name: m.name || m.id,
        context: m.context_length || 0,
      };
    });
  }

  // Group models by provider prefix (e.g., "openai/gpt-4o" → "OpenAI")
  const providerNames = {
    openai: "OpenAI", anthropic: "Anthropic", google: "Google",
    "x-ai": "xAI", meta: "Meta", deepseek: "DeepSeek",
    mistralai: "Mistral", cohere: "Cohere", qwen: "Qwen",
  };
  const groups = {};
  const ungrouped = [];
  models.forEach((m) => {
    const slash = m.indexOf("/");
    if (slash > 0) {
      const prefix = m.substring(0, slash);
      if (!groups[prefix]) groups[prefix] = [];
      groups[prefix].push(m);
    } else {
      ungrouped.push(m);
    }
  });

  // Render grouped models with <optgroup>
  const orderedPrefixes = ["openai", "anthropic", "google", "x-ai", "meta", "deepseek", "mistralai"];
  const renderOpt = (m) => {
    const opt = document.createElement("option");
    opt.value = m;
    const shortName = m.includes("/") ? m.split("/").slice(1).join("/") : m;
    const pricing = _modelPricingCache[m];
    if (pricing && (pricing.prompt > 0 || pricing.completion > 0)) {
      opt.textContent = `${shortName}  ($${pricing.prompt} / $${pricing.completion} per 1M)`;
    } else {
      opt.textContent = shortName;
    }
    return opt;
  };

  // Render in preferred order first, then remaining
  const rendered = new Set();
  orderedPrefixes.forEach((prefix) => {
    if (groups[prefix]) {
      const label = providerNames[prefix] || prefix;
      const grp = document.createElement("optgroup");
      grp.label = label;
      groups[prefix].forEach((m) => grp.appendChild(renderOpt(m)));
      sel.appendChild(grp);
      rendered.add(prefix);
    }
  });
  Object.keys(groups).sort().forEach((prefix) => {
    if (!rendered.has(prefix)) {
      const label = providerNames[prefix] || prefix;
      const grp = document.createElement("optgroup");
      grp.label = label;
      groups[prefix].forEach((m) => grp.appendChild(renderOpt(m)));
      sel.appendChild(grp);
    }
  });
  ungrouped.forEach((m) => sel.appendChild(renderOpt(m)));

  if (models.includes(prev)) {
    sel.value = prev;
  }
  _updatePricingDisplay();
}

function _updatePricingDisplay() {
  const sel = document.getElementById("settingsModel");
  const el = document.getElementById("settingsModelPricing");
  if (!el || !sel) return;
  const modelId = sel.value;
  const p = _modelPricingCache[modelId];
  if (p && (p.prompt > 0 || p.completion > 0)) {
    const ctx = p.context ? ` | Context: ${(p.context / 1000).toFixed(0)}K tokens` : "";
    el.innerHTML = `<strong>Pricing:</strong> $${p.prompt}/1M input, $${p.completion}/1M output${ctx}`;
  } else {
    el.textContent = "";
  }
}

/* ═══════════════════ Public functions ═══════════════════ */

export async function updateModelDropdown(keepValue) {
  updateKeyStatus();
  updateKeyPlaceholder();

  /* Fetch models from OpenRouter API if not cached */
  if (_allFetchedModels.length === 0) {
    try {
      const res = await fetch(`${API_BASE}/models?provider=openrouter`);
      const data = await res.json();
      if (data.success && data.models && data.models.length > 0) {
        _allFetchedModels = data.models;
        _allFetchedPricing = data.models_with_pricing || [];
      }
    } catch (_) { /* fall through to hardcoded list */ }
  }

  const models = _allFetchedModels.length > 0 ? _allFetchedModels : (PROVIDER_MODELS.openrouter || []);
  const pricing = _allFetchedPricing;

  /* Apply provider filter */
  const filter = document.getElementById("settingsProviderFilter")?.value || "";
  const filtered = filter ? models.filter(m => m.startsWith(filter + "/")) : models;
  const filteredPricing = filter ? pricing.filter(m => m.id.startsWith(filter + "/")) : pricing;

  _populateModelSelect(filtered, keepValue, filteredPricing);
}

/** Re-filter models without re-fetching (called when provider filter changes). */
export function filterModels() {
  const current = document.getElementById("settingsModel")?.value || "";
  updateModelDropdown(current);
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
      document.getElementById("settingsProvider").value = "openrouter";
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
      model: document.getElementById("settingsModel").value,
      api_key_source: apiKeySource,
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
  const body = {
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
  } else if (!_apiKeysStatus["openrouter"]) {
    resultEl.textContent = "No API key found. Set OPENROUTER_API_KEY or enter one manually.";
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
  document.getElementById("settingsProviderFilter").addEventListener("change", filterModels);
  document.getElementById("settingsModel").addEventListener("change", _updatePricingDisplay);
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
