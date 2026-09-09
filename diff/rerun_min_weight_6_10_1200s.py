"""Rerun direct bit-level RKDiff minimum-weight search for rounds 6..10."""

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).with_name("run_rkdiff_min_weight_from6.py")
spec = importlib.util.spec_from_file_location("min_weight_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

runner.START_ROUND = 6
runner.MAX_ROUND = 10
runner.TIME_LIMIT_SECONDS = 1200


def main():
    runner.DIFF_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for rounds in range(runner.START_ROUND, runner.MAX_ROUND + 1):
        runner.round_dir(rounds).mkdir(parents=True, exist_ok=True)
        json_path = runner.target_json(rounds)
        txt_path = runner.target_txt(rounds)
        print(f"[{rounds}] direct RKDiff min-weight search with 1200s")
        try:
            result, stdout = runner.run_round(rounds)
        except Exception as exc:
            import traceback

            result = {
                "rounds": rounds,
                "mode": "direct_bit_level_rkdiff_min_weight",
                "start_weight": runner.START_WEIGHT,
                "time_limit_seconds": runner.TIME_LIMIT_SECONDS,
                "status": None,
                "status_name": "ERROR",
                "weight": None,
                "time_seconds": 0,
                "lp_file": None,
                "trail": None,
                "error": repr(exc),
            }
            stdout = traceback.format_exc()
        runner.write_json(json_path, result)
        with open(txt_path, "w", encoding="utf-8") as handle:
            handle.write(stdout)

    # Rebuild the 6..15 summary from the current per-round files.
    runner.START_ROUND = 6
    runner.MAX_ROUND = 15
    rows = []
    for rounds in range(runner.START_ROUND, runner.MAX_ROUND + 1):
        json_path = runner.target_json(rounds)
        if json_path.exists():
            rows.append(runner.row_from_result(runner.read_json(json_path)))
    runner.write_summary(rows)


if __name__ == "__main__":
    main()
