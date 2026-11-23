import random
import streamlit as st
from dotenv import load_dotenv

from logic_utils import (get_range_for_difficulty, get_attempt_limit, is_guess_in_range, parse_guess, check_guess, update_score,)
from ai_hints import AIUnavailable, GeminiClient, generate_fun_fact, generate_hint
from logging_config import get_logger

# Load GEMINI_API_KEY (and optional GEMINI_MODEL) from a local .env file.
load_dotenv()
logger = get_logger("app")

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

st.sidebar.divider()
ai_enabled = st.sidebar.toggle(
    "🤖 AI hints & facts",
    value=False,
    help="After each wrong guess, Gemini gives a hint that gets more specific "
         "as you use attempts. When the game ends, it shares a fun fact about the number.",
)


@st.cache_resource(show_spinner=False)
def get_ai_client():
    """Create the Gemini client once per server. Returns (client, error_message)."""

    try:
        return GeminiClient(), None
    except AIUnavailable as exc:
        logger.warning("AI unavailable: %s", exc)
        return None, str(exc)


ai_client = None

if ai_enabled:
    ai_client, ai_error = get_ai_client()

    if ai_client:
        st.sidebar.caption(f"AI model: {ai_client.model}")
    else:
        st.sidebar.warning(f"AI is offline ({ai_error}). Built-in hints will be used instead.")

# Centralized game initialization and reset.
def reset_game(difficulty, low, high):
    """Initialize or reset all game session variables."""

    st.session_state.game_difficulty = difficulty
    st.session_state.secret = random.randint(low, high)
    st.session_state.attempts = 0
    st.session_state.score = 0
    st.session_state.status = "playing"
    st.session_state.history = []
    st.session_state.ai_hints = []
    st.session_state.fun_fact = None
    logger.info("New game: difficulty=%s range=%d-%d", difficulty, low, high)

def show_ai_hints():
    """Show every AI hint given so far this game."""

    for i, hint in enumerate(st.session_state.ai_hints, start=1):
        label = "🤖 AI hint" if hint["source"] == "ai" else "💡 Built-in hint"
        st.info(f"{label} #{i} ({hint['level']}): {hint['text']}")


def show_fun_fact():
    """Generate (once) and show a fun fact about the secret after the game ends."""

    if not ai_enabled:
        return

    if st.session_state.fun_fact is None:
        with st.spinner("Asking the AI for a fun fact..."):
            result = generate_fun_fact(
                ai_client,
                st.session_state.secret,
                won=st.session_state.status == "won",
            )
        st.session_state.fun_fact = result.text

    st.success(f"🧠 Fun fact: {st.session_state.fun_fact}")


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
    st.write("AI hints:", st.session_state.ai_hints)

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
    logger.info("Player started a new game")
    reset_game(difficulty, low, high)
    st.rerun()

# Stop further guesses after the game ends.
if st.session_state.status != "playing":

    if st.session_state.status == "won":
        st.success("You already won. Start a new game to play again.")

    else:
        st.error("Game over. Start a new game to try again.")

    show_ai_hints()
    show_fun_fact()
    st.stop()

# Process submitted guesses.
if submit:

    ok, guess_int, err = parse_guess(raw_guess)

    # Reject invalid input without consuming an attempt.
    if not ok:
        logger.info("Rejected input %r: %s", raw_guess, err)
        st.error(err)

    # Reject guesses outside the selected difficulty range.
    elif not is_guess_in_range(guess_int, low, high):
        logger.info("Rejected out-of-range guess %d", guess_int)
        st.error(f"Enter a number between {low} and {high}.")

    else:
        # Only valid guesses consume attempts.
        st.session_state.attempts += 1
        st.session_state.history.append(guess_int)

        secret = st.session_state.secret

        outcome, message = check_guess(guess_int, secret)
        logger.info("Guess %d -> %s (attempt %d/%d)",
                    guess_int, outcome, st.session_state.attempts, attempt_limit)

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

        # Wrong guess with attempts left: ask the AI for a progressive hint.
        elif ai_enabled:
            with st.spinner("The AI is thinking of a hint..."):
                result = generate_hint(
                    ai_client,
                    secret=secret,
                    low=low,
                    high=high,
                    attempts_used=st.session_state.attempts,
                    attempt_limit=attempt_limit,
                    guesses=st.session_state.history,
                    previous_hints=[h["text"] for h in st.session_state.ai_hints],
                )

            st.session_state.ai_hints.append(
                {"text": result.text, "level": result.level_name, "source": result.source}
            )

            if result.filtered:
                st.caption(f"🛡️ Filtered {result.filtered} AI response(s) that gave away the answer.")

        if st.session_state.status != "playing":
            logger.info("Game over: status=%s secret=%d score=%d",
                        st.session_state.status, secret, st.session_state.score)
            show_fun_fact()

# Show AI hints for this game.
show_ai_hints()

# Display game history.
st.divider()
st.subheader("Guess History")

if st.session_state.history:
    st.write(st.session_state.history)

else:
    st.caption("No guesses yet. Start playing!")

st.divider()

st.caption("Built by an AI that claims this code is production-ready.")