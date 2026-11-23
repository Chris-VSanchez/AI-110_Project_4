"""AI hint and fun-fact generation powered by Google Gemini.

Flow for a hint:
    game state -> hint level (gets more specific as attempts are used)
               -> prompt -> Gemini
               -> answer filter (reject any response that contains the secret)
               -> retry with feedback (up to MAX_ATTEMPTS calls)
               -> built-in fallback hint if the AI keeps failing or is unavailable

Every request, response, filtered leak, error and fallback is logged to logs/game.log.
"""

import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from logging_config import get_logger

logger = get_logger("ai_hints")

DEFAULT_MODEL = "gemini-3.5-flash-lite"
MAX_ATTEMPTS = 3  # total AI calls per hint (1 try + 2 retries)
REQUEST_TIMEOUT_MS = 20_000
RETRY_DELAY_S = 1.0  # wait before retrying after an error (doubles each time)

HINT_LEVELS = ["vague", "moderate", "specific", "very specific"]

LEVEL_INSTRUCTIONS = {
    0: "Give a VAGUE hint: one broad property such as whether it is even or odd, "
       "or which half of the range it is in.",
    1: "Give a MODERATE hint: something like a number it is divisible by, how many "
       "digits it has, or roughly which part of the range it is in.",
    2: "Give a SPECIFIC hint: combine two properties (for example the sum of its digits, "
       "whether it is prime, or which group of ten it falls in).",
    3: "Give a VERY SPECIFIC hint: this is the player's last chance, so narrow it down "
       "to a small window of about 5 numbers or an unmistakable property.",
}

SYSTEM_INSTRUCTION = (
    "You are the friendly hint-giver in a number guessing game. "
    "You know the secret number and help the player find it without ever saying it. "
    "Never write the secret number in digits or in words. "
    "Reply with ONE short sentence (under 25 words) and nothing else."
)

class AIUnavailable(Exception):
    """Raised when the AI client cannot be created (missing key or package)."""

class TextModel(Protocol):
    """Anything with a generate(prompt) -> str method. Lets tests inject a fake model."""

    def generate(self, prompt: str) -> str: ...

