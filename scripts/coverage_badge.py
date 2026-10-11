#!/usr/bin/env python3
"""
Write docs/imgs/coverage.svg from the last ``coverage run`` (standard library only).

    coverage run -m pytest && python scripts/coverage_badge.py

The badge has the same look as the one from the coverage-badge package, which no longer works on recent
Pythons (it imports pkg_resources).
"""

import json
import subprocess
import sys
from pathlib import Path

TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="99" height="20">
    <linearGradient id="b" x2="0" y2="100%">
        <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
        <stop offset="1" stop-opacity=".1"/>
    </linearGradient>
    <mask id="a">
        <rect width="99" height="20" rx="3" fill="#fff"/>
    </mask>
    <g mask="url(#a)">
        <path fill="#555" d="M0 0h63v20H0z"/>
        <path fill="{color}" d="M63 0h36v20H63z"/>
        <path fill="url(#b)" d="M0 0h99v20H0z"/>
    </g>
    <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
        <text x="31.5" y="15" fill="#010101" fill-opacity=".3">coverage</text>
        <text x="31.5" y="14">coverage</text>
        <text x="80" y="15" fill="#010101" fill-opacity=".3">{percent}%</text>
        <text x="80" y="14">{percent}%</text>
    </g>
</svg>
"""

COLORS = [(95, "#4c1"), (90, "#97CA00"), (75, "#a4a61d"), (60, "#dfb317"), (40, "#fe7d37"), (0, "#e05d44")]


def total_percent() -> int:
    report = subprocess.run(
        [sys.executable, "-m", "coverage", "json", "-o", "-", "-q"], check=True, capture_output=True, text=True
    ).stdout
    return int(round(json.loads(report)["totals"]["percent_covered"]))


def main(argv) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path("docs/imgs/coverage.svg")
    percent = total_percent()
    color = next(c for threshold, c in COLORS if percent >= threshold)
    out.write_text(TEMPLATE.format(percent=percent, color=color))
    print(f"coverage {percent}% -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
