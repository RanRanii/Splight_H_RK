#!/usr/bin/env python3

"""Run the existing RK probability experiments from an already saved result."""

from argparse import ArgumentParser
import json
import os
from pathlib import Path
import re
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


def _rounds_from_case_name(case_name):
    match = re.fullmatch(r"(\d+)-(\d+)-(\d+)(?:_\d+)?", str(case_name))
    if match is None:
        raise ValueError(
            "probability result directory name must be "
            "<r0>-<rm>-<r1> or <r0>-<rm>-<r1>_<w0><wm><w1>"
        )
    r0, rm, r1 = (int(value) for value in match.groups())
    return {"r0": r0, "rm": rm, "r1": r1}


def probability_report_stem(summary, case_name):
    rounds = summary.get("rounds") or _rounds_from_case_name(case_name)
    return f"{int(rounds['r0'])}-{int(rounds['rm'])}-{int(rounds['r1'])}"


def _display(value, digits=None):
    if value is None:
        return "n/a"
    if digits is not None:
        try:
            return f"{float(value):.{digits}f}"
        except (TypeError, ValueError):
            pass
    return str(value)


def _experiment_status(entry):
    if not entry:
        return "UNAVAILABLE"
    if entry.get("skipped"):
        return "SKIPPED"
    if entry.get("probability") is None:
        return "UNAVAILABLE"
    return "SUCCESS"


def _right_total(entry, right_key="right"):
    if not entry:
        return "n/a"
    right = entry.get(right_key)
    total = entry.get("total")
    if right is None or total is None:
        return "n/a"
    return f"{right} / {total}"


def _middle_theory_log2(middle):
    if not middle:
        return "n/a"
    lower = middle.get("hadipour_lower_log2")
    upper = middle.get("hadipour_upper_log2")
    if lower is None or upper is None:
        return "n/a"
    if float(lower) == float(upper):
        return _display(lower, 6)
    return f"[{_display(lower, 6)}, {_display(upper, 6)}]"


def _error_message(error):
    lines = [line.strip() for line in str(error or "").splitlines() if line.strip()]
    return lines[-1] if lines else "Unknown error"


