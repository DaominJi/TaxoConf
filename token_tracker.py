"""
Token usage and cost tracking for LLM API calls.

Tracks prompt tokens, completion tokens, and estimated costs across all
LLM calls in a session. Supports cost models for OpenAI, Google (Gemini),
Anthropic (Claude), and xAI (Grok).

Usage:
    tracker = TokenTracker()
    tracker.record(provider, model, prompt_tokens, completion_tokens)
    tracker.print_summary()
"""
import logging
import threading
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Pricing per 1M tokens (USD) — updated as of 2026-04
# ────────────────────────────────────────────────────────────────────

PRICING: dict[str, dict[str, tuple[float, float]]] = {
    # provider -> { model_prefix: (input_per_1M, output_per_1M) }
    "openai": {
        # GPT-5.x series
        "gpt-5.4-nano":         (0.20,   1.25),
        "gpt-5.4":              (2.50,  15.00),
        "gpt-5":                (1.25,  10.00),
        # GPT-4.1 series
        "gpt-4.1-nano":         (0.10,   0.40),
        "gpt-4.1-mini":         (0.50,   2.00),
        "gpt-4.1":              (2.00,   8.00),
        # GPT-4o series
        "gpt-4o-mini":          (0.15,   0.60),
        "gpt-4o":               (2.50,  10.00),
        # Reasoning models (o-series)
        "o4-mini":              (0.50,   2.00),
        "o3-mini":              (0.50,   2.00),
        "o3":                   (2.00,   8.00),
        "_default":             (2.50,  10.00),
    },
    "google": {
        # Gemini 3.x series
        "gemini-3.1-pro-preview":       (2.00,  12.00),
        "gemini-3.1-flash-lite-preview": (0.25,  1.50),
        "gemini-3-flash-preview":       (0.50,   3.00),
        # Gemini 2.5 series
        "gemini-2.5-flash-lite": (0.10,  0.40),
        "gemini-2.5-flash":     (0.30,   2.50),
        "gemini-2.5-pro":       (1.00,  10.00),
        # Gemini 2.0 series
        "gemini-2.0-flash":     (0.10,   0.40),
        # Legacy
        "gemini-1.5-pro":       (1.25,   5.00),
        "gemini-1.5-flash":     (0.075,  0.30),
        "_default":             (1.00,  10.00),
    },
    "anthropic": {
        # Claude Opus series
        "claude-opus-4-6":      (5.00,  25.00),
        "claude-opus-4-5":      (5.00,  25.00),
        "claude-opus-4-1":      (15.00, 75.00),
        "claude-opus-4":        (15.00, 75.00),
        "claude-3-opus":        (15.00, 75.00),
        # Claude Sonnet series
        "claude-sonnet-4-6":    (3.00,  15.00),
        "claude-sonnet-4-5":    (3.00,  15.00),
        "claude-sonnet-4":      (3.00,  15.00),
        "claude-3-5-sonnet":    (3.00,  15.00),
        # Claude Haiku series
        "claude-haiku-4-5":     (1.00,   5.00),
        "claude-haiku-3-5":     (0.80,   4.00),
        "claude-3-haiku":       (0.25,   1.25),
        "_default":             (3.00,  15.00),
    },
    "xai": {
        "grok-4-fast":          (0.20,   0.50),
        "grok-4":               (3.00,  15.00),
        "grok-3":               (3.00,  15.00),
        "grok-3-mini":          (0.30,   0.50),
        "_default":             (3.00,  15.00),
    },
}


def _lookup_price(provider: str, model: str) -> tuple[float, float]:
    """Look up (input_per_1M, output_per_1M) for a provider + model.

    For OpenRouter models (format "provider/model"), strips the prefix
    and looks up in the original provider's pricing table.
    """
    # OpenRouter models: "openai/gpt-4o" → lookup in PRICING["openai"] for "gpt-4o"
    if provider == "openrouter" and "/" in model:
        orig_provider, orig_model = model.split("/", 1)
        # Map OpenRouter provider prefixes to our pricing table keys
        provider_map = {
            "openai": "openai", "anthropic": "anthropic",
            "google": "google", "x-ai": "xai",
            "meta-llama": "openai",  # use openai default pricing as fallback
            "deepseek": "openai",
            "mistralai": "openai",
        }
        mapped_provider = provider_map.get(orig_provider, orig_provider)
        result = _lookup_in_provider(mapped_provider, orig_model)
        if result != (0.0, 0.0):
            return result
        # Try with full model name as fallback
        return _lookup_in_provider(mapped_provider, model)

    return _lookup_in_provider(provider, model)


