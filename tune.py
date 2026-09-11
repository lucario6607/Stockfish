"""
Stockfish Bayesian Optimization Tuner using Optuna and cutechess-cli.
Tunes exact singular extension margins (exactSingleMargin, exactDoubleMargin, exactTripleMargin).
"""

import argparse
import os
import re
import subprocess
import sys
import optuna

DEFAULT_CUTECHESS = r"C:\Program Files (x86)\Cute Chess\cutechess-cli.exe"
DEFAULT_BASE = r"stockfish_master.exe"
DEFAULT_TUNED = r"stockfish_optuna.exe"
DEFAULT_BOOK = r"books\UHO_Lichess_4852_v1.epd"
DEFAULT_DB = r"sqlite:///optuna_tune.db"
DEFAULT_STUDY_NAME = "singular_margins_tune"

def parse_cutechess_output(output: str):
    """
    Parses cutechess-cli match output for:
    Score of Candidate vs Base: W - L - D  [score] total
    """
    pattern = r"Score of Candidate vs Base:\s+(\d+)\s+-\s+(\d+)\s+-\s+(\d+)\s+\[([0-9\.]+)\]\s+(\d+)"
    matches = re.findall(pattern, output)
    if matches:
        last = matches[-1]
        w, l, d = int(last[0]), int(last[1]), int(last[2])
        score = float(last[3])
        total = int(last[4])
        return w, l, d, score, total

    # Fallback to counting results if final score line not captured
    w = len(re.findall(r"Finished game \d+ \(Candidate vs Base\): 1-0", output)) + \
        len(re.findall(r"Finished game \d+ \(Base vs Candidate\): 0-1", output))
    l = len(re.findall(r"Finished game \d+ \(Candidate vs Base\): 0-1", output)) + \
        len(re.findall(r"Finished game \d+ \(Base vs Candidate\): 1-0", output))
    d = len(re.findall(r"Finished game \d+ .*: 1/2-1/2", output))
    total = w + l + d
    score = (w + 0.5 * d) / total if total > 0 else 0.5
    return w, l, d, score, total

def run_match(args, single_m: int, double_m: int, triple_m: int, rounds: int):
    """
    Runs a match between Candidate (stockfish_optuna) and Base (stockfish_master).
    Each round plays 2 games (color-swapped) per opening to eliminate color bias.
    """
    cmd = [
        args.cutechess,
        "-engine", f"cmd={args.tuned}", "name=Candidate", "proto=uci",
        f"option.exactSingleMargin={single_m}",
        f"option.exactDoubleMargin={double_m}",
        f"option.exactTripleMargin={triple_m}",
        "-engine", f"cmd={args.base}", "name=Base", "proto=uci",
        "-each", f"tc={args.tc}",
        "-rounds", str(rounds),
        "-games", "2",
        "-repeat",
        "-recover",
        "-concurrency", str(args.concurrency),
        "-openings", f"file={args.book}", "format=epd", "order=random"
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=os.getcwd())
    output = proc.stdout + "\n" + proc.stderr

    if proc.returncode != 0 and "Finished match" not in output:
        print(f"[ERROR] cutechess-cli error:\n{output[-500:]}", file=sys.stderr)
        raise RuntimeError("cutechess-cli match failed")

    return parse_cutechess_output(output)

