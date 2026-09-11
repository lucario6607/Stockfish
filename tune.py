"""
Stockfish Bayesian Optimization Tuner using Optuna and cutechess-cli.
Configured for high-throughput, low-noise tuning at STC (10+0.1) across 22 threads.
"""

import argparse
import math
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

def parse_full_cutechess_output(output: str):
    """
    Extracts W-L-D, Score, Elo difference, error margin, LOS, and Draw Ratio.
    """
    w, l, d, score, total = 0, 0, 0, 0.5, 0
    elo, elo_err, los, draw_ratio = "0.0", "nan", "50.0%", "0.0%"

    score_match = re.findall(
        r"Score of Candidate vs Base:\s+(\d+)\s+-\s+(\d+)\s+-\s+(\d+)\s+\[([0-9\.]+)\]\s+(\d+)",
        output
    )
    if score_match:
        last = score_match[-1]
        w, l, d = int(last[0]), int(last[1]), int(last[2])
        score = float(last[3])
        total = int(last[4])
    else:
        # Fallback manual extraction
        w = len(re.findall(r"Finished game \d+ \(Candidate vs Base\): 1-0", output)) + \
            len(re.findall(r"Finished game \d+ \(Base vs Candidate\): 0-1", output))
        l = len(re.findall(r"Finished game \d+ \(Candidate vs Base\): 0-1", output)) + \
            len(re.findall(r"Finished game \d+ \(Base vs Candidate\): 1-0", output))
        d = len(re.findall(r"Finished game \d+ .*: 1/2-1/2", output))
        total = w + l + d
        score = (w + 0.5 * d) / total if total > 0 else 0.5

    elo_match = re.search(r"Elo difference:\s+([+-]?[0-9\.]+|[+-]?inf)\s+\+/-\s+([0-9\.]+|nan)", output)
    if elo_match:
        elo = elo_match.group(1)
        elo_err = elo_match.group(2)
    elif 0.0 < score < 1.0:
        raw_elo = -400.0 * math.log10((1.0 / score) - 1.0)
        elo = f"{raw_elo:+.1f}"

    los_match = re.search(r"LOS:\s+([0-9\.]+\s*%)", output)
    if los_match:
        los = los_match.group(1)

    dr_match = re.search(r"DrawRatio:\s+([0-9\.]+\s*%)", output)
    if dr_match:
        draw_ratio = dr_match.group(1)

    return {
        "wins": w,
        "losses": l,
        "draws": d,
        "score": score,
        "total": total,
        "elo": elo,
        "elo_err": elo_err,
        "los": los,
        "draw_ratio": draw_ratio,
    }

def run_match(args, single_m: int, double_m: int, triple_m: int, rounds: int, trial_num: int):
    """
    Runs a match between Candidate and Base with real-time game progress.
    Each round plays 2 games (color-swapped) per opening to cancel color bias.
    """
    total_games = rounds * 2
    cmd = [
        args.cutechess,
        "-engine", f"cmd={args.tuned}", "name=Candidate", "proto=uci",
        f"option.exactSingleMargin={single_m}",
        f"option.exactDoubleMargin={double_m}",
        f"option.exactTripleMargin={triple_m}",
        f"option.Hash={args.hash}",
        "-engine", f"cmd={args.base}", "name=Base", "proto=uci",
        f"option.Hash={args.hash}",
        "-each", f"tc={args.tc}",
        "-rounds", str(rounds),
        "-games", "2",
        "-repeat",
        "-recover",
        "-concurrency", str(args.concurrency),
        "-draw", "movenumber=40", "movecount=8", "score=10",
        "-resign", "movecount=5", "score=600",
        "-ratinginterval", "1",
        "-openings", f"file={args.book}", "format=epd", "order=random"
    ]

    captured_lines = []
    current_game = 0

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=os.getcwd()
    )

    for line in proc.stdout:
        captured_lines.append(line)
        if "Finished game" in line:
            current_game += 1
        elif "Score of Candidate vs Base:" in line:
            match = re.search(r"Score of Candidate vs Base:\s+(\d+)\s+-\s+(\d+)\s+-\s+(\d+)\s+\[([0-9\.]+)\]\s+(\d+)", line)
            if match:
                w, l, d, s, tot = match.groups()
                pct = float(s) * 100
                sys.stdout.write(f"\r  [Trial #{trial_num}] Progress: {tot}/{total_games} games | +{w} -{l} ={d} ({pct:.1f}%)")
                sys.stdout.flush()

    proc.wait()
    sys.stdout.write("\n")
    sys.stdout.flush()

    full_output = "".join(captured_lines)
    if proc.returncode != 0 and "Finished match" not in full_output:
        print(f"[ERROR] cutechess-cli error:\n{full_output[-600:]}", file=sys.stderr)
        raise RuntimeError("cutechess-cli match failed")

    return parse_full_cutechess_output(full_output)