def render_probability_markdown(summary, case_name, probability_log_exists=True):
    stem = probability_report_stem(summary, case_name)
    status = summary.get("status", "UNKNOWN")
    lines = [
        f"# Splight-RK Probability Summary: {stem}",
        "",
        "## Overall Result",
        "",
        f"- Status: `{status}`",
        f"- Result case: `{case_name}`",
    ]

    if status != "SUCCESS":
        lines.extend([
            f"- Elapsed time: `{_display(summary.get('elapsed_seconds'), 6)} seconds`",
            "",
            "## Error",
            "",
            f"`{_error_message(summary.get('error'))}`",
            "",
            "## Related Files",
            "",
            (
                f"- Full probability log: `{stem}_rk_probtest.txt`"
                if probability_log_exists
                else "- Full probability log: not generated"
            ),
            "- Terminal output: `terminal_print.txt`",
            "- Summary JSON: `summary.json`",
            "",
        ])
        return "\n".join(lines)

    trail_source = summary.get("trail_source") or {}
    if isinstance(trail_source, dict):
        source_name = trail_source.get("source", "unknown")
    else:
        source_name = str(trail_source)
    accepted_id = summary.get("accepted_truncated_id")
    accepted_path = (
        f"truncated_{int(accepted_id):04d}" if accepted_id is not None else "n/a"
    )
    parameters = summary.get("probability_test_parameters") or {}
    upper = summary.get("upper_differential_probability") or {}
    middle = summary.get("middle_boomerang_probability") or {}
    lower = summary.get("lower_differential_probability") or {}
    total = summary.get("estimated_total_boomerang_probability") or {}
    bounds = summary.get("theoretical_total_boomerang_bounds") or {}

    lines.extend([
        f"- Trail source: `{source_name}`",
        f"- Accepted truncated path: `{accepted_path}`",
        f"- Random seed: `{_display(parameters.get('seed'))}`",
        f"- Elapsed time: `{_display(summary.get('elapsed_seconds'), 6)} seconds`",
        "",
        "## Boomerang Probability",
        "",
        "| Component | Symbol | Theoretical log2 | Experimental log2 | Right / Total | Status |",
        "|---|---:|---:|---:|---:|---|",
        "| Upper differential | $p$ | `{}` | `{}` | `{}` | `{}` |".format(
            _display(upper.get("theory_log2"), 6),
            _display(upper.get("log2_probability"), 6),
            _right_total(upper),
            _experiment_status(upper),
        ),
        "| Middle switch | $r$ | `{}` | `{}` | `{}` | `{}` |".format(
            _middle_theory_log2(middle),
            _display(middle.get("log2_r"), 6),
            _right_total(middle, "returned_count"),
            _experiment_status({
                "skipped": middle.get("skipped"),
                "probability": middle.get("estimated_r"),
            }),
        ),
        "| Lower differential | $q$ | `{}` | `{}` | `{}` | `{}` |".format(
            _display(lower.get("theory_log2"), 6),
            _display(lower.get("log2_probability"), 6),
            _right_total(lower),
            _experiment_status(lower),
        ),
        "",
    ])

    total_log2 = total.get("log2_probability")
    if total.get("available") and total_log2 is not None:
        lines.append(
            "- Experimental estimate: "
            f"$\\hat p^2 \\times \\hat r \\times \\hat q^2 = "
            f"2^{{{float(total_log2):.6f}}}$"
        )
    else:
        lines.append(
            "- Experimental estimate: unavailable"
            + (f" (`{total.get('reason')}`)" if total.get("reason") else "")
        )
    lower_bound = bounds.get("lower_log2_bound")
    upper_bound = bounds.get("upper_log2_bound")
    if lower_bound is not None and upper_bound is not None:
        lines.append(
            f"- Theoretical bound: $2^{{{float(lower_bound):.6f}}} "
            f"\\leq p^2rq^2 \\leq 2^{{{float(upper_bound):.6f}}}$"
        )

    lines.extend([
        "",
        "## Upper Related-Key Differential",
        "",
        f"- Rounds: `{_display(upper.get('rounds'))}`",
        f"- Round offset: `{_display(upper.get('round_offset'))}`",
        f"- Input difference: `{_display(upper.get('input_diff'))}`",
        f"- Output difference: `{_display(upper.get('output_diff'))}`",
        f"- Master-key difference: `{_display(upper.get('key_diff'))}`",
        f"- Data size: `{_display(upper.get('data_size'))}`",
        f"- Right pairs: `{_display(upper.get('right'))}`",
        f"- Probability: `{_display(upper.get('probability'))}`",
        f"- $\\log_2$ probability: `{_display(upper.get('log2_probability'), 6)}`",
        "",
        "## Middle Related-Key Boomerang Switch",
        "",
        f"- Rounds: `{_display(middle.get('rounds'))}`",
        f"- Round offset: `{_display(middle.get('round_offset'))}`",
        f"- $\\Delta$: `{_display(middle.get('input_diff_delta'))}`",
        f"- $\\nabla$: `{_display(middle.get('output_diff_nabla'))}`",
        f"- Forward key difference: `{_display(middle.get('delta_key_diff'))}`",
        f"- Backward key difference: `{_display(middle.get('nabla_key_diff'))}`",
        f"- Common active S-boxes: `{_display(middle.get('common_active_sboxes'))}`",
        f"- Data size: `{_display(middle.get('data_size'))}`",
        f"- Right quartets: `{_display(middle.get('returned_count'))}`",
        f"- Probability: `{_display(middle.get('estimated_r'))}`",
        f"- $\\log_2$ probability: `{_display(middle.get('log2_r'), 6)}`",
        "",
        "## Lower Related-Key Differential",
        "",
        f"- Rounds: `{_display(lower.get('rounds'))}`",
        f"- Round offset: `{_display(lower.get('round_offset'))}`",
        f"- Input difference: `{_display(lower.get('input_diff'))}`",
        f"- Output difference: `{_display(lower.get('output_diff'))}`",
        f"- Master-key difference: `{_display(lower.get('key_diff'))}`",
        f"- Data size: `{_display(lower.get('data_size'))}`",
        f"- Right pairs: `{_display(lower.get('right'))}`",
        f"- Probability: `{_display(lower.get('probability'))}`",
        f"- $\\log_2$ probability: `{_display(lower.get('log2_probability'), 6)}`",
        "",
        "## Related Files",
        "",
        f"- Full probability log: `{stem}_rk_probtest.txt`",
        "- Machine-readable result: `.json/rk_probability_tests.json`",
        "- Aligned key schedule: `aligned_key_schedule.txt`",
        "- Forward key difference: `delta_keydiff_forward.txt`",
        "- Backward key difference: `nabla_keydiff_backward.txt`",
        "- Terminal output: `terminal_print.txt`",
        "- Summary JSON: `summary.json`",
        "",
    ])
    return "\n".join(lines)


def write_probability_markdown(output_dir, summary):
    output_dir = Path(output_dir)
    stem = probability_report_stem(summary, output_dir.name)
    path = output_dir / f"{stem}_prob.md"
    path.write_text(
        render_probability_markdown(
            summary,
            output_dir.name,
            probability_log_exists=(output_dir / f"{stem}_rk_probtest.txt").is_file(),
        ),
        encoding="utf-8",
    )
    return path


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
    upper_trail = recovered_result.get("diff_upper_trail") or {}
    lower_trail = recovered_result.get("diff_lower_trail") or {}
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
        "upper_master_key_diff": upper_trail.get("master_key_diff"),
        "lower_master_key_diff": lower_trail.get("master_key_diff"),
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
    case_rounds = _rounds_from_case_name(result_dir.name)
    report_stem = probability_report_stem({"rounds": case_rounds}, result_dir.name)
    probability_log_name = f"{report_stem}_rk_probtest.txt"

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
                text_filename=probability_log_name,
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
            legacy_log_path = output_dir / "rk_probability_tests.txt"
            if legacy_log_path.is_file():
                legacy_log_path.unlink()
            markdown_path = write_probability_markdown(output_dir, summary)
            print(f"Saved: {summary_path}")
            print(f"Saved: {markdown_path}")
            return summary
        except Exception:
            elapsed_seconds = perf_counter() - started
            failure_summary = {
                "status": "FAILURE",
                "result_case": result_dir.name,
                "result_dir": str(result_dir),
                "rounds": case_rounds,
                "elapsed_seconds": elapsed_seconds,
                "error": traceback.format_exc(),
            }
            _write_json(summary_path, failure_summary)
            write_probability_markdown(output_dir, failure_summary)
            traceback.print_exc()
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