def make_objective(args):
    def objective(trial: optuna.Trial):
        # Sample parameters using Tree-structured Parzen Estimator (TPE)
        single_m = trial.suggest_int("exactSingleMargin", 0, 36)
        double_m = trial.suggest_int("exactDoubleMargin", -18, 18)
        triple_m = trial.suggest_int("exactTripleMargin", -18, 18)

        rounds = max(1, args.games // 2)
        total_games = rounds * 2

        print(f"\n[Trial #{trial.number}] Testing: single={single_m}, double={double_m}, triple={triple_m} ({total_games} games)...")
        w, l, d, score, total = run_match(args, single_m, double_m, triple_m, rounds)

        # Elo difference approximation: Elo = -400 * log10(1/score - 1)
        import math
        elo_str = "0.0"
        if 0.0 < score < 1.0:
            elo = -400.0 * math.log10((1.0 / score) - 1.0)
            elo_str = f"{elo:+.1f}"
        elif score == 1.0:
            elo_str = "+inf"
        elif score == 0.0:
            elo_str = "-inf"

        print(f"  -> Result: +{w} -{l} ={d} | Score: {score*100:.1f}% ({elo_str} Elo) over {total} games")

        # Record extra trial metadata
        trial.set_user_attr("wins", w)
        trial.set_user_attr("losses", l)
        trial.set_user_attr("draws", d)
        trial.set_user_attr("elo", elo_str)

        return score
    return objective

def main():
    parser = argparse.ArgumentParser(description="Optuna Bayesian Tuner for Stockfish Singular Extension Margins")
    parser.add_argument("--cutechess", default=DEFAULT_CUTECHESS, help="Path to cutechess-cli.exe")
    parser.add_argument("--base", default=DEFAULT_BASE, help="Path to baseline stockfish_master.exe")
    parser.add_argument("--tuned", default=DEFAULT_TUNED, help="Path to tuned stockfish_optuna.exe")
    parser.add_argument("--book", default=DEFAULT_BOOK, help="Path to opening book (EPD)")
    parser.add_argument("--tc", default="2+0.02", help="Time control (e.g. 2+0.02 or 1+0.01)")
    parser.add_argument("--games", type=int, default=30, help="Total games per trial (will be rounded to even number)")
    parser.add_argument("--trials", type=int, default=50, help="Number of Optuna trials to run")
    parser.add_argument("--concurrency", type=int, default=8, help="Number of concurrent games")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path for persistence")
    parser.add_argument("--study-name", default=DEFAULT_STUDY_NAME, help="Optuna study name")
    parser.add_argument("--analyze", action="store_true", help="Print summary of existing study and best trials")

    args = parser.parse_args()

    # Validate file dependencies
    for label, path in [("cutechess-cli", args.cutechess), ("Baseline engine", args.base),
                        ("Tuned engine", args.tuned), ("Opening book", args.book)]:
        if not os.path.exists(path):
            print(f"[ERROR] {label} not found at: {path}", file=sys.stderr)
            sys.exit(1)

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    study = optuna.create_study(
        study_name=args.study_name,
        storage=args.db,
        load_if_exists=True,
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42)
    )

    if args.analyze:
        print(f"\n=== Study Summary: {args.study_name} ===")
        print(f"Total Trials: {len(study.trials)}")
        if study.trials:
            sorted_trials = sorted([t for t in study.trials if t.value is not None], key=lambda t: t.value, reverse=True)
            print("\nTop 5 Trials:")
            for i, t in enumerate(sorted_trials[:5], 1):
                params = t.params
                w = t.user_attrs.get("wins", "?")
                l = t.user_attrs.get("losses", "?")
                d = t.user_attrs.get("draws", "?")
                elo = t.user_attrs.get("elo", "?")
                print(f"  #{i} Trial {t.number}: Score {t.value*100:.1f}% (+{w}-{l}={d}, {elo} Elo) | "
                      f"single={params.get('exactSingleMargin')}, double={params.get('exactDoubleMargin')}, triple={params.get('exactTripleMargin')}")
        return

    print("=" * 60)
    print(" STOCKFISH OPTUNA BAYESIAN TUNER")
    print("=" * 60)
    print(f"Baseline:     {args.base}")
    print(f"Candidate:    {args.tuned}")
    print(f"Book:         {args.book}")
    print(f"Time Control: {args.tc}")
    print(f"Games/Trial:  {args.games} (paired openings)")
    print(f"Concurrency:  {args.concurrency}")
    print(f"Trials:       {args.trials}")
    print(f"Database:     {args.db}")
    print("=" * 60)

    try:
        study.optimize(make_objective(args), n_trials=args.trials)
    except KeyboardInterrupt:
        print("\n[INFO] Tuning paused by user. Progress saved in database.")

    print("\n" + "=" * 60)
    print(" TUNING COMPLETE / BEST TRIAL")
    print("=" * 60)
    best = study.best_trial
    print(f"Best Trial #{best.number}")
    print(f"  Score: {best.value * 100:.2f}%")
    print(f"  Parameters:")
    for k, v in best.params.items():
        print(f"    {k}: {v}")
    print("=" * 60)

if __name__ == "__main__":
    main()
