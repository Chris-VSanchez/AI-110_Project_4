import pytest

from ai_hints import (
    AIUnavailable,
    GeminiClient,
    build_hint_prompt,
    contains_secret,
    fallback_hint,
    generate_fun_fact,
    generate_hint,
    get_hint_level,
    number_to_words,
)

class FakeModel:
    """Stands in for Gemini: returns scripted responses (or raises scripted errors)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

# Hint level tests: hints get more specific as attempts are used.
def test_first_attempt_is_vague():
    assert get_hint_level(attempts_used=1, attempt_limit=8) == 0

def test_hint_levels_never_decrease():
    levels = [get_hint_level(used, 8) for used in range(1, 8)]
    assert levels == sorted(levels)
    assert levels[0] == 0
    assert levels[-1] == 3

@pytest.mark.parametrize("limit", [5, 6, 8])
def test_last_attempt_is_very_specific(limit):
    assert get_hint_level(attempts_used=limit - 1, attempt_limit=limit) == 3

# Answer filter tests.
@pytest.mark.parametrize("text", [
    "The answer is 42.",
    "It's 42",
    "42 is the one!",
    "Think forty-two.",
    "It is Forty Two!",
    "$42",
])
def test_detects_secret(text):
    assert contains_secret(text, 42)

@pytest.mark.parametrize("text", [
    "It's an even number.",
    "It's less than 142.",
    "Between 40 and 45.",
    "It's 4.2 times ten.",
    "Not one hundred forty two.",
])
def test_ignores_text_without_secret(text):
    assert not contains_secret(text, 42)

def test_detects_hundred():
    assert contains_secret("It's a hundred!", 100)
    assert contains_secret("one hundred", 100)

def test_number_to_words():
    assert number_to_words(7) == "seven"
    assert number_to_words(42) == "forty two"
    assert number_to_words(100) == "one hundred"

# Generator tests with a fake AI model.
def test_clean_ai_hint_is_used():
    model = FakeModel(["It's an even number."])
    result = generate_hint(model, secret=42, low=1, high=100, attempts_used=1, attempt_limit=8)

    assert result.source == "ai"
    assert result.text == "It's an even number."
    assert result.calls == 1
    assert result.filtered == 0

def test_leaking_hint_is_filtered_and_retried():
    model = FakeModel(["The answer is 42!", "It's a multiple of 6."])
    result = generate_hint(model, secret=42, low=1, high=100, attempts_used=4, attempt_limit=8)

    assert result.source == "ai"
    assert result.text == "It's a multiple of 6."
    assert result.filtered == 1
    assert result.calls == 2
    # The retry prompt tells the AI what went wrong.
    assert "revealed the secret" in model.prompts[1]

def test_always_leaking_ai_falls_back_without_revealing_answer():
    model = FakeModel(["42!", "forty-two", "It is 42."])
    result = generate_hint(model, secret=42, low=1, high=100, attempts_used=7, attempt_limit=8)

    assert result.source == "fallback"
    assert result.filtered == 3
    assert not contains_secret(result.text, 42)

def test_ai_errors_fall_back():
    model = FakeModel([RuntimeError("503 UNAVAILABLE")] * 3)
    result = generate_hint(model, secret=10, low=1, high=20, attempts_used=1, attempt_limit=6,
                           retry_delay=0)

    assert result.source == "fallback"
    assert len(result.errors) == 3

def test_no_model_uses_fallback():
    result = generate_hint(None, secret=10, low=1, high=20, attempts_used=1, attempt_limit=6)
    assert result.source == "fallback"
    assert result.calls == 0

def test_prompt_includes_level_and_previous_hints():
    prompt = build_hint_prompt(42, 1, 100, attempts_used=7, attempt_limit=8, level=3,
                               guesses=[50, 30], previous_hints=["It's even."])
    assert "VERY SPECIFIC" in prompt
    assert "It's even." in prompt
    assert "50, 30" in prompt

@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_fallback_hints_never_reveal_secret(level):
    for secret in range(1, 101):
        assert not contains_secret(fallback_hint(secret, 1, 100, level), secret)

def test_fun_fact_uses_ai_and_falls_back():
    assert generate_fun_fact(FakeModel(["42 is the answer to everything."]), 42, won=True).source == "ai"

    result = generate_fun_fact(FakeModel([RuntimeError("down"), RuntimeError("down")]), 42, won=False,
                               retry_delay=0)
    assert result.source == "fallback"
    assert "42" in result.text

def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(AIUnavailable):
        GeminiClient()

@pytest.mark.parametrize("secret", [1, 2, 99, 100])
def test_fallback_hints_stay_inside_range(secret):
    hint = fallback_hint(secret, 1, 100, level=3)
    assert "-" not in hint and "0 and" not in hint
    assert not contains_secret(hint, secret)