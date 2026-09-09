#!/usr/bin/env python3

"""Run the existing RK probability experiments from an already saved result."""

from argparse import ArgumentParser
import json
import os
from pathlib import Path
import sys
from time import perf_counter
import traceback


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from probability.rk_probability_evaluator import (  # noqa: E402
    ResultRecoveryError,
    load_probability_input_from_result_dir,
    save_rk_probability_checks,
)
from rkboom import _tee_terminal_output  # noqa: E402


def _write_json(path, data):
    Path(path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _experiment_summary(entry):
    result = entry.get("result") if entry else None
    if result is None:
        return None
    return {
        "skipped": bool(result.get("skipped", False)),
        "rounds": result.get("rounds"),
        "round_offset": result.get("round_offset"),
        "input_diff": result.get("input_diff"),
        "output_diff": result.get("output_diff"),
        "key_diff": result.get("key_diff"),
        "probability": result.get("probability"),
        "log2_probability": result.get("log2_probability"),
        "theory_log2": result.get("theory_log2"),
        "data_size": result.get("data_size"),
        "data_size_count": result.get("data_size_count"),
        "right": result.get("right"),
        "total": result.get("total"),
        "reason": result.get("reason"),
    }


def _theoretical_boomerang_bounds(recovered_result):
    upper_weight = float(recovered_result["diff_upper_trail"]["total_weight"])
    lower_weight = float(recovered_result["diff_lower_trail"]["total_weight"])
    common_active = float(recovered_result["middle_part"]["as"])
    base = -2.0 * upper_weight - 2.0 * lower_weight
    return {
        "formula": "p^2*q^2*r",
        "lower_log2_bound": base - 2.5 * common_active,
        "upper_log2_bound": base - 2.0 * common_active,
        "common_active_sboxes": common_active,
    }


def _build_summary(result_dir, provenance, recovered_result, probability_result, elapsed_seconds):
    em = probability_result["rk_em_boomerang"]
    return {
        "status": "SUCCESS",
        "result_case": Path(result_dir).name,
        "result_dir": str(result_dir),
        "rounds": {
            "r0": int(recovered_result["parameters"]["r0"]),
            "rm": int(recovered_result["parameters"]["rm"]),
            "r1": int(recovered_result["parameters"]["r1"]),
        },
        "accepted_truncated_id": provenance.get("accepted_truncated_id"),
        "trail_source": provenance,
        "upper_master_key_diff": recovered_result["diff_upper_trail"].get("master_key_diff"),
        "lower_master_key_diff": recovered_result["diff_lower_trail"].get("master_key_diff"),
        "probability_test_parameters": probability_result.get("parameters", {}),
        "timelimit": recovered_result["parameters"].get("timelimit"),
        "upper_differential_probability": _experiment_summary(
            probability_result["rkdiff"].get("upper")
        ),
        "lower_differential_probability": _experiment_summary(
            probability_result["rkdiff"].get("lower")
        ),
        "middle_boomerang_probability": em,
        "estimated_total_boomerang_probability": probability_result[
            "total_boomerang_probability"
        ],
        "theoretical_total_boomerang_bounds": _theoretical_boomerang_bounds(
            recovered_result
        ),
        "elapsed_seconds": elapsed_seconds,
    }


def _build_argument_parser():
    parser = ArgumentParser(
        description=(
            "Run existing RK probability checks from a saved rkboom.py result. "
            "No truncated/RKDiff/Z3 search is run."
        )
    )
    parser.add_argument(
        "--result-dir",
        required=True,
        help="completed result directory, for example .\\results\\4-4-4_636 (legacy 4-4-4 is also supported)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="override the existing evaluator seed; default uses today's date",
    )
    parser.add_argument(
        "-tl",
        "--timelimit",
        type=int,
        default=None,
        help="override saved key-schedule MILP time limit; default uses saved rkboom parameter",
    )
    return parser


def main(argv=None):
    args = _build_argument_parser().parse_args(argv)
    result_dir = Path(args.result_dir).expanduser().resolve()
    if not result_dir.is_dir():
        raise SystemExit(f"result directory does not exist: {result_dir}")
    if args.timelimit is not None and args.timelimit <= 0:
        raise SystemExit("--timelimit must be greater than zero")

    os.chdir(PROJECT_DIR)
    output_dir = PROJECT_DIR / "probability_results" / result_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    summary_path = output_dir / "summary.json"

    with _tee_terminal_output(output_dir / "terminal_print.txt"):
        try:
            print("=" * 72)
            print("从已有结果执行相关密钥概率测试")
            print(f"result dir : {result_dir}")
            recovered_result, provenance = load_probability_input_from_result_dir(result_dir)
            if args.timelimit is not None:
                recovered_result["parameters"] = dict(recovered_result["parameters"])
                recovered_result["parameters"]["timelimit"] = args.timelimit
            if provenance.get("exact_recovery_error"):
                print("Exact accepted result is incomplete; use formal trail fallback:")
                print(provenance["exact_recovery_error"])
            print(f"trail source: {provenance['source']}")
            if provenance.get("accepted_truncated_id") is not None:
                print(f"accepted truncated id: {provenance['accepted_truncated_id']}")

            probability_result, probability_log = save_rk_probability_checks(
                recovered_result,
                output_dir,
                seed=args.seed,
            )
            print(probability_log, end="")
            summary = _build_summary(
                result_dir,
                provenance,
                recovered_result,
                probability_result,
                perf_counter() - started,
            )
            _write_json(summary_path, summary)
            print(f"Saved: {summary_path}")
            return summary
        except Exception:
            elapsed_seconds = perf_counter() - started
            _write_json(summary_path, {
                "status": "FAILURE",
                "result_case": result_dir.name,
                "result_dir": str(result_dir),
                "elapsed_seconds": elapsed_seconds,
                "error": traceback.format_exc(),
            })
            traceback.print_exc()
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