def make_objective(args):
    def objective(trial: optuna.Trial):
        # Propose parameters using Tree-structured Parzen Estimator (TPE)
        single_m = trial.suggest_int("exactSingleMargin", 0, 36)
        double_m = trial.suggest_int("exactDoubleMargin", -18, 18)
        triple_m = trial.suggest_int("exactTripleMargin", -18, 18)

        rounds = max(1, args.games // 2)
        total_games = rounds * 2

        print(f"\n[Trial #{trial.number}] Params: single={single_m}, double={double_m}, triple={triple_m} | Match: {total_games} games @ {args.tc} on {args.concurrency} threads")
        res = run_match(args, single_m, double_m, triple_m, rounds, trial.number)

        elo_display = f"{res['elo']} +/- {res['elo_err']}" if res['elo_err'] != "nan" else f"{res['elo']}"
        print(f"  Result: +{res['wins']} -{res['losses']} ={res['draws']} ({res['total']} games) | "
              f"Score: {res['score']*100:.2f}% | Elo: {elo_display} | LOS: {res['los']} | Draws: {res['draw_ratio']}")

        # Save complete trial metrics to SQLite
        for k, v in res.items():
            trial.set_user_attr(k, v)

        return res["score"]
    return objective

def print_study_analysis(study):
    print("\n" + "=" * 75)
    print(f" STUDY SUMMARY: {study.study_name} (Total Trials: {len(study.trials)})")
    print("=" * 75)
    valid_trials = [t for t in study.trials if t.value is not None]
    if not valid_trials:
        print("No completed trials found in database.")
        return

    sorted_trials = sorted(valid_trials, key=lambda t: t.value, reverse=True)
    print(f"{'Rank':<5}{'Trial':<7}{'Score':<9}{'W-L-D':<14}{'Elo Diff':<18}{'LOS':<8}{'Single':<8}{'Double':<8}{'Triple':<8}")
    print("-" * 75)
    for i, t in enumerate(sorted_trials[:10], 1):
        p = t.params
        w = t.user_attrs.get("wins", "?")
        l = t.user_attrs.get("losses", "?")
        d = t.user_attrs.get("draws", "?")
        elo = t.user_attrs.get("elo", "?")
        err = t.user_attrs.get("elo_err", "nan")
        elo_str = f"{elo} +/- {err}" if err != "nan" else str(elo)
        los = t.user_attrs.get("los", "?")
        wld = f"+{w}-{l}={d}"
        print(f"#{i:<4}{t.number:<7}{t.value*100:>5.1f}%   {wld:<14}{elo_str:<18}{los:<8}"
              f"{p.get('exactSingleMargin', '?'):<8}{p.get('exactDoubleMargin', '?'):<8}{p.get('exactTripleMargin', '?'):<8}")

    print("=" * 75)
    best = study.best_trial
    print(f"Best Configuration: Trial #{best.number} (Score: {best.value*100:.2f}%)")
    print(f"  exactSingleMargin: {best.params.get('exactSingleMargin')}")
    print(f"  exactDoubleMargin: {best.params.get('exactDoubleMargin')}")
    print(f"  exactTripleMargin: {best.params.get('exactTripleMargin')}")
    print("=" * 75)

def main():
    parser = argparse.ArgumentParser(description="Stockfish Optuna Bayesian Tuner (High-Throughput STC)")
    parser.add_argument("--cutechess", default=DEFAULT_CUTECHESS, help="Path to cutechess-cli.exe")
    parser.add_argument("--base", default=DEFAULT_BASE, help="Path to baseline stockfish_master.exe")
    parser.add_argument("--tuned", default=DEFAULT_TUNED, help="Path to tuned stockfish_optuna.exe")
    parser.add_argument("--book", default=DEFAULT_BOOK, help="Path to opening book (EPD)")
    parser.add_argument("--tc", default="10+0.1", help="Time control (default: 10+0.1)")
    parser.add_argument("--games", type=int, default=88, help="Total games per trial (default: 88, rounded to even)")
    parser.add_argument("--trials", type=int, default=50, help="Number of Optuna trials (default: 50)")
    parser.add_argument("--concurrency", type=int, default=22, help="Concurrency (default: 22 threads)")
    parser.add_argument("--hash", type=int, default=16, help="Hash size per engine instance in MB (default: 16)")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path for persistence")
    parser.add_argument("--study-name", default=DEFAULT_STUDY_NAME, help="Optuna study name")
    parser.add_argument("--analyze", action="store_true", help="Print summary of top trials and best parameters")

    args = parser.parse_args()

    # Verify dependencies
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
        print_study_analysis(study)
        return

    print("=" * 70)
    print(" STOCKFISH OPTUNA BAYESIAN TUNER (HIGH-THROUGHPUT LOW-NOISE)")
    print("=" * 70)
    print(f"Baseline:     {args.base}")
    print(f"Candidate:    {args.tuned}")
    print(f"Book:         {args.book}")
    print(f"Time Control: {args.tc}")
    print(f"Games/Trial:  {args.games} (paired openings, White & Black)")
    print(f"Concurrency:  {args.concurrency} concurrent games")
    print(f"Hash / Inst:  {args.hash} MB (Total memory: ~{args.concurrency * 2 * args.hash} MB)")
    print(f"Trials:       {args.trials}")
    print(f"Adjudication: Draw (move 40, count 8, <=10cp) | Resign (count 5, >=600cp)")
    print(f"Database:     {args.db}")
    print("=" * 70)

    try:
        study.optimize(make_objective(args), n_trials=args.trials)
    except KeyboardInterrupt:
        print("\n[INFO] Tuning paused by user. Progress safely saved in database.")

    print_study_analysis(study)

if __name__ == "__main__":
    main()