def _lookup_in_provider(provider: str, model: str) -> tuple[float, float]:
    """Look up price in a specific provider's pricing table."""
    provider_prices = PRICING.get(provider, {})
    if not provider_prices:
        return (0.0, 0.0)

    # Try exact match first, then prefix match (longest first)
    if model in provider_prices:
        return provider_prices[model]

    # Prefix matching: sort by length descending to match most specific first
    for prefix in sorted(provider_prices.keys(), key=len, reverse=True):
        if prefix != "_default" and model.startswith(prefix):
            return provider_prices[prefix]

    return provider_prices.get("_default", (0.0, 0.0))


# ────────────────────────────────────────────────────────────────────
# Token usage record
# ────────────────────────────────────────────────────────────────────

@dataclass
class TokenUsageRecord:
    """A single LLM API call's token usage."""
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    call_label: str = ""


@dataclass
class TokenTracker:
    """Aggregates token usage and cost across an entire session.

    Thread-safe: uses a lock for concurrent taxonomy-builder calls.
    """
    records: list[TokenUsageRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # Running totals
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_calls: int = 0

    def record(self, provider: str, model: str,
               prompt_tokens: int, completion_tokens: int,
               call_label: str = ""):
        """Record a single API call's token usage."""
        total = prompt_tokens + completion_tokens
        input_rate, output_rate = _lookup_price(provider, model)
        cost = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000

        rec = TokenUsageRecord(
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            estimated_cost_usd=cost,
            call_label=call_label,
        )

        with self._lock:
            self.records.append(rec)
            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens
            self.total_tokens += total
            self.total_cost_usd += cost
            self.total_calls += 1

        logger.debug(f"Token usage: {call_label or 'call'} → "
                     f"{prompt_tokens}+{completion_tokens}={total} tokens, "
                     f"${cost:.4f}")

    def print_summary(self):
        """Print a formatted summary of token usage and costs."""
        print("\n" + "=" * 72)
        print("  TOKEN USAGE & COST SUMMARY")
        print("=" * 72)

        if not self.records:
            print("  No LLM calls were made.")
            print("=" * 72)
            return

        # Per-model breakdown
        model_stats: dict[str, dict] = {}
        for r in self.records:
            key = f"{r.provider}/{r.model}"
            if key not in model_stats:
                model_stats[key] = {
                    "calls": 0, "prompt": 0, "completion": 0,
                    "total": 0, "cost": 0.0,
                }
            s = model_stats[key]
            s["calls"] += 1
            s["prompt"] += r.prompt_tokens
            s["completion"] += r.completion_tokens
            s["total"] += r.total_tokens
            s["cost"] += r.estimated_cost_usd

        print(f"\n  {'Model':<35} {'Calls':>6} {'Prompt':>10} {'Completion':>12} {'Total':>10} {'Cost (USD)':>12}")
        print(f"  {'─' * 35} {'─' * 6} {'─' * 10} {'─' * 12} {'─' * 10} {'─' * 12}")

        for model_key in sorted(model_stats.keys()):
            s = model_stats[model_key]
            print(f"  {model_key:<35} {s['calls']:>6} {s['prompt']:>10,} "
                  f"{s['completion']:>12,} {s['total']:>10,} ${s['cost']:>11.4f}")

        print(f"  {'─' * 35} {'─' * 6} {'─' * 10} {'─' * 12} {'─' * 10} {'─' * 12}")
        print(f"  {'TOTAL':<35} {self.total_calls:>6} {self.total_prompt_tokens:>10,} "
              f"{self.total_completion_tokens:>12,} {self.total_tokens:>10,} "
              f"${self.total_cost_usd:>11.4f}")
        print("=" * 72)

    def to_dict(self) -> dict:
        """Return a JSON-serializable summary."""
        return {
            "total_calls": self.total_calls,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "per_call": [
                {
                    "provider": r.provider,
                    "model": r.model,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "total_tokens": r.total_tokens,
                    "estimated_cost_usd": round(r.estimated_cost_usd, 6),
                    "label": r.call_label,
                }
                for r in self.records
            ],
        }


# ────────────────────────────────────────────────────────────────────
# Global tracker (singleton for the process)
# ────────────────────────────────────────────────────────────────────

_global_tracker: TokenTracker | None = None


def get_global_tracker() -> TokenTracker:
    """Get (or create) the global token tracker."""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = TokenTracker()
    return _global_tracker


def reset_global_tracker():
    """Reset the global tracker for a fresh run."""
    global _global_tracker
    _global_tracker = TokenTracker()
