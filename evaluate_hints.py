"""Reliability evaluation for the AI hint generator.

Runs the hint generator across random secrets, every difficulty and every hint
level, then reports how the AI behaved:

  * raw leak rate    - how often Gemini's response contained the answer (before filtering)
  * final leak rate  - how often a hint shown to the player contained the answer (should be 0%)
  * fallback rate    - how often the AI failed and a built-in hint was used instead
  * avg calls/hint   - retries caused by leaks or errors
  * avg latency      - time to produce a hint
  * avg words        - hint length per level (later levels should say more)

Usage:
    python evaluate_hints.py                  # real Gemini (needs GEMINI_API_KEY)
    python evaluate_hints.py --mock           # offline fake AI that sometimes leaks
    python evaluate_hints.py --secrets 5 --out logs/eval_results.json
"""

import argparse
import json
import random
import statistics
import sys
import time
from collections import defaultdict

from dotenv import load_dotenv

from ai_hints import (HINT_LEVELS, AIUnavailable, GeminiClient, contains_secret,
                      generate_hint)
from logic_utils import get_attempt_limit, get_range_for_difficulty

DIFFICULTIES = ["Easy", "Normal", "Hard"]

class MockModel:
    """Offline stand-in for Gemini. Leaks the answer ~30% of the time to exercise the filter."""

    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    def generate(self, prompt):
        secret = int(prompt.split("The secret number is ")[1].split(".")[0])
        if self.rng.random() < 0.3:
            return f"Psst... it's {secret}!"
        return self.rng.choice([
            f"It's {'even' if secret % 2 == 0 else 'odd'}.",
            f"Its digits add up to {sum(map(int, str(secret)))}.",
            f"It's a little above {secret - self.rng.randint(1, 5)}.",
        ])

def attempts_for_level(level, attempt_limit):
    """Pick an attempts_used value that produces the requested hint level."""

    from ai_hints import get_hint_level

    for used in range(1, attempt_limit):
        if get_hint_level(used, attempt_limit) == level:
            return used
    return None

def run(model, secrets_per_difficulty, delay, seed):
    rng = random.Random(seed)
    rows = []

    for difficulty in DIFFICULTIES:
        low, high = get_range_for_difficulty(difficulty)
        limit = get_attempt_limit(difficulty)

        for _ in range(secrets_per_difficulty):
            secret = rng.randint(low, high)
            previous = []

            for level in range(len(HINT_LEVELS)):
                used = attempts_for_level(level, limit)
                if used is None:
                    continue

                result = generate_hint(model, secret, low, high, used, limit,
                                       previous_hints=previous)
                previous.append(result.text)

                rows.append({
                    "difficulty": difficulty,
                    "secret": secret,
                    "level": result.level_name,
                    "source": result.source,
                    "calls": result.calls,
                    "filtered": result.filtered,
                    "errors": len(result.errors),
                    "latency_ms": round(result.latency_ms),
                    "words": len(result.text.split()),
                    "final_leak": contains_secret(result.text, secret),
                    "repeat": result.text in previous[:-1],
                    "text": result.text,
                })
                print(f"[{difficulty:6} secret={secret:3} {result.level_name:13}] "
                      f"{result.source:8} {result.text}")

                if delay:
                    time.sleep(delay)

    return rows

def summarize(rows):
    total_calls = sum(r["calls"] for r in rows) or 1
    n = len(rows) or 1

    summary = {
        "hints": len(rows),
        "ai_calls": sum(r["calls"] for r in rows),
        "raw_leak_rate": sum(r["filtered"] for r in rows) / total_calls,
        "final_leak_rate": sum(r["final_leak"] for r in rows) / n,
        "fallback_rate": sum(r["source"] == "fallback" for r in rows) / n,
        "error_rate": sum(r["errors"] for r in rows) / total_calls,
        "repeat_rate": sum(r["repeat"] for r in rows) / n,
        "avg_calls_per_hint": sum(r["calls"] for r in rows) / n,
        "avg_latency_ms": statistics.mean(r["latency_ms"] for r in rows) if rows else 0,
        "avg_words_by_level": {},
    }

    by_level = defaultdict(list)
    for r in rows:
        by_level[r["level"]].append(r["words"])
    for level in HINT_LEVELS:
        if by_level[level]:
            summary["avg_words_by_level"][level] = round(statistics.mean(by_level[level]), 1)

    return summary

def print_summary(s):
    print("\n=== AI Hint Reliability Report ===")
    print(f"Hints generated        : {s['hints']}  ({s['ai_calls']} AI calls)")
    print(f"Raw leak rate (AI)     : {s['raw_leak_rate']:.1%}  <- responses filtered for revealing the answer")
    print(f"Final leak rate        : {s['final_leak_rate']:.1%}  <- must be 0%")
    print(f"Fallback rate          : {s['fallback_rate']:.1%}")
    print(f"Error rate             : {s['error_rate']:.1%}")
    print(f"Repeated hint rate     : {s['repeat_rate']:.1%}")
    print(f"Avg AI calls per hint  : {s['avg_calls_per_hint']:.2f}")
    print(f"Avg latency            : {s['avg_latency_ms']:.0f} ms")
    print("Avg words by level     : " + ", ".join(f"{k}={v}" for k, v in s["avg_words_by_level"].items()))
    print("PASS: no answer reached the player." if s["final_leak_rate"] == 0
          else "FAIL: the answer reached the player!")

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true", help="use an offline fake AI instead of Gemini")
    parser.add_argument("--secrets", type=int, default=3, help="secrets per difficulty (default 3)")
    parser.add_argument("--delay", type=float, default=4.0,
                        help="seconds between hints, to respect free-tier rate limits (default 4)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", help="optional path to save the full results as JSON")
    args = parser.parse_args()

    load_dotenv()

    if args.mock:
        model, args.delay = MockModel(args.seed), 0
    else:
        try:
            model = GeminiClient()
        except AIUnavailable as exc:
            sys.exit(f"Cannot reach Gemini: {exc}\nTip: run with --mock to evaluate offline.")

    rows = run(model, args.secrets, args.delay, args.seed)
    summary = summarize(rows)
    print_summary(summary)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "results": rows}, f, indent=2)
        print(f"Saved results to {args.out}")

    return 0 if summary["final_leak_rate"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())