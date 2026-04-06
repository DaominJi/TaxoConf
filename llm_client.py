"""
Unified multi-provider LLM client.

Supports OpenAI, Google Gemini, Anthropic Claude, and xAI Grok through a
common `.chat(system, user)` interface with automatic token tracking.

Usage:
    from llm_client import LLMClient
    llm = LLMClient()
    response = llm.chat("You are helpful.", "Hello!", call_label="test")
"""
import logging
import os

import config
from token_tracker import get_global_tracker

logger = logging.getLogger(__name__)


class LLMClient:
    """Unified wrapper around OpenAI, Google Gemini, Anthropic Claude, and xAI Grok.

    Provider selection is based on config.LLM_PROVIDER:
      - "openai"    -> uses the openai SDK
      - "google"    -> uses the google-genai SDK
      - "anthropic" -> uses the anthropic SDK
      - "xai"       -> uses the openai SDK with xAI base URL

    All providers are accessed through a common `.chat(system, user)` interface
    and token usage is automatically tracked via the global TokenTracker.
    """

    def __init__(self, provider: str = None, model: str = None,
                 temperature: float = None, json_mode: bool = True):
        self.provider = (provider or getattr(config, "LLM_PROVIDER", "openai")).lower()
        self.model = model or config.LLM_MODEL
        self.temperature = temperature if temperature is not None else config.LLM_TEMPERATURE
        self.json_mode = json_mode
        self.tracker = get_global_tracker()

        self._init_client()

    def _init_client(self):
        """Initialize the appropriate SDK client."""
        if self.provider == "openai":
            self._init_openai()
        elif self.provider == "google":
            self._init_google()
        elif self.provider == "anthropic":
            self._init_anthropic()
        elif self.provider == "xai":
            self._init_xai()
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider!r}. "
                             f"Supported: openai, google, anthropic, xai")

    def _init_openai(self):
        """Initialize OpenAI client (uses OPENAI_API_KEY env var)."""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package required for OpenAI provider. "
                              "Install with: pip install openai")
        self.client = OpenAI()

    def _init_google(self):
        """Initialize Google Gemini client (uses GOOGLE_API_KEY env var)."""
        try:
            from google import genai
        except ImportError:
            raise ImportError("google-genai package required for Google provider. "
                              "Install with: pip install google-genai")
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY environment variable required")
        self.client = genai.Client(api_key=api_key)

    def _init_anthropic(self):
        """Initialize Anthropic Claude client (uses ANTHROPIC_API_KEY env var)."""
        try:
            import anthropic
        except ImportError:
            raise ImportError("anthropic package required for Anthropic provider. "
                              "Install with: pip install anthropic")
        self.client = anthropic.Anthropic()

    def _init_xai(self):
        """Initialize xAI Grok client (OpenAI-compatible, uses XAI_API_KEY env var)."""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package required for xAI provider. "
                              "Install with: pip install openai")
        api_key = os.environ.get("XAI_API_KEY")
        if not api_key:
            raise ValueError("XAI_API_KEY environment variable required")
        self.client = OpenAI(api_key=api_key,
                             base_url="https://api.x.ai/v1")

    # -- Unified chat interface --

    def chat(self, system: str, user: str, call_label: str = "") -> str:
        """Send a chat completion request and return the text response.

        Automatically dispatches to the correct provider and records
        token usage in the global tracker.
        """
        for attempt in range(config.LLM_MAX_RETRIES):
            try:
                if self.provider == "openai" or self.provider == "xai":
                    return self._chat_openai(system, user, call_label)
                elif self.provider == "google":
                    return self._chat_google(system, user, call_label)
                elif self.provider == "anthropic":
                    return self._chat_anthropic(system, user, call_label)
            except Exception as e:
                logger.warning(f"LLM call failed (attempt {attempt+1}/{config.LLM_MAX_RETRIES}): {e}")
                if attempt == config.LLM_MAX_RETRIES - 1:
                    raise
        return ""

    def _chat_openai(self, system: str, user: str, call_label: str) -> str:
        """OpenAI / xAI (OpenAI-compatible) chat completion."""
        kwargs = dict(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        if self.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self.client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content.strip()

        usage = resp.usage
        if usage:
            self.tracker.record(
                provider=self.provider,
                model=self.model,
                prompt_tokens=usage.prompt_tokens or 0,
                completion_tokens=usage.completion_tokens or 0,
                call_label=call_label,
            )
        return text

    def _chat_google(self, system: str, user: str, call_label: str) -> str:
        """Google Gemini chat completion via google-genai SDK."""
        from google.genai import types

        combined_prompt = f"{system}\n\n{user}"
        gen_config = types.GenerateContentConfig(
            temperature=self.temperature,
        )
        if self.json_mode:
            gen_config.response_mime_type = "application/json"
        response = self.client.models.generate_content(
            model=self.model,
            contents=combined_prompt,
            config=gen_config,
        )
        text = response.text.strip()

        usage = getattr(response, "usage_metadata", None)
        if usage:
            self.tracker.record(
                provider="google",
                model=self.model,
                prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                completion_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                call_label=call_label,
            )
        return text

    def _chat_anthropic(self, system: str, user: str, call_label: str) -> str:
        """Anthropic Claude chat completion."""
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=[
                {"role": "user", "content": user},
            ],
            temperature=self.temperature,
        )

        text = ""
        for block in resp.content:
            if hasattr(block, "text"):
                text += block.text
        text = text.strip()

        # Claude may wrap JSON in markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        usage = resp.usage
        if usage:
            self.tracker.record(
                provider="anthropic",
                model=self.model,
                prompt_tokens=getattr(usage, "input_tokens", 0) or 0,
                completion_tokens=getattr(usage, "output_tokens", 0) or 0,
                call_label=call_label,
            )
        return text
