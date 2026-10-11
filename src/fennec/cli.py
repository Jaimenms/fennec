"""Command line: ``python -m fennec scenario.json --output results.json [--plot results.png]``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from .examples import SCENARIOS
from .scenario import load_scenario, results_to_dict, solver_options


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fennec", description="Fennec home energy optimizer")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("scenario", nargs="?", help="path to a JSON scenario (see fennec.scenario)")
    source.add_argument("--example", choices=sorted(SCENARIOS), help="run one of the built-in scenarios")
    p.add_argument("-o", "--output", help="write the results as JSON to this path")
    p.add_argument("--plot", help="save a dispatch figure to this path (requires matplotlib)")
    p.add_argument("--time-limit", type=float, default=None, help="solver time limit in seconds")
    p.add_argument("--gap", type=float, default=None, help="relative MIP gap")
    p.add_argument("--tee", action="store_true", help="show the solver log")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    options = {}
    if args.example:
        home = SCENARIOS[args.example]()
    else:
        home = load_scenario(args.scenario)
        with open(args.scenario, "r", encoding="utf-8") as f:
            options = solver_options(json.load(f))
    if args.time_limit is not None:
        options["time_limit"] = args.time_limit
    if args.gap is not None:
        options["mip_rel_gap"] = args.gap
    if args.tee:
        options["tee"] = True

    results = home.solve(**options)
    summary = results.summary()
    for key, value in summary.items():
        print(f"{key:>24}: {value}")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results_to_dict(results), f, indent=2)
        print(f"results written to {args.output}")

    if args.plot:
        import matplotlib

        matplotlib.use("Agg")  # headless: write the file, never open a window
        from .utils.plotting import plot_dispatch

        fig = plot_dispatch(results)
        fig.savefig(args.plot, dpi=150, bbox_inches="tight")
        print(f"figure written to {args.plot}")

    return 0 if results.feasible else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
