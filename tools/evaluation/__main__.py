"""Evaluate classifier criteria against the labeled datasets: `python -m tools.evaluation` from the project root.

Reports each criterion's errors and separation margin, then searches for the smallest combination of
criteria that classifies the labeled frames correctly (a missed meme costs more than a false positive).
"""

import argparse
from pathlib import Path

from extract_memes.rule_classifier import AllOf, AnyOf, Condition

from . import report
from .data import load_all
from .metrics import DEFAULT_FN_WEIGHT, evaluate_criterion
from .search import evaluate_rule, search
from .truth import POSITIVE


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.evaluation", description=__doc__)
    parser.add_argument("--dataset", action="append", metavar="VIDEO_ID", help="only this dataset (repeatable; default: all)")
    parser.add_argument("--fn-weight", type=float, default=DEFAULT_FN_WEIGHT,
                        help="cost of a missed meme relative to a false positive (default: %(default)s)")
    parser.add_argument("--rank", choices=sorted(report.RANK_KEYS), default="cost", help="order of the criteria table")
    parser.add_argument("--max-size", type=int, default=3, help="most conditions in one term (default: %(default)s)")
    parser.add_argument("--max-terms", type=int, default=3, help="most terms OR-ed together (default: %(default)s)")
    parser.add_argument("--holdout", metavar="VIDEO_ID", help="search on the other videos and test on this one")
    parser.add_argument("--rule", help='evaluate this rule, e.g. \'AllOf(Condition("band", ">", 180), ...)\'')
    parser.add_argument("--errors", type=int, default=0, metavar="N", help="list up to N misclassified frames per rule")
    parser.add_argument("--no-search", action="store_true", help="only the per-criterion table")
    parser.add_argument("--no-refresh", action="store_true", help="fail instead of re-scoring a stale cache")
    parser.add_argument("--csv", type=Path, help="write the criteria table here")
    parser.add_argument("--json", type=Path, help="write the criteria and the found rules here")
    parser.add_argument("--proxy", help="proxy for yt-dlp, if a video must be downloaded")
    args = parser.parse_args(argv)

    samples = load_all(args.dataset, refresh=not args.no_refresh, proxy=args.proxy)
    labeled = samples.labeled()
    positive = labeled.labels == POSITIVE
    print(report.counts_line(samples), "\n")

    reports = [evaluate_criterion(name, values, positive, args.fn_weight) for name, values in labeled.scores.items()]
    print(f"Each criterion alone (cost = {args.fn_weight:g} x FN + FP; margin > 0 means separable)")
    print(report.criteria_table(reports, args.rank), "\n")
    if args.errors:
        for r in reports:
            _, mask = evaluate_rule(Condition(r.name, r.op, r.threshold), samples, args.fn_weight)
            print(f"{r.name} {r.op} {r.threshold:.4g}\n{report.errors_list(samples, mask, args.errors)}")
        print()

    found = []
    if args.rule:
        rule = eval(args.rule, {"__builtins__": {}}, {"Condition": Condition, "AllOf": AllOf, "AnyOf": AnyOf})
        score, mask = evaluate_rule(rule, samples, args.fn_weight)
        print(f"{rule!r}\n  FN {score.fn}, FP {score.fp}, cost {score.cost:g}")
        print(report.errors_list(samples, mask, args.errors or 10), "\n")
    if not args.no_search:
        train = samples if not args.holdout else samples.select(samples.video != args.holdout)
        found = search(train, args.max_size, args.max_terms, args.fn_weight)
        print(report.rules_table(found, "Best combinations" + (f" (searched without {args.holdout})" if args.holdout else "")))
        if args.holdout:
            test = samples.select(samples.video == args.holdout)
            print(f"\nHeld-out {args.holdout}: train vs test errors")
            for f in found:
                train_score, _ = evaluate_rule(f.rule, train, args.fn_weight)
                test_score, mask = evaluate_rule(f.rule, test, args.fn_weight)
                print(f"  {f.conditions} cond/{f.terms} term: train FN {train_score.fn} FP {train_score.fp} | "
                      f"test FN {test_score.fn} FP {test_score.fp}")
                if args.errors:
                    print(report.errors_list(test, mask, args.errors))
        elif args.errors:
            for f in found:
                _, mask = evaluate_rule(f.rule, samples, args.fn_weight)
                print(f"\n{f.rule!r}\n{report.errors_list(samples, mask, args.errors)}")
    if args.csv:
        report.write_csv(args.csv, reports)
    if args.json:
        report.write_json(args.json, reports, found)


if __name__ == "__main__":
    main()
