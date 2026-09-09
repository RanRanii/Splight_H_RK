#!/usr/bin/env python3
"""CLI wrapper for a single RKDiff search."""

from argparse import ArgumentParser
import json
from pathlib import Path
import sys


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
from rkdiff import RKDiff


def main():
    parser = ArgumentParser()
    parser.add_argument("--rounds", type=int, required=True)
    parser.add_argument("--time-limit", type=int, default=120)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else BASE_DIR / "results" / "rkdiff_2_11"
    out_dir.mkdir(parents=True, exist_ok=True)
    diff = RKDiff({
        "nrounds": args.rounds,
        "timelimit": args.time_limit,
        "mode": 0,
        "startweight": 0,
        "endweight": 512,
        "numberoftrails": 1,
    })
    diff.make_model()
    trail = diff.solve()
    if trail is None:
        raise SystemExit(1)
    path = out_dir / f"rkdiff_{args.rounds}r.json"
    path.write_text(json.dumps(trail, indent=2), encoding="utf-8")
    txt_path = out_dir / f"rkdiff_{args.rounds}r.txt"
    lines = [
        "Related-key differential trail:",
        "Rounds  x                 y         l         RK        ak        z         KS                                  pr      rw      kw     ",
        "-" * 132,
    ]
    round_offset = int(trail.get("round_offset", 0))
    for r in range(trail["nrounds"] + 1):
        ks = trail.get(
            f"round_ks_{r}",
            trail.get(f"ks_global_{round_offset + r + 1}", "none") if r < trail["nrounds"] else "none",
        )
        lines.append(
            f"{r:<7} {trail.get(f'x_{r}', 'none'):<17} {trail.get(f'y_{r}', 'none'):<9} "
            f"{trail.get(f'l_{r}', 'none'):<9} {trail.get(f'rk_{r}', 'none'):<9} "
            f"{trail.get(f'ak_{r}', 'none'):<9} {trail.get(f'z_{r}', 'none'):<9} "
            f"{ks:<35} "
            f"{trail.get(f'pr_{r}', 'none'):<7} {trail.get(f'rw_{r}', 'none'):<7} {trail.get(f'kw_{r}', 'none'):<7}"
        )
    lines.append(f"Master key diff: {trail.get('master_key_diff', 'none')}")
    lines.append(f"Weight: -{trail.get('total_weight', '0')}")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