class GeminiClient:
    """Thin wrapper around the google-genai SDK."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise AIUnavailable("GEMINI_API_KEY is not set. Add it to your .env file.")

        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise AIUnavailable("The google-genai package is not installed.") from exc

        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
        self._types = types
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
        )
        logger.info("Gemini client ready (model=%s)", self.model)

    def generate(self, prompt: str) -> str:
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=self._types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.9,
                max_output_tokens=120,
            ),
        )
        return (response.text or "").strip()

@dataclass
class AIResult:
    """What the game shows, plus metadata used for logging and evaluation."""

    text: str
    source: str  # "ai" or "fallback"
    level: int = 0
    calls: int = 0
    filtered: int = 0  # responses rejected because they contained the answer
    errors: List[str] = field(default_factory=list)
    latency_ms: float = 0.0

    @property
    def level_name(self) -> str:
        return HINT_LEVELS[self.level]

# ---------------------------------------------------------------------------
# Hint level
# ---------------------------------------------------------------------------

def get_hint_level(attempts_used: int, attempt_limit: int) -> int:
    """Map attempts used to a hint level 0-3. More attempts used = more specific hint."""

    attempts_left = attempt_limit - attempts_used

    if attempts_left <= 1:
        return 3

    ratio = attempts_used / max(1, attempt_limit)

    if ratio < 1 / 3:
        return 0
    if ratio < 2 / 3:
        return 1
    return 2

# ---------------------------------------------------------------------------
# Answer filter
# ---------------------------------------------------------------------------

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

def number_to_words(n: int) -> str:
    """Spell out 0-999 in English, e.g. 142 -> 'one hundred forty two'."""

    if n < 0 or n > 999:
        return str(n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + ("" if ones == 0 else " " + _ONES[ones])

    hundreds, rest = divmod(n, 100)
    words = _ONES[hundreds] + " hundred"
    return words if rest == 0 else words + " " + number_to_words(rest)

def contains_secret(text: str, secret: int) -> bool:
    """True if the text reveals the secret in digits ('42') or words ('forty-two').

    Digit matches must stand alone, so '142' or '4.2' do not count as revealing 42.
    """

    if not text:
        return False

    if re.search(rf"(?<![\d.,]){secret}(?![\d]|[.,]\d)", text):
        return True

    words = number_to_words(secret).split()
    word_pattern = r"\b" + r"[\s-]+(?:and[\s-]+)?".join(map(re.escape, words)) + r"\b"
    match = re.search(word_pattern, text, flags=re.IGNORECASE)

    if not match:
        # "a hundred" is a common way to say 100.
        return secret == 100 and re.search(r"\ba[\s-]+hundred\b", text, re.IGNORECASE) is not None

    # "forty two" should not match inside "one hundred forty two".
    if secret < 100:
        before = text[: match.start()].lower().rstrip(" -")
        if before.endswith("hundred") or before.endswith("hundred and"):
            return False

    return True

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def build_hint_prompt(secret, low, high, attempts_used, attempt_limit, level,
                      guesses=None, previous_hints=None, feedback=None) -> str:
    lines = [
        f"The secret number is {secret}. The allowed range is {low} to {high}.",
        f"The player has used {attempts_used} of {attempt_limit} attempts.",
        LEVEL_INSTRUCTIONS[level],
    ]

    if guesses:
        lines.append(f"The player's wrong guesses so far: {', '.join(map(str, guesses))}.")
    if previous_hints:
        lines.append("Hints already given (say something new and more specific):")
        lines.extend(f"- {h}" for h in previous_hints)
    if feedback:
        lines.append(f"IMPORTANT: {feedback}")

    lines.append("Do NOT say the secret number in digits or words. Reply with the hint only.")
    return "\n".join(lines)

def build_fun_fact_prompt(secret: int, won: bool) -> str:
    result = "won" if won else "ran out of attempts"
    return (
        f"The game is over: the player {result}. The secret number was {secret}. "
        f"Share ONE short, surprising fun fact or mathematical property about the number {secret}. "
        "You MAY mention the number now. Reply with one sentence under 30 words."
    )

# ---------------------------------------------------------------------------
# Fallbacks (used when the AI is unavailable or keeps leaking)
# ---------------------------------------------------------------------------

def fallback_hint(secret: int, low: int, high: int, level: int, rng=None) -> str:
    rng = rng or random.Random()

    if level == 0:
        return f"It's an {'even' if secret % 2 == 0 else 'odd'} number."

    if level == 1:
        mid = (low + high) / 2
        half = "lower" if secret <= mid else "upper"
        return f"It's in the {half} half of the range."

    width = 10 if level == 2 else 4
    below = rng.randint(1, width - 1)
    start, end = secret - below, secret - below + width

    if start < low:
        hint = f"It's less than {end}."
    elif end > high:
        hint = f"It's greater than {start}."
    else:
        hint = f"It's somewhere between {start} and {end}."
    return hint if not contains_secret(hint, secret) else f"It's within {width} of the middle of the range."

def fallback_fun_fact(secret: int) -> str:
    return f"{secret} is written as {bin(secret)[2:]} in binary."

# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def _call_model(model: TextModel, prompt: str, result: AIResult, kind: str) -> Optional[str]:
    """Make one AI call, recording errors and call counts. Returns text or None."""

    result.calls += 1
    try:
        text = model.generate(prompt)
    except Exception as exc:  # network errors, quota, 503s, bad responses...
        msg = f"{type(exc).__name__}: {str(exc)[:200]}"
        result.errors.append(msg)
        logger.warning("%s call %d failed: %s", kind, result.calls, msg)
        return None

    if not text:
        result.errors.append("empty response")
        logger.warning("%s call %d returned an empty response", kind, result.calls)
        return None

    return text

def _backoff(result: AIResult, max_attempts: int, retry_delay: float) -> None:
    """Wait before retrying after an error (e.g. 429 rate limit), unless no retries remain."""

    if retry_delay > 0 and result.calls < max_attempts:
        time.sleep(retry_delay * 2 ** (result.calls - 1))

def generate_hint(model: Optional[TextModel], secret: int, low: int, high: int,
                  attempts_used: int, attempt_limit: int, guesses=None,
                  previous_hints=None, max_attempts: int = MAX_ATTEMPTS,
                  retry_delay: float = RETRY_DELAY_S) -> AIResult:
    """Ask the AI for a progressive hint and filter out any response containing the answer."""

    level = get_hint_level(attempts_used, attempt_limit)
    result = AIResult(text="", source="fallback", level=level)
    start = time.perf_counter()
    feedback = None

    logger.info("Hint requested: level=%s attempts=%d/%d range=%d-%d",
                HINT_LEVELS[level], attempts_used, attempt_limit, low, high)

    if model is not None:
        for _ in range(max_attempts):
            prompt = build_hint_prompt(secret, low, high, attempts_used, attempt_limit,
                                       level, guesses, previous_hints, feedback)
            text = _call_model(model, prompt, result, "Hint")

            if text is None:
                _backoff(result, max_attempts, retry_delay)
                continue

            if contains_secret(text, secret):
                result.filtered += 1
                logger.warning("FILTERED hint that revealed the answer (call %d): %r",
                               result.calls, text)
                feedback = ("Your last hint revealed the secret number. "
                            "Write a new hint that does not contain it in any form.")
                continue

            result.text, result.source = text, "ai"
            break

    if result.source != "ai":
        result.text = fallback_hint(secret, low, high, level)
        logger.info("Using fallback hint (model=%s, calls=%d, filtered=%d)",
                    "none" if model is None else "set", result.calls, result.filtered)

    result.latency_ms = (time.perf_counter() - start) * 1000
    logger.info("Hint delivered: source=%s level=%s calls=%d filtered=%d latency=%.0fms text=%r",
                result.source, result.level_name, result.calls, result.filtered,
                result.latency_ms, result.text)
    return result

def generate_fun_fact(model: Optional[TextModel], secret: int, won: bool,
                      max_attempts: int = 2, retry_delay: float = RETRY_DELAY_S) -> AIResult:
    """Ask the AI for a fun fact about the (now revealed) secret number."""

    result = AIResult(text="", source="fallback", level=0)
    start = time.perf_counter()

    if model is not None:
        for _ in range(max_attempts):
            text = _call_model(model, build_fun_fact_prompt(secret, won), result, "Fun fact")
            if text:
                result.text, result.source = text, "ai"
                break
            _backoff(result, max_attempts, retry_delay)

    if result.source != "ai":
        result.text = fallback_fun_fact(secret)

    result.latency_ms = (time.perf_counter() - start) * 1000
    logger.info("Fun fact delivered: source=%s calls=%d latency=%.0fms text=%r",
                result.source, result.calls, result.latency_ms, result.text)
    return result