# Refactored code to separate game logic from UI

def get_range_for_difficulty(difficulty: str):
    """Return (low, high) inclusive range for a given difficulty."""

    if difficulty == "Easy":
        return 1, 20

    if difficulty == "Normal":
        return 1, 100

    if difficulty == "Hard":
        return 1, 50

    return 1, 100

def get_attempt_limit(difficulty: str):
    """Return the maximum number of attempts for each difficulty."""

    attempt_limits = {
        "Easy": 6,
        "Normal": 8,
        "Hard": 5,
    }

    return attempt_limits.get(difficulty, 8)

def is_guess_in_range(guess: int, low: int, high: int):
    """Check whether a guess falls within the allowed range."""

    return low <= guess <= high

def parse_guess(raw: str):
    """Parse user input into an integer.

    Returns:
        (ok, guess_int, error_message)
    """

    if raw is None or raw.strip() == "":
        return False, None, "Enter a guess."

    try:
        value = int(raw.strip())

    except (ValueError, TypeError):
        return False, None, "That is not a valid whole number."

    return True, value, None

def check_guess(guess, secret):
    """Compare the guess with the secret number."""

    if guess == secret:
        return "Win", "🎉 Correct!"

    if guess > secret:
        return "Too High", "📉 Go LOWER!"

    return "Too Low", "📈 Go HIGHER!"

def update_score(current_score: int, outcome: str, attempt_number: int):
    """Update score based on outcome and attempt number."""

    if outcome == "Win":
        points = max(10, 100 - 10 * (attempt_number - 1))
        return current_score + points

    if outcome in ("Too High", "Too Low"):
        return current_score - 5

    return current_score