import pytest

from logic_utils import (get_range_for_difficulty, get_attempt_limit, is_guess_in_range, parse_guess, check_guess, update_score,)

# Guess outcome tests.
def test_winning_guess():
    assert check_guess(50, 50) == ("Win", "🎉 Correct!")

def test_guess_too_high():
    assert check_guess(60, 50) == ("Too High", "📉 Go LOWER!")

def test_guess_too_low():
    assert check_guess(40, 50) == ("Too Low", "📈 Go HIGHER!")

# Input validation tests.
@pytest.mark.parametrize(
    "raw",
    ["", "   ", "hello", "3.5", None],
)
def test_invalid_guess_is_rejected(raw):
    ok, guess, error = parse_guess(raw)

    assert ok is False
    assert guess is None
    assert error is not None

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("50", 50),
        (" 25 ", 25),
        ("0", 0),
        ("-5", -5),
    ],
)
def test_valid_integer_input_is_parsed(raw, expected):
    assert parse_guess(raw) == (True, expected, None)


# Difficulty range tests.
@pytest.mark.parametrize(
    ("difficulty", "expected_range"),
    [
        ("Easy", (1, 20)),
        ("Normal", (1, 100)),
        ("Hard", (1, 50)),
    ],
)
def test_difficulty_ranges(difficulty, expected_range):
    assert get_range_for_difficulty(difficulty) == expected_range

def test_unknown_difficulty_uses_default_range():
    assert get_range_for_difficulty("Unknown") == (1, 100)

# Attempt limit tests.
@pytest.mark.parametrize(
    ("difficulty", "expected_limit"),
    [
        ("Easy", 6),
        ("Normal", 8),
        ("Hard", 5),
    ],
)
def test_attempt_limits(difficulty, expected_limit):
    assert get_attempt_limit(difficulty) == expected_limit

def test_unknown_difficulty_uses_default_attempt_limit():
    assert get_attempt_limit("Unknown") == 8


# Guess range validation tests.
@pytest.mark.parametrize(
    ("guess", "low", "high", "expected"),
    [
        (1, 1, 20, True),
        (20, 1, 20, True),
        (10, 1, 20, True),
        (0, 1, 20, False),
        (21, 1, 20, False),
        (50, 1, 100, True),
    ],
)
def test_guess_range_validation(guess, low, high, expected):
    assert is_guess_in_range(guess, low, high) is expected

# Scoring tests.
def test_first_attempt_win_awards_100_points():
    assert update_score(0, "Win", 1) == 100

def test_later_win_awards_fewer_points():
    assert update_score(0, "Win", 2) == 90

def test_win_score_never_falls_below_10():
    assert update_score(0, "Win", 20) == 10

def test_incorrect_guess_loses_5_points():
    assert update_score(20, "Too High", 1) == 15
    assert update_score(20, "Too Low", 1) == 15

def test_score_can_become_negative():
    assert update_score(0, "Too High", 1) == -5

def test_unknown_outcome_does_not_change_score():
    assert update_score(20, "Unknown", 1) == 20