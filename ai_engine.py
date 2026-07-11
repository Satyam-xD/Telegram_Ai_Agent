"""
ai_engine.py — Multi-provider AI content generation with automatic fallback.

Fallback order:
  Gemini 2.5 Flash → Gemini 2.0 Flash → Gemini 2.5 Lite → Gemini Flash Latest
  → Claude 3 Haiku (if configured)
  → OpenAI GPT-4o-mini (if configured)
"""
import logging

import google.generativeai as genai

from config import claude_client, openai_client

logger = logging.getLogger(__name__)

_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
]


def generate(prompt: str) -> str:
    """Generate text using the first available AI provider.

    Tries each Gemini model in order, then Claude, then OpenAI.
    Raises the last exception if every provider fails.
    """
    last_error: Exception | None = None

    # 1-4: Gemini models
    for idx, model_name in enumerate(_GEMINI_MODELS):
        try:
            logger.info("Trying Gemini model: %s", model_name)
            response = genai.GenerativeModel(model_name).generate_content(prompt)
            return response.text
        except Exception as exc:
            last_error = exc
            err = str(exc)
            quota_hit = "429" in err or "quota" in err.lower()
            if quota_hit and idx < len(_GEMINI_MODELS) - 1:
                logger.warning("%s quota exceeded — trying next Gemini model.", model_name)
                continue
            logger.warning("Gemini (%s) failed: %s", model_name, err)
            break  # Non-quota error or last model — move to next provider

    # 5: Claude
    if claude_client:
        try:
            logger.info("Falling back to Claude (claude-3-haiku-20240307).")
            msg = claude_client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text
        except Exception as exc:
            logger.warning("Claude fallback failed: %s", exc)
            last_error = exc

    # 6: OpenAI
    if openai_client:
        try:
            logger.info("Falling back to OpenAI (gpt-4o-mini).")
            res = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
            )
            return res.choices[0].message.content
        except Exception as exc:
            logger.error("OpenAI fallback failed: %s", exc)
            last_error = exc

    raise last_error or RuntimeError("All AI providers failed.")
