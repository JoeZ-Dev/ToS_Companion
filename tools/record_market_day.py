#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from momentum_companion.recording.market_day import MarketDayRecorder, SchwabMarketDayRunner


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record Schwab Level 1 for one or more symbols until 3:00 PM ET."
    )
    parser.add_argument("symbols", nargs="+", help="Symbols, e.g. AEHL TOPS DDC")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Optional recording root (default: ~/.tos_companion/recordings)",
    )
    parser.add_argument(
        "--probe-timesales",
        action="store_true",
        help=(
            "EXPERIMENTAL: also request undocumented TIMESALE_EQUITY. "
            "Do not assume Schwab supports this service."
        ),
    )
    args = parser.parse_args()

    recorder = MarketDayRecorder(args.symbols, output_root=args.output_root)
    runner = SchwabMarketDayRunner(recorder, probe_timesales=args.probe_timesales)
    try:
        session_dir = runner.run()
    except KeyboardInterrupt:
        runner.stop()
        recorder.close(stop_reason="keyboard_interrupt")
        session_dir = recorder.session_dir
    print(f"Recording saved: {session_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
