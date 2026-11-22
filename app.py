import random
import streamlit as st

from logic_utils import (get_range_for_difficulty, get_attempt_limit, is_guess_in_range, parse_guess, check_guess, update_score,)

st.set_page_config(page_title = "Glitchy Guesser", page_icon = "🎮")

st.title("🎮 Game Glitch Investigator")
st.caption("An AI-generated guessing game. Something is off.")

st.sidebar.header("Settings")

difficulty = st.sidebar.selectbox(
    "Difficulty",
    ["Easy", "Normal", "Hard"],
    index = 1,
)

# Get game settings from logic_utils.py.
low, high = get_range_for_difficulty(difficulty)
attempt_limit = get_attempt_limit(difficulty)

st.sidebar.caption(f"Range: {low} to {high}")
st.sidebar.caption(f"Attempts allowed: {attempt_limit}")

# Centralized game initialization and reset.
def reset_game(difficulty, low, high):
    """Initialize or reset all game session variables."""

    st.session_state.game_difficulty = difficulty
    st.session_state.secret = random.randint(low, high)
    st.session_state.attempts = 0
    st.session_state.score = 0
    st.session_state.status = "playing"
    st.session_state.history = []

# Initialize a new game or reset when difficulty changes.
if "secret" not in st.session_state or st.session_state.game_difficulty != difficulty:
    reset_game(difficulty, low, high)

st.subheader("Make a guess")

attempts_left = max(0, attempt_limit - st.session_state.attempts)

st.info(
    f"Guess a number between {low} and {high}. "
    f"Attempts left: {attempts_left}"
)

with st.expander("Developer Debug Info"):
    st.write("Secret:", st.session_state.secret)
    st.write("Attempts:", st.session_state.attempts)
    st.write("Score:", st.session_state.score)
    st.write("Difficulty:", difficulty)
    st.write("History:", st.session_state.history)

raw_guess = st.text_input(
    "Enter your guess:",
    key = f"guess_input_{difficulty}"
)

col1, col2, col3 = st.columns(3)

with col1:
    submit = st.button("Submit Guess 🚀")

with col2:
    new_game = st.button("New Game 🔁")

with col3:
    show_hint = st.checkbox("Show hint", value=True)

# Start a new game and clear previous game data.
if new_game:
    reset_game(difficulty, low, high)
    st.rerun()

# Stop further guesses after the game ends.
if st.session_state.status != "playing":

    if st.session_state.status == "won":
        st.success("You already won. Start a new game to play again.")

    else:
        st.error("Game over. Start a new game to try again.")

    st.stop()

# Process submitted guesses.
if submit:

    ok, guess_int, err = parse_guess(raw_guess)

    # Reject invalid input without consuming an attempt.
    if not ok:
        st.error(err)

    # Reject guesses outside the selected difficulty range.
    elif not is_guess_in_range(guess_int, low, high):
        st.error(f"Enter a number between {low} and {high}.")

    else:
        # Only valid guesses consume attempts.
        st.session_state.attempts += 1
        st.session_state.history.append(guess_int)

        secret = st.session_state.secret

        outcome, message = check_guess(guess_int, secret)

        if show_hint:
            st.warning(message)

        # Update score.
        st.session_state.score = update_score(
            current_score=st.session_state.score,
            outcome=outcome,
            attempt_number=st.session_state.attempts,
        )

        # Handle winning guesses.
        if outcome == "Win":

            st.session_state.status = "won"

            st.balloons()

            st.success(
                f"You won! The secret was {secret}. "
                f"Final score: {st.session_state.score}"
            )

        # Handle running out of attempts.
        elif st.session_state.attempts >= attempt_limit:

            st.session_state.status = "lost"

            st.error(
                f"Out of attempts! "
                f"The secret was {secret}. "
                f"Score: {st.session_state.score}"
            )

# Display game history.
st.divider()
st.subheader("Guess History")

if st.session_state.history:
    st.write(st.session_state.history)

else:
    st.caption("No guesses yet. Start playing!")

st.divider()

st.caption("Built by an AI that claims this code is production-ready.")