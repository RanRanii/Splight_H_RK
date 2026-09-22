#!/usr/bin/env python3

"""Related-key Hadipour-style Splight boomerang search entry.

This file intentionally follows the control flow and parameter style of
Paper_code/comeback-main/lblock/boom.py. The related-key cipher-specific parts
live in rktruncdiff.py, rktruncboom.py and rkdiff.py.
"""

from argparse import ArgumentParser, RawTextHelpFormatter
from contextlib import contextmanager
import json
import os
import re
import shutil
import sys
import threading
import traceback
from time import perf_counter

import yaml

from rktruncboom import RKTruncatedBoomerang
from rkdiff import RKDiff
from tools.rk_exact_verify import verify_trail
from output.plotdistinguisher import *
from probability.rk_probability_evaluator import save_rk_probability_checks


def result_case_dir_name(params):
    """Return the result directory name without changing artifact basenames."""
    rounds = f"{params['r0']}-{params['rm']}-{params['r1']}"
    weights = f"{params['w0']}{params['wm']}{params['w1']}"
    return f"{rounds}_{weights}"


def _remaining_solve_seconds(deadline):
    if deadline is None:
        return None
    return max(0.0, deadline - perf_counter())


def _effective_time_limit(deadline, local_limit=None):
    remaining = _remaining_solve_seconds(deadline)
    if remaining is not None and remaining <= 0:
        return 0.0
    if local_limit is None:
        return remaining
    return float(local_limit) if remaining is None else min(float(local_limit), remaining)


class _InstantiationLpCleaner:
    """Delete only rejected RKDiff LP files created and registered in this run."""

    _LP_NAME = re.compile(r"splight_h_rkdiff_\d+_\d+\.lp")

    def __init__(self, root=None):
        default_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp", "boomerang")
        self.root = os.path.realpath(root or default_root)
        self._owned = {}
        self._stats = {
            "policy": "delete-definitively-rejected-current-run-only",
            "registered_files": 0,
            "deleted_files": 0,
            "deleted_bytes": 0,
            "refused_files": 0,
            "delete_failures": 0,
        }

    def _resolve_safe_path(self, diff):
        raw_path = getattr(diff, "lp_file_name", None)
        if not raw_path:
            return None
        path = os.path.realpath(raw_path)
        try:
            inside_root = os.path.commonpath((self.root, path)) == self.root
        except ValueError:
            inside_root = False
        if not inside_root or self._LP_NAME.fullmatch(os.path.basename(path)) is None:
            return None
        return path

    @staticmethod
    def _file_identity(stat_result):
        return (
            stat_result.st_dev,
            stat_result.st_ino,
            stat_result.st_size,
            stat_result.st_mtime_ns,
        )

    def register(self, diff):
        """Register one newly created LP; unregistered historical files stay untouchable."""
        path = self._resolve_safe_path(diff)
        if path is None:
            if getattr(diff, "lp_file_name", None):
                self._stats["refused_files"] += 1
                print(f"LP cleanup registration refused: {diff.lp_file_name}")
            return False
        try:
            stat_result = os.stat(path)
        except OSError as exc:
            self._stats["refused_files"] += 1
            print(f"LP cleanup registration failed: path={path} error={exc}")
            return False
        self._owned[path] = self._file_identity(stat_result)
        self._stats["registered_files"] += 1
        return True

    def delete(self, diff, reason):
        """Delete a registered LP if it is still the exact file that was registered."""
        path = self._resolve_safe_path(diff)
        if path is None or path not in self._owned:
            return False
        registered_identity = self._owned[path]
        try:
            current_stat = os.stat(path)
            if self._file_identity(current_stat) != registered_identity:
                self._stats["refused_files"] += 1
                print(f"LP cleanup refused changed file: path={path} reason={reason}")
                return False

            model = getattr(diff, "milp_model", None)
            dispose = getattr(model, "dispose", None)
            if callable(dispose):
                dispose()
            if hasattr(diff, "milp_model"):
                diff.milp_model = None

            os.remove(path)
            self._owned.pop(path, None)
            self._stats["deleted_files"] += 1
            self._stats["deleted_bytes"] += current_stat.st_size
            return True
        except FileNotFoundError:
            self._owned.pop(path, None)
            return False
        except OSError as exc:
            self._stats["delete_failures"] += 1
            print(f"LP cleanup warning: path={path} reason={reason} error={exc}")
            return False

    def delete_many(self, diffs, reason):
        deleted_before = self._stats["deleted_files"]
        bytes_before = self._stats["deleted_bytes"]
        for diff in diffs:
            self.delete(diff, reason)
        return {
            "deleted_files": self._stats["deleted_files"] - deleted_before,
            "deleted_bytes": self._stats["deleted_bytes"] - bytes_before,
        }

    def snapshot(self):
        return {
            **self._stats,
            "retained_registered_files": len(self._owned),
        }


class _TeeTextStream:
    """Mirror text writes to the original terminal stream and one log file."""

    def __init__(self, terminal_stream, log_stream, lock):
        self._terminal_stream = terminal_stream
        self._log_stream = log_stream
        self._lock = lock

    def write(self, text):
        with self._lock:
            terminal_result = self._terminal_stream.write(text)
            self._log_stream.write(text)
        return terminal_result

    def flush(self):
        with self._lock:
            self._terminal_stream.flush()
            self._log_stream.flush()

    def __getattr__(self, name):
        return getattr(self._terminal_stream, name)


@contextmanager
def _tee_terminal_output(log_path):
    """Keep normal terminal output while recording stdout and stderr in order."""

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    lock = threading.RLock()
    with open(log_path, "w", encoding="utf-8", buffering=1) as log_stream:
        sys.stdout = _TeeTextStream(original_stdout, log_stream, lock)
        sys.stderr = _TeeTextStream(original_stderr, log_stream, lock)
        try:
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            sys.stdout = original_stdout
            sys.stderr = original_stderr


def diff_trail_to_lines(diff_trail):
    if diff_trail is None:
        return []
    lines = ["Rounds  x                 y         l         RK        ak        z         KS                                  pr      rw      kw     ",
             "-" * 132]
    round_offset = int(diff_trail.get("round_offset", 0))
    for r in range(diff_trail["nrounds"] + 1):
        ks = diff_trail.get(
            f"round_ks_{r}",
            diff_trail.get(f"ks_global_{round_offset + r + 1}", "none") if r < diff_trail["nrounds"] else "none",
        )
        lines.append(
            f"{r:<7} "
            f"{diff_trail.get(f'x_{r}', 'none'):<17} "
            f"{diff_trail.get(f'y_{r}', 'none'):<9} "
            f"{diff_trail.get(f'l_{r}', 'none'):<9} "
            f"{diff_trail.get(f'rk_{r}', 'none'):<9} "
            f"{diff_trail.get(f'ak_{r}', 'none'):<9} "
            f"{diff_trail.get(f'z_{r}', 'none'):<9} "
            f"{ks:<35} "
            f"{diff_trail.get(f'pr_{r}', 'none'):<7} "
            f"{diff_trail.get(f'rw_{r}', 'none'):<7} "
            f"{diff_trail.get(f'kw_{r}', 'none'):<7}"
        )
    lines.append(f"Master key diff: {diff_trail.get('master_key_diff', 'none')}")
    lines.append(f"Weight: -{diff_trail.get('total_weight', '0')}")
    return lines


def truncated_trail_to_lines(trail, nrounds):
    lines = ["Rounds  x                 y         l         RK        ak        z        ",
             "-" * 76]
    for r in range(nrounds + 1):
        lines.append(
            f"{r:<7} "
            f"{trail.get(f'x_{r}', ''):<17} "
            f"{trail.get(f'y_{r}', 'none'):<9} "
            f"{trail.get(f'l_{r}', 'none'):<9} "
            f"{trail.get(f'rk_{r}', 'none'):<9} "
            f"{trail.get(f'ak_{r}', 'none'):<9} "
            f"{trail.get(f'z_{r}', 'none'):<9}"
        )
    return lines


def apply_truncated_state_mask(diff_params, local_round, mask):
    for nibble, flag in enumerate(mask):
        if flag == "0":
            for bit in range(4):
                diff_params["fixedVariables"][f"x_{local_round}_{nibble}_{bit}"] = "0"
        else:
            diff_params["nonzeroVariables"].append(f"x_{local_round}_{nibble}")


def apply_truncated_nibble_mask(diff_params, family, round_index, mask):
    """Constrain a concrete nibble family to exactly one activity mask."""
    if mask in (None, "none"):
        return
    for nibble, flag in enumerate(mask):
        name = f"{family}_{round_index}_{nibble}"
        if flag == "0":
            diff_params["fixedVariables"][name] = "0"
        elif flag == "1":
            diff_params["nonzeroVariables"].append(name)
        else:
            raise ValueError(f"invalid truncated activity {flag!r} in {family}_{round_index}")


class SupportConsistencyError(RuntimeError):
    def __init__(self, mismatch):
        self.mismatch = mismatch
        super().__init__(
            "support mismatch: "
            f"side={mismatch['side']} truncated={mismatch['truncated_id']} "
            f"candidate={mismatch['candidate_id']} variable={mismatch['variable']} "
            f"round={mismatch['round']} nibble={mismatch['nibble']} "
            f"expected={mismatch['expected_activity']} actual={mismatch['actual_activity']}"
        )


def _hex_support(value):
    return "".join("0" if nibble == "0" else "1" for nibble in value.upper())


def _rotate_right_text(value, amount):
    amount %= len(value)
    return value[-amount:] + value[:-amount] if amount else value


def _add_expected_support(expected, family, model_round, mask, source_round=None):
    expected.append({
        "family": family,
        "model_round": int(model_round),
        "source_round": int(model_round if source_round is None else source_round),
        "mask": mask,
    })


def build_rkdiff_for_truncated_side(bm, side, params, upper_trail, lower_trail):
    """Build one RKDiff model whose complete support equals one truncated side."""
    if side == "upper":
        nrounds = bm.r0
        round_offset = 0
        truncated = upper_trail
        state_source = lambda r: r
    elif side == "lower":
        nrounds = bm.r1
        round_offset = bm.r0 + bm.rm
        truncated = lower_trail
        state_source = lambda r: bm.rm + r
    else:
        raise ValueError(f"unknown side: {side}")

    diff_params = {
        "nrounds": nrounds,
        "mode": 0,
        "startweight": 0,
        "endweight": 128,
        "timelimit": params.get("timelimit", 18000),
        "numberoftrails": 1,
        "round_offset": round_offset,
        "rk_mode": params.get("rk_mode", "rk-ladder"),
        "fixedVariables": {},
        "nonzeroVariables": [],
    }
    expected = []
    for local_round in range(nrounds + 1):
        source_round = state_source(local_round)
        mask = truncated[f"x_{source_round}"]
        apply_truncated_nibble_mask(diff_params, "x", local_round, mask)
        _add_expected_support(expected, "x", local_round, mask, source_round)
        if local_round < nrounds:
            for family in ("y", "l", "rk", "ak", "z"):
                mask = truncated[f"{family}_{source_round}"]
                apply_truncated_nibble_mask(diff_params, family, local_round, mask)
                _add_expected_support(expected, family, local_round, mask, source_round)

    max_key_round = round_offset + nrounds
    for global_round in range(max_key_round + 1):
        mask = truncated[f"ks_global_{global_round}"]
        apply_truncated_nibble_mask(diff_params, "ks", global_round, mask)
        _add_expected_support(expected, "ks_global", global_round, mask, global_round)
        if global_round < max_key_round:
            core_mask = truncated[f"kc_global_{global_round}"]
            apply_truncated_nibble_mask(diff_params, "kc", global_round, core_mask)
            _add_expected_support(expected, "kc_global", global_round, core_mask, global_round)

    diff = RKDiff(diff_params)
    diff.make_model()
    return diff, expected


def check_support_consistency(candidate, expected, side, truncated_id, candidate_id):
    characteristic = candidate["characteristic"]
    fixed_diffs = candidate["trail"]["fixed_diffs"]
    for item in expected:
        family = item["family"]
        model_round = item["model_round"]
        if family == "ks_global":
            concrete = characteristic[f"ks_global_{model_round}"]
        elif family == "kc_global":
            concrete = _rotate_right_text(fixed_diffs[f"dKSGCORE{model_round}"], 1)
        else:
            concrete = characteristic[f"{family}_{model_round}"]
        actual = _hex_support(concrete)
        mask = item["mask"]
        if actual == mask:
            continue
        for nibble, (expected_bit, actual_bit) in enumerate(zip(mask, actual)):
            if expected_bit != actual_bit:
                raise SupportConsistencyError({
                    "side": side,
                    "truncated_id": truncated_id,
                    "candidate_id": candidate_id,
                    "round": item["source_round"],
                    "variable": family,
                    "nibble": nibble,
                    "expected_activity": int(expected_bit),
                    "actual_activity": int(actual_bit),
                })
    return True


def _write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)


def _diff_markdown_table(characteristic):
    rows = [
        "| Rounds | x | y | l | RK | ak | z | KS | pr | rw | kw |",
        "|---:|---|---|---|---|---|---|---|---|---|---|",
    ]
    offset = int(characteristic.get("round_offset", 0))
    for r in range(characteristic["nrounds"] + 1):
        ks = characteristic.get(
            f"round_ks_{r}",
            characteristic.get(f"ks_global_{offset + r + 1}", "none")
            if r < characteristic["nrounds"] else "none",
        )
        values = [
            r,
            characteristic.get(f"x_{r}", "none"),
            characteristic.get(f"y_{r}", "none"),
            characteristic.get(f"l_{r}", "none"),
            characteristic.get(f"rk_{r}", "none"),
            characteristic.get(f"ak_{r}", "none"),
            characteristic.get(f"z_{r}", "none"),
            ks,
            characteristic.get(f"pr_{r}", "none"),
            characteristic.get(f"rw_{r}", "none"),
            characteristic.get(f"kw_{r}", "none"),
        ]
        rows.append("| " + " | ".join(f"`{value}`" for value in values) + " |")
    return rows


def _candidate_markdown(side, truncated_id, candidate_id, record, characteristic):
    side_title = "上" if side == "upper" else "下"
    lines = [
        f"# {side_title}路径 Exact Candidate {candidate_id:04d}",
        "",
        f"- Truncated Path ID：`{truncated_id}`",
        f"- Candidate ID：`{candidate_id}`",
        f"- SMT 状态：`{record['smt_status']}`",
        f"- Round Offset：`{record['round_offset']}`",
        f"- 主密钥输入差分：`{characteristic['master_key_diff']}`",
        f"- Weight：`{record['weight']}`",
    ]
    if record.get("nogood_constraint"):
        lines.append(f"- No-good Constraint：`{record['nogood_constraint']}`")
    if record.get("reason"):
        lines.append(f"- 原因：`{record['reason']}`")
    lines.extend([
        "",
        f"## {side_title}具体相关密钥差分路径",
        "",
        *_diff_markdown_table(characteristic),
        "",
    ])
    return "\n".join(lines)


def _save_candidate(path_dir, bucket, side, truncated_id, candidate_id, record, candidate):
    target_dir = os.path.join(path_dir, bucket) if bucket else path_dir
    os.makedirs(target_dir, exist_ok=True)
    stem = f"candidate_{candidate_id:04d}"
    _write_json(os.path.join(target_dir, stem + ".json"), record)
    with open(os.path.join(target_dir, stem + ".md"), "w", encoding="utf-8") as handle:
        handle.write(_candidate_markdown(
            side,
            truncated_id,
            candidate_id,
            record,
            candidate["characteristic"],
        ))


def solve_rkdiff_until_exact_sat(
    diff,
    label,
    path_dir,
    truncated_id,
    expected_support,
    timeout_ms=300_000,
    path_timeout_sec=None,
    verifier=verify_trail,
    initial_milp_result=None,
    write_summary=True,
    global_deadline=None,
):
    """Inner loop: enumerate concrete trails on one unchanged RKDiff model."""
    title = f"{label.capitalize()} exact-realizability refinement, truncated #{truncated_id}"
    print("=" * 60)
    print(title)
    print("=" * 60)
    started = perf_counter()
    candidate_id = 0
    rejected_signatures = set()
    pending_milp_result = initial_milp_result
    report = {
        "truncated_id": truncated_id,
        "side": label,
        "result": "SEARCHING",
        "rounds": diff.nrounds,
        "round_offset": diff.round_offset,
        "candidate_timeout_ms": timeout_ms,
        "path_timeout_seconds": path_timeout_sec,
        "total_candidates": 0,
        "rejected_candidates": 0,
        "unknown_candidates": 0,
        "initial_concrete_weight": None,
        "last_concrete_weight": None,
        "rkdiff_model_id": id(diff.milp_model) if diff.milp_model is not None else None,
        "milp_solve_seconds": 0.0,
        "z3_verification_seconds": 0.0,
    }

    def finish(result, **extra):
        report["result"] = result
        report["elapsed_seconds"] = perf_counter() - started
        report.update(extra)
        if write_summary:
            _write_json(os.path.join(path_dir, "summary.json"), report)
        return None, report

    while True:
        global_remaining = _remaining_solve_seconds(global_deadline)
        if global_remaining is not None and global_remaining <= 0:
            print("Action      : global solving time limit reached")
            return finish("GLOBAL_TIME_LIMIT", reason="GLOBAL_TIME_LIMIT")
        elapsed = perf_counter() - started
        if path_timeout_sec is not None and elapsed >= path_timeout_sec:
            print("Action      : current truncated path reached its overall timeout")
            return finish("TIMEOUT_SKIPPED", reason="PATH_TIMEOUT")

        if pending_milp_result is not None:
            milp_result = pending_milp_result
            pending_milp_result = None
        else:
            milp_limit = _effective_time_limit(
                global_deadline,
                getattr(diff, "time_limit", None),
            )
            if milp_limit is not None and milp_limit <= 0:
                return finish("GLOBAL_TIME_LIMIT", reason="GLOBAL_TIME_LIMIT")
            if isinstance(diff, RKDiff):
                milp_result = diff.optimize_next_candidate(
                    output_flag=False,
                    time_limit_override=milp_limit,
                )
            else:
                # Test/custom adapters may still expose the original interface.
                milp_result = diff.optimize_next_candidate(output_flag=False)
        report["milp_solve_seconds"] += float(milp_result.get("elapsed_seconds", 0.0))
        current_model_id = id(diff.milp_model)
        if report["rkdiff_model_id"] is None:
            report["rkdiff_model_id"] = current_model_id
        elif report["rkdiff_model_id"] != current_model_id:
            raise AssertionError("RKDiff model object changed during concrete refinement")
        if milp_result["trail"] is None:
            status = milp_result["status"]
            if status in ("INFEASIBLE", "INF_OR_UNBD"):
                print(f"{label} concrete candidates exhausted under truncated #{truncated_id}")
                return finish("CONCRETE_EXHAUSTED", milp_status=status)
            reason = "MILP_TIMEOUT" if status == "TIME_LIMIT" else "MILP_STOPPED_WITHOUT_SOLUTION"
            return finish("TIMEOUT_SKIPPED", reason=reason, milp_status=status)

        if path_timeout_sec is not None and perf_counter() - started >= path_timeout_sec:
            return finish("TIMEOUT_SKIPPED", reason="PATH_TIMEOUT")

        candidate_id += 1
        candidate = diff.extract_solution_for_exact_verify()
        signature = tuple(candidate["nogood_assignment"])
        if signature in rejected_signatures:
            raise AssertionError(
                f"{label} truncated #{truncated_id} candidate #{candidate_id} repeats a blocked signature"
            )
        check_support_consistency(
            candidate,
            expected_support,
            label,
            truncated_id,
            candidate_id,
        )
        report["total_candidates"] = candidate_id
        report["initial_concrete_weight"] = (
            candidate["weight"] if report["initial_concrete_weight"] is None
            else report["initial_concrete_weight"]
        )
        report["last_concrete_weight"] = candidate["weight"]

        effective_timeout_ms = timeout_ms
        if path_timeout_sec is not None:
            remaining_ms = int((path_timeout_sec - (perf_counter() - started)) * 1000)
            if remaining_ms <= 0:
                return finish("TIMEOUT_SKIPPED", reason="PATH_TIMEOUT")
            effective_timeout_ms = min(timeout_ms, remaining_ms)
        global_remaining = _remaining_solve_seconds(global_deadline)
        if global_remaining is not None:
            if global_remaining <= 0:
                return finish("GLOBAL_TIME_LIMIT", reason="GLOBAL_TIME_LIMIT")
            effective_timeout_ms = min(
                effective_timeout_ms,
                max(1, int(global_remaining * 1000)),
            )

        print(f"\nCandidate #{candidate_id}")
        print(f"MILP status : {milp_result['status']}")
        print(f"MILP weight : {candidate['weight']}")
        print(f"MILP time   : {float(milp_result.get('elapsed_seconds', 0.0)):.6f} seconds")
        verify_started = perf_counter()
        try:
            exact_result = verifier(
                candidate["trail"],
                timeout_ms=effective_timeout_ms,
                return_witness=True,
                return_all_diffs=False,
            )
        except Exception as exc:
            verification_seconds = perf_counter() - verify_started
            report["z3_verification_seconds"] += verification_seconds
            print(f"Z3 time     : {verification_seconds:.6f} seconds")
            record = {
                "truncated_id": truncated_id,
                "candidate_id": candidate_id,
                "side": label,
                "weight": candidate["weight"],
                "round_offset": diff.round_offset,
                "milp_status": milp_result["status"],
                "smt_status": "ERROR",
                "milp_solve_time_seconds": float(milp_result.get("elapsed_seconds", 0.0)),
                "verification_time_seconds": verification_seconds,
                "reason": f"{type(exc).__name__}: {exc}",
                "fixed_diffs": candidate["trail"]["fixed_diffs"],
                "characteristic": candidate["characteristic"],
            }
            _save_candidate(path_dir, "unknown", label, truncated_id, candidate_id, record, candidate)
            return finish("MODEL_INCONSISTENCY", candidate_id=candidate_id, reason=record["reason"])

        exact_status = exact_result["status"]
        verification_seconds = float(exact_result.get(
            "elapsed_seconds", perf_counter() - verify_started
        ))
        report["z3_verification_seconds"] += verification_seconds
        print(f"SMT status  : {exact_status}")
        print(f"Z3 time     : {verification_seconds:.6f} seconds")
        base_record = {
            "truncated_id": truncated_id,
            "candidate_id": candidate_id,
            "side": label,
            "weight": candidate["weight"],
            "round_offset": diff.round_offset,
            "milp_status": milp_result["status"],
            "smt_status": exact_status,
            "milp_solve_time_seconds": float(milp_result.get("elapsed_seconds", 0.0)),
            "verification_time_seconds": verification_seconds,
            "signature_bit_count": len(signature),
            "fixed_diffs": candidate["trail"]["fixed_diffs"],
            "characteristic": candidate["characteristic"],
        }

        if exact_status == "SAT":
            witness = exact_result.get("witness")
            replay = witness.get("concrete_replay") if witness else None
            print(f"Replay      : {replay}")
            base_record["concrete_replay"] = replay
            base_record["witness"] = witness
            if replay != "PASS":
                base_record["reason"] = "SMT returned SAT but concrete replay did not PASS"
                _save_candidate(path_dir, "unknown", label, truncated_id, candidate_id, base_record, candidate)
                return finish(
                    "MODEL_INCONSISTENCY",
                    candidate_id=candidate_id,
                    reason=base_record["reason"],
                )
            report.update({
                "result": "SAT",
                "accepted_candidate": candidate_id,
                "accepted_weight": candidate["weight"],
                "concrete_replay": "PASS",
                "witness": witness,
                "elapsed_seconds": perf_counter() - started,
            })
            if write_summary:
                _write_json(os.path.join(path_dir, "summary.json"), report)
            print(f"Accepted {label}: truncated #{truncated_id}, candidate #{candidate_id}")
            return candidate["characteristic"], report

        if exact_status == "UNSAT":
            constraint_name = (
                f"exact_nogood_{label}_t{truncated_id:03d}_c{candidate_id:04d}"
            )
            base_record["nogood_constraint"] = constraint_name
            # Save the frozen candidate before another optimize overwrites Var.X.
            _save_candidate(path_dir, "rejected", label, truncated_id, candidate_id, base_record, candidate)
            actual_name = diff.add_solution_nogood(
                candidate,
                constraint_name=constraint_name,
            )
            if actual_name != constraint_name:
                raise AssertionError("unexpected concrete no-good constraint name")
            rejected_signatures.add(signature)
            report["rejected_candidates"] += 1
            print("Action      : block full concrete trail and re-optimize same RKDiff model")
            continue

        if exact_status == "UNKNOWN":
            base_record["reason"] = exact_result.get("reason")
            _save_candidate(path_dir, "unknown", label, truncated_id, candidate_id, base_record, candidate)
            report["unknown_candidates"] += 1
            print("Action      : skip current truncated path; UNKNOWN candidate is not blocked")
            return finish(
                "TIMEOUT_SKIPPED",
                reason="Z3_TIMEOUT" if exact_result.get("reason") == "timeout" else "Z3_UNKNOWN",
                unknown_candidate=candidate_id,
            )

        raise RuntimeError(f"unexpected exact verification status: {exact_status}")


def _save_truncated_path(path_dir, truncated_id, snapshot, bm):
    """Save one complete joint upper/Em/lower truncated boomerang path."""
    activity = snapshot["activity"]
    payload = {
        "truncated_id": truncated_id,
        "weight": snapshot["objective"],
        "signature": snapshot["signature"],
        "upper_trail": activity["upper_trail"],
        "middle_part": activity["middle_part"],
        "lower_trail": activity["lower_trail"],
        "truncated_model_id": id(bm.milp_model),
        "timing": snapshot.get("timing", {}),
    }
    _write_json(os.path.join(path_dir, "truncated_path.json"), payload)
    lines = [
        f"# 联合截断 Boomerang 路径 #{truncated_id:04d}",
        "",
        f"- 截断模型目标值：`{snapshot['objective']}`",
        f"- 截断签名 bit 数：`{len(snapshot['signature'])}`",
        f"- 截断模型对象 ID：`{id(bm.milp_model)}`",
        f"- 从求解开始到路径通过 upper/lower 实例化：`{snapshot.get('timing', {}).get('qualification_seconds_from_solve_start', 'none')}` 秒",
        "",
        "## Upper 截断差分",
        "",
        "```text",
        *truncated_trail_to_lines(activity["upper_trail"], bm.R0),
        "```",
        "",
        "## 中间共同活跃位置",
        "",
        "| Round | state | key schedule |",
        "|---:|---|---|",
    ]
    middle = activity["middle_part"]
    for r in range(bm.rm):
        lines.append(f"| {r} | `{middle.get(f's_{r}', '')}` | `{middle.get(f'ks_{r}', '')}` |")
    lines.extend([
        "",
        "## Lower 截断差分",
        "",
        "```text",
        *truncated_trail_to_lines(activity["lower_trail"], bm.R1),
        "```",
    ])
    with open(os.path.join(path_dir, "truncated_path.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _accepted_markdown(side, truncated_id, report, characteristic, previous_paths):
    side_title = "上" if side == "upper" else "下"
    witness = report.get("witness") or {}
    lines = [
        f"# {side_title}路径 Exact Accepted Candidate",
        "",
        f"- Truncated Path ID：`{truncated_id}`",
        f"- Candidate ID：`{report['accepted_candidate']}`",
        "- SMT 状态：`SAT`",
        f"- Concrete Replay：`{report.get('concrete_replay')}`",
        f"- Round Offset：`{characteristic.get('round_offset')}`",
        f"- Weight：`{report.get('accepted_weight')}`",
        f"- Previous Truncated Paths：`{previous_paths}`",
        f"- Rejected Concrete Candidates：`{report.get('rejected_candidates', 0)}`",
        "",
        f"## {side_title}具体相关密钥差分路径",
        "",
        *_diff_markdown_table(characteristic),
        "",
        "## Real Witness",
        "",
    ]
    witness_labels = {
        "state_A_0": "State A",
        "state_B_0": "State B",
        "state_A_final": "State A Final",
        "state_B_final": "State B Final",
        "master_key_A": "Master Key A",
        "master_key_B": "Master Key B",
        "master_key_diff": "Master Key Difference",
        "concrete_replay": "Concrete Replay",
    }
    for key, label in witness_labels.items():
        if key in witness:
            lines.append(f"- {label}：`{witness[key]}`")
    return "\n".join(lines) + "\n"


def _save_accepted(exact_dir, side, truncated_id, report, characteristic, previous_paths):
    payload = {
        "truncated_id": truncated_id,
        "candidate_id": report["accepted_candidate"],
        "side": side,
        "status": "SAT",
        "weight": report["accepted_weight"],
        "round_offset": characteristic["round_offset"],
        "rejected_before_sat": report["rejected_candidates"],
        "concrete_replay": report["concrete_replay"],
        "characteristic": characteristic,
        "witness": report.get("witness"),
        "timing": {
            "instantiation_seconds": report.get("instantiation_seconds"),
            "candidate_milp_seconds": report.get("milp_solve_seconds"),
            "z3_verification_seconds": report.get("z3_verification_seconds"),
            "exact_refinement_seconds": report.get("elapsed_seconds"),
        },
    }
    _write_json(os.path.join(exact_dir, "accepted.json"), payload)
    with open(os.path.join(exact_dir, "accepted.md"), "w", encoding="utf-8") as handle:
        handle.write(_accepted_markdown(
            side, truncated_id, report, characteristic, previous_paths
        ))


def _save_global_side_summary(exact_dir, side, result, path_reports, **extra):
    summary = {
        "side": side,
        "exact_verify_enabled": True,
        "result": result,
        "truncated_paths_tested": len(path_reports),
        "timeout_skipped_paths": sum(
            item.get("result") == "TIMEOUT_SKIPPED" for item in path_reports
        ),
        "truncated_paths": [
            {
                "truncated_id": item.get("truncated_id"),
                "result": item.get("result"),
                "candidate_count": item.get("total_candidates", 0),
                **({"accepted_candidate": item["accepted_candidate"]}
                   if item.get("accepted_candidate") is not None else {}),
            }
            for item in path_reports
        ],
    }
    summary.update(extra)
    if exact_dir is not None:
        _write_json(os.path.join(exact_dir, "summary.json"), summary)
    return summary


def _write_joint_path_summary(
    path_dir,
    truncated_id,
    snapshot,
    upper_report,
    lower_report,
    result,
    truncated_nogood=None,
):
    payload = {
        "truncated_id": truncated_id,
        "result": result,
        "truncated_weight": snapshot["objective"],
        "upper": upper_report,
        "lower": lower_report,
        "truncated_model_id": snapshot.get("truncated_model_id"),
        "timing": snapshot.get("timing", {}),
    }
    if truncated_nogood is not None:
        payload["truncated_nogood"] = truncated_nogood
    _write_json(os.path.join(path_dir, "summary.json"), payload)
    return payload


def _reset_exact_result_dirs(results_dir):
    """Remove only this case's prior exact-layout directories before a fresh run."""
    results_root = os.path.realpath(results_dir)
    names = ["upper_exact", "lower_exact"]
    if os.path.isdir(results_root):
        names.extend(
            name
            for name in os.listdir(results_root)
            if re.fullmatch(r"truncated_\d{4}", name)
        )
    for name in names:
        path = os.path.realpath(os.path.join(results_root, name))
        if os.path.commonpath((results_root, path)) != results_root:
            raise RuntimeError(f"refusing to clear exact results outside {results_root}")
        if os.path.isdir(path):
            shutil.rmtree(path)


def run_exact_two_level_search(
    bm,
    params,
    results_dir,
    verifier=verify_trail,
    diff_builder=build_rkdiff_for_truncated_side,
    inner_solver=solve_rkdiff_until_exact_sat,
    preflight_solver=None,
    global_deadline=None,
    solve_started=None,
    lp_cleaner=None,
):
    """Outer truncated enumeration plus inner concrete exact refinement."""
    _reset_exact_result_dirs(results_dir)
    solve_started = perf_counter() if solve_started is None else solve_started
    truncated_started = perf_counter()

    bm.make_model()
    bm.load_model()
    truncated_model_id = id(bm.milp_model)
    upper_reports = []
    lower_reports = []
    timed_out_paths = []
    truncated_id = 0
    raw_candidate_id = 0
    raw_rejected = 0
    raw_unresolved = 0
    timeout_ms = params.get("exact_verify_timeout_ms", 300_000)
    path_timeout_sec = params.get("exact_path_timeout_sec")
    default_preflight_solver = preflight_solver is None
    lp_cleaner = lp_cleaner or _InstantiationLpCleaner()

    def finish_result(payload):
        cleanup = lp_cleaner.snapshot()
        payload["instantiation_lp_cleanup"] = cleanup
        print(
            "Instantiation LP cleanup: "
            f"registered={cleanup['registered_files']} "
            f"deleted={cleanup['deleted_files']} "
            f"deleted_bytes={cleanup['deleted_bytes']} "
            f"retained={cleanup['retained_registered_files']} "
            f"refused={cleanup['refused_files']} "
            f"failures={cleanup['delete_failures']}"
        )
        return payload

    def solve_preflight(diff):
        if not default_preflight_solver:
            return preflight_solver(diff)
        if not isinstance(diff, RKDiff):
            return diff.optimize_next_candidate(output_flag=False)
        milp_limit = _effective_time_limit(global_deadline, diff.time_limit)
        if milp_limit is not None and milp_limit <= 0:
            return {
                "status": "GLOBAL_TIME_LIMIT",
                "trail": None,
                "weight": None,
                "elapsed_seconds": 0.0,
            }
        return diff.optimize_next_candidate(
            output_flag=False,
            time_limit_override=milp_limit,
        )

    while True:
        truncated_limit = _effective_time_limit(
            global_deadline,
            getattr(bm, "time_limit", None),
        )
        if truncated_limit is not None and truncated_limit <= 0:
            truncated_result = {
                "status": "GLOBAL_TIME_LIMIT",
                "solution": None,
                "objective": None,
                "elapsed_seconds": 0.0,
            }
        else:
            if isinstance(bm, RKTruncatedBoomerang):
                truncated_result = bm.optimize_next_truncated_path(
                    output_flag=False,
                    time_limit_override=truncated_limit,
                )
            else:
                truncated_result = bm.optimize_next_truncated_path(output_flag=False)
        if truncated_result["solution"] is None:
            if truncated_result["status"] == "GLOBAL_TIME_LIMIT":
                global_result = "GLOBAL_TIME_LIMIT"
            elif truncated_result["status"] not in ("INFEASIBLE", "INF_OR_UNBD"):
                global_result = "SEARCH_INCOMPLETE_TIMEOUT"
            else:
                global_result = (
                    "SEARCH_INCOMPLETE_TIMEOUT"
                    if timed_out_paths else "NO_EXACT_REALIZABLE_TRAIL"
                )
            upper_summary = _save_global_side_summary(
                None,
                "upper",
                global_result,
                upper_reports,
                truncated_model_id=truncated_model_id,
                timed_out_truncated_paths=timed_out_paths,
                raw_truncated_candidates=raw_candidate_id,
                raw_rejected_before_results=raw_rejected,
                raw_unresolved_before_results=raw_unresolved,
            )
            lower_summary = _save_global_side_summary(
                None,
                "lower",
                global_result,
                lower_reports,
                truncated_model_id=truncated_model_id,
                timed_out_truncated_paths=timed_out_paths,
                raw_truncated_candidates=raw_candidate_id,
                raw_rejected_before_results=raw_rejected,
                raw_unresolved_before_results=raw_unresolved,
            )
            return finish_result({
                "result": global_result,
                "upper_trail": None,
                "lower_trail": None,
                "truncated": None,
                "upper_summary": upper_summary,
                "lower_summary": lower_summary,
                "truncated_model_id": truncated_model_id,
                "raw_truncated_candidates": raw_candidate_id,
                "raw_rejected_before_results": raw_rejected,
                "timing": {
                    "truncated_search_seconds": perf_counter() - truncated_started,
                    "total_solving_seconds": perf_counter() - solve_started,
                },
            })

        raw_candidate_id += 1
        snapshot = bm.extract_current_truncated_path()
        if id(bm.milp_model) != truncated_model_id:
            raise AssertionError("truncated model object changed during outer enumeration")
        parsed = snapshot["activity"]
        upper_trail = parsed["upper_trail"]
        middle_part = parsed["middle_part"]
        lower_trail = parsed["lower_trail"]
        upper_build_started = perf_counter()
        upper_diff, upper_expected = diff_builder(
            bm, "upper", params, upper_trail, lower_trail
        )
        upper_build_seconds = perf_counter() - upper_build_started
        lower_build_started = perf_counter()
        lower_diff, lower_expected = diff_builder(
            bm, "lower", params, upper_trail, lower_trail
        )
        lower_build_seconds = perf_counter() - lower_build_started
        lp_cleaner.register(upper_diff)
        lp_cleaner.register(lower_diff)
        upper_first = solve_preflight(upper_diff)
        lower_first = solve_preflight(lower_diff)
        upper_instantiation_seconds = (
            upper_build_seconds + float(upper_first.get("elapsed_seconds", 0.0))
        )
        lower_instantiation_seconds = (
            lower_build_seconds + float(lower_first.get("elapsed_seconds", 0.0))
        )
        if "GLOBAL_TIME_LIMIT" in (upper_first["status"], lower_first["status"]):
            return finish_result({
                "result": "GLOBAL_TIME_LIMIT",
                "upper_trail": None,
                "lower_trail": None,
                "truncated": snapshot,
                "truncated_model_id": truncated_model_id,
                "raw_truncated_candidates": raw_candidate_id,
                "raw_rejected_before_results": raw_rejected,
                "timing": {
                    "truncated_search_seconds": perf_counter() - truncated_started,
                    "upper_instantiation_seconds": upper_instantiation_seconds,
                    "lower_instantiation_seconds": lower_instantiation_seconds,
                    "total_solving_seconds": perf_counter() - solve_started,
                },
            })
        if upper_first["trail"] is None or lower_first["trail"] is None:
            statuses = {
                "upper": upper_first["status"],
                "lower": lower_first["status"],
            }
            unresolved = any(
                status not in ("INFEASIBLE", "INF_OR_UNBD")
                for side, status in statuses.items()
                if (upper_first if side == "upper" else lower_first)["trail"] is None
            )
            if unresolved:
                raw_unresolved += 1
            raw_rejected += 1
            raw_nogood = bm.add_truncated_path_nogood(
                snapshot,
                constraint_name=f"raw_truncated_nogood_{raw_candidate_id:04d}",
            )
            cleanup = {"deleted_files": 0, "deleted_bytes": 0}
            if not unresolved:
                cleanup = lp_cleaner.delete_many(
                    (upper_diff, lower_diff),
                    reason=f"raw_truncated_candidate_{raw_candidate_id}_rejected",
                )
            print(
                f"Raw truncated candidate #{raw_candidate_id}: "
                f"upper={statuses['upper']}, lower={statuses['lower']}; "
                f"not counted in results, add {raw_nogood}; "
                f"lp_cleanup_deleted={cleanup['deleted_files']} "
                f"lp_cleanup_bytes={cleanup['deleted_bytes']}"
            )
            continue

        truncated_id += 1
        qualification_seconds = perf_counter() - solve_started
        print("\nMILP-qualified truncated path timing")
        print(f"qualified truncated id       : {truncated_id}")
        print(f"raw truncated candidates     : {raw_candidate_id}")
        print(f"from solve start to qualified: {qualification_seconds:.6f} seconds")
        print(f"upper RKDiff instantiation   : {upper_instantiation_seconds:.6f} seconds")
        print(f"lower RKDiff instantiation   : {lower_instantiation_seconds:.6f} seconds")
        snapshot["timing"] = {
            "qualification_seconds_from_solve_start": qualification_seconds,
            "truncated_search_seconds": perf_counter() - truncated_started,
            "truncated_milp_seconds": float(truncated_result.get("elapsed_seconds", 0.0)),
            "upper_instantiation_seconds": upper_instantiation_seconds,
            "lower_instantiation_seconds": lower_instantiation_seconds,
        }
        bm.parse_solver_output()
        path_dir = os.path.join(results_dir, f"truncated_{truncated_id:04d}")
        upper_path_dir = os.path.join(path_dir, "upper")
        lower_path_dir = os.path.join(path_dir, "lower")
        os.makedirs(upper_path_dir, exist_ok=True)
        os.makedirs(lower_path_dir, exist_ok=True)
        _save_truncated_path(path_dir, truncated_id, snapshot, bm)
        path_started = perf_counter()

        try:
            upper_characteristic, upper_report = inner_solver(
                upper_diff,
                "upper",
                upper_path_dir,
                truncated_id,
                upper_expected,
                timeout_ms=timeout_ms,
                path_timeout_sec=path_timeout_sec,
                verifier=verifier,
                initial_milp_result=upper_first,
                write_summary=False,
                global_deadline=global_deadline,
            )
        except SupportConsistencyError as exc:
            failure = {
                "truncated_id": truncated_id,
                "side": "upper",
                "result": "SUPPORT_MISMATCH",
                "mismatch": exc.mismatch,
            }
            _write_joint_path_summary(
                path_dir,
                truncated_id,
                snapshot,
                failure,
                None,
                "SUPPORT_MISMATCH",
            )
            return finish_result({
                "result": "SUPPORT_MISMATCH",
                "upper_trail": None,
                "lower_trail": None,
                "truncated": snapshot,
                "mismatch": exc.mismatch,
                "truncated_model_id": truncated_model_id,
            })
        upper_reports.append(upper_report)
        upper_report["instantiation_seconds"] = upper_instantiation_seconds

        if upper_report["result"] == "GLOBAL_TIME_LIMIT":
            _write_joint_path_summary(
                path_dir,
                truncated_id,
                snapshot,
                upper_report,
                None,
                "GLOBAL_TIME_LIMIT",
            )
            return finish_result({
                "result": "GLOBAL_TIME_LIMIT",
                "upper_trail": None,
                "lower_trail": None,
                "truncated": snapshot,
                "timing": {
                    **snapshot.get("timing", {}),
                    "total_solving_seconds": perf_counter() - solve_started,
                },
            })

        if upper_report["result"] == "MODEL_INCONSISTENCY":
            _write_joint_path_summary(
                path_dir,
                truncated_id,
                snapshot,
                upper_report,
                None,
                "MODEL_INCONSISTENCY",
            )
            return finish_result({
                "result": "MODEL_INCONSISTENCY",
                "upper_trail": None,
                "lower_trail": None,
                "truncated": snapshot,
            })

        if upper_report["result"] == "SAT":
            _save_accepted(
                upper_path_dir,
                "upper",
                truncated_id,
                upper_report,
                upper_characteristic,
                truncated_id - 1,
            )

        lower_characteristic = None
        lower_report = None
        if upper_report["result"] == "SAT":
            remaining_path_timeout = None
            if path_timeout_sec is not None:
                remaining_path_timeout = path_timeout_sec - (perf_counter() - path_started)
            if remaining_path_timeout is not None and remaining_path_timeout <= 0:
                lower_report = {
                    "truncated_id": truncated_id,
                    "side": "lower",
                    "result": "TIMEOUT_SKIPPED",
                    "reason": "PATH_TIMEOUT",
                    "total_candidates": 0,
                    "rejected_candidates": 0,
                    "unknown_candidates": 0,
                    "elapsed_seconds": 0.0,
                }
                lower_reports.append(lower_report)
            else:
                try:
                    lower_characteristic, lower_report = inner_solver(
                        lower_diff,
                        "lower",
                        lower_path_dir,
                        truncated_id,
                        lower_expected,
                        timeout_ms=timeout_ms,
                        path_timeout_sec=remaining_path_timeout,
                        verifier=verifier,
                        initial_milp_result=lower_first,
                        write_summary=False,
                        global_deadline=global_deadline,
                    )
                except SupportConsistencyError as exc:
                    failure = {
                        "truncated_id": truncated_id,
                        "side": "lower",
                        "result": "SUPPORT_MISMATCH",
                        "mismatch": exc.mismatch,
                    }
                    _write_joint_path_summary(
                        path_dir,
                        truncated_id,
                        snapshot,
                        upper_report,
                        failure,
                        "SUPPORT_MISMATCH",
                    )
                    return finish_result({
                        "result": "SUPPORT_MISMATCH",
                        "upper_trail": None,
                        "lower_trail": None,
                        "truncated": snapshot,
                        "mismatch": exc.mismatch,
                        "truncated_model_id": truncated_model_id,
                    })
                lower_reports.append(lower_report)
                lower_report["instantiation_seconds"] = lower_instantiation_seconds
            if lower_report["result"] == "GLOBAL_TIME_LIMIT":
                _write_joint_path_summary(
                    path_dir,
                    truncated_id,
                    snapshot,
                    upper_report,
                    lower_report,
                    "GLOBAL_TIME_LIMIT",
                )
                return finish_result({
                    "result": "GLOBAL_TIME_LIMIT",
                    "upper_trail": None,
                    "lower_trail": None,
                    "truncated": snapshot,
                    "timing": {
                        **snapshot.get("timing", {}),
                        "total_solving_seconds": perf_counter() - solve_started,
                    },
                })
            if lower_report["result"] == "MODEL_INCONSISTENCY":
                _write_joint_path_summary(
                    path_dir,
                    truncated_id,
                    snapshot,
                    upper_report,
                    lower_report,
                    "MODEL_INCONSISTENCY",
                )
                return finish_result({
                    "result": "MODEL_INCONSISTENCY",
                    "upper_trail": None,
                    "lower_trail": None,
                    "truncated": snapshot,
                })
        else:
            lower_report = {
                "truncated_id": truncated_id,
                "side": "lower",
                "result": "NOT_RUN_UPPER_NOT_SAT",
                "total_candidates": 0,
                "elapsed_seconds": 0.0,
            }
            lower_reports.append(lower_report)

        if lower_report["result"] == "SAT":
            _save_accepted(
                lower_path_dir,
                "lower",
                truncated_id,
                lower_report,
                lower_characteristic,
                truncated_id - 1,
            )

        if (
            upper_report["result"] == "SAT"
            and lower_report["result"] == "SAT"
        ):
            _write_joint_path_summary(
                path_dir,
                truncated_id,
                snapshot,
                upper_report,
                lower_report,
                "SAT",
            )
            upper_summary = _save_global_side_summary(
                None,
                "upper",
                "SAT",
                upper_reports,
                accepted_truncated_id=truncated_id,
                accepted_candidate_id=upper_report["accepted_candidate"],
                accepted_weight=upper_report["accepted_weight"],
                concrete_replay="PASS",
                truncated_model_id=truncated_model_id,
                raw_truncated_candidates=raw_candidate_id,
                raw_rejected_before_results=raw_rejected,
                raw_unresolved_before_results=raw_unresolved,
            )
            lower_summary = _save_global_side_summary(
                None,
                "lower",
                "SAT",
                lower_reports,
                accepted_truncated_id=truncated_id,
                accepted_candidate_id=lower_report["accepted_candidate"],
                accepted_weight=lower_report["accepted_weight"],
                concrete_replay="PASS",
                truncated_model_id=truncated_model_id,
                raw_truncated_candidates=raw_candidate_id,
                raw_rejected_before_results=raw_rejected,
                raw_unresolved_before_results=raw_unresolved,
            )
            return finish_result({
                "result": "SUCCESS",
                "upper_trail": upper_characteristic,
                "lower_trail": lower_characteristic,
                "truncated": snapshot,
                "upper_summary": upper_summary,
                "lower_summary": lower_summary,
                "truncated_model_id": truncated_model_id,
                "raw_truncated_candidates": raw_candidate_id,
                "raw_rejected_before_results": raw_rejected,
                "timing": {
                    **snapshot.get("timing", {}),
                    "total_solving_seconds": perf_counter() - solve_started,
                },
            })

        if (
            upper_report["result"] == "TIMEOUT_SKIPPED"
            or lower_report["result"] == "TIMEOUT_SKIPPED"
        ):
            timed_out_paths.append(truncated_id)

        truncated_nogood = bm.add_truncated_path_nogood(snapshot, truncated_id)
        if id(bm.milp_model) != truncated_model_id:
            raise AssertionError("truncated model object changed while adding no-good")
        joint_result = (
            "TIMEOUT_SKIPPED"
            if truncated_id in timed_out_paths else "CONCRETE_EXHAUSTED"
        )
        _write_joint_path_summary(
            path_dir,
            truncated_id,
            snapshot,
            upper_report,
            lower_report,
            joint_result,
            truncated_nogood=truncated_nogood,
        )
        rejected_results = {"CONCRETE_EXHAUSTED", "UNSAT", "NOT_RUN_UPPER_NOT_SAT"}
        cleanup_targets = []
        if upper_report["result"] in rejected_results:
            cleanup_targets.append(upper_diff)
        if lower_report["result"] in rejected_results:
            cleanup_targets.append(lower_diff)
        cleanup = lp_cleaner.delete_many(
            cleanup_targets,
            reason=f"truncated_candidate_{truncated_id}_{joint_result}",
        )
        print(
            f"Truncated #{truncated_id}: {upper_report['result']} / "
            f"{lower_report['result']}; add {truncated_nogood} and optimize same truncated model; "
            f"lp_cleanup_deleted={cleanup['deleted_files']} "
            f"lp_cleanup_bytes={cleanup['deleted_bytes']}"
        )


def _run_search(params, results_dir, solve_started=None, global_deadline=None):
    solve_started = perf_counter() if solve_started is None else solve_started
    r0, rm, r1 = params["r0"], params["rm"], params["r1"]
    w0, wm, w1 = params["w0"], params["wm"], params["w1"]
    assert(rm > 0)

    bm = RKTruncatedBoomerang(
        r0=r0,
        r1=r1,
        rm=rm,
        w0=w0,
        w1=w1,
        wm=wm,
        rk_mode=params.get("rk_mode", "rk-ladder"),
        time_limit=params.get("timelimit"),
    )
    bm.iterative = False
    result_name = f"{r0}-{rm}-{r1}"
    json_dir = os.path.join(results_dir, ".json")
    os.makedirs(json_dir, exist_ok=True)
    tex_content = tex_init()
    upper_exact_report = None
    lower_exact_report = None
    timing = {
        "single_milp_time_limit_seconds": params.get("timelimit"),
        "global_time_limit_seconds": params.get("global_timelimit"),
        "truncated_search_seconds": None,
        "upper_instantiation_seconds": None,
        "lower_instantiation_seconds": None,
        "probability_test_seconds": None,
    }
    print("=" * 72)
    print("Search time limits")
    print(f"single MILP optimize : {params.get('timelimit')} seconds")
    print(
        "global search       : "
        + (
            f"{params['global_timelimit']} seconds"
            if params.get("global_timelimit") is not None
            else "unlimited"
        )
    )
    print("probability test     : excluded from global search time")

    if params.get("exact_verify"):
        exact_search = run_exact_two_level_search(
            bm,
            params,
            results_dir,
            global_deadline=global_deadline,
            solve_started=solve_started,
        )
        timing.update({
            key: value
            for key, value in exact_search.get("timing", {}).items()
            if value is not None
        })
        timing["total_solving_seconds"] = perf_counter() - solve_started
        exact_search["timing"] = timing.copy()
        _write_json(os.path.join(results_dir, "exact_summary.json"), exact_search)
        if exact_search["result"] != "SUCCESS":
            print(f"Exact two-level search stopped with result: {exact_search['result']}")
            print(f"Total solving time: {timing['total_solving_seconds']:.6f} seconds")
            return exact_search
        snapshot = exact_search["truncated"]
        upper_trail = snapshot["activity"]["upper_trail"]
        middle_part = snapshot["activity"]["middle_part"]
        lower_trail = snapshot["activity"]["lower_trail"]
        diff_upper_trail = exact_search["upper_trail"]
        diff_lower_trail = exact_search["lower_trail"]
        upper_exact_report = exact_search["upper_summary"]
        lower_exact_report = exact_search["lower_summary"]
    else:
        truncated_started = perf_counter()
        truncated_limit = _effective_time_limit(global_deadline, bm.time_limit)
        if truncated_limit is not None and truncated_limit <= 0:
            timing["total_solving_seconds"] = perf_counter() - solve_started
            print("Global solving time limit reached before truncated MILP")
            print(f"Total solving time: {timing['total_solving_seconds']:.6f} seconds")
            return {"result": "GLOBAL_TIME_LIMIT", "timing": timing}
        truncated_result = bm.find_truncated_boomerang_trail(
            time_limit_override=truncated_limit
        )
        timing["truncated_search_seconds"] = perf_counter() - truncated_started
        print(
            "Truncated trail search time: "
            f"{timing['truncated_search_seconds']:.6f} seconds"
        )
        if truncated_result["solution"] is None:
            timing["total_solving_seconds"] = perf_counter() - solve_started
            stopped_by_global_limit = (
                global_deadline is not None
                and _remaining_solve_seconds(global_deadline) <= 0
            )
            result = {
                "result": (
                    "GLOBAL_TIME_LIMIT"
                    if stopped_by_global_limit
                    else "TRUNCATED_SEARCH_STOPPED"
                ),
                "timing": timing,
            }
            print(f"Total solving time: {timing['total_solving_seconds']:.6f} seconds")
            return result
        upper_trail, middle_part, lower_trail = bm.parse_solver_output()
        diff_upper_trail = None
        diff_lower_trail = None
        time_limit = params.get("timelimit", 18000)
        if r0 != 0:
            instantiation_started = perf_counter()
            diff_params = {
                "nrounds": bm.r0,
                "mode": 0,
                "startweight": 0,
                "endweight": 128,
                "timelimit": time_limit,
                "numberoftrails": 1,
                "round_offset": 0,
                "rk_mode": params.get("rk_mode", "rk-ladder"),
                "fixedVariables": {},
                "nonzeroVariables": [],
            }
            apply_truncated_state_mask(diff_params, 0, upper_trail["x_0"])
            apply_truncated_state_mask(diff_params, bm.r0, upper_trail[f"x_{bm.r0}"])
            diff_upper = RKDiff(diff_params)
            diff_upper.make_model()
            upper_limit = _effective_time_limit(global_deadline, time_limit)
            diff_upper_trail = diff_upper.solve(
                deadline=global_deadline,
                time_limit_override=upper_limit,
            )
            timing["upper_instantiation_seconds"] = perf_counter() - instantiation_started
            print(
                "Upper RKDiff instantiation time: "
                f"{timing['upper_instantiation_seconds']:.6f} seconds"
            )
        if r1 != 0:
            instantiation_started = perf_counter()
            diff_params = {
                "nrounds": bm.r1,
                "mode": 0,
                "startweight": 0,
                "endweight": 128,
                "timelimit": time_limit,
                "numberoftrails": 1,
                "round_offset": bm.r0 + bm.rm,
                "rk_mode": params.get("rk_mode", "rk-ladder"),
                "fixedVariables": {},
                "nonzeroVariables": [],
            }
            apply_truncated_state_mask(diff_params, 0, lower_trail[f"x_{bm.rm}"])
            apply_truncated_state_mask(diff_params, bm.r1, lower_trail[f"x_{bm.R1}"])
            diff_lower = RKDiff(diff_params)
            diff_lower.make_model()
            lower_limit = _effective_time_limit(global_deadline, time_limit)
            diff_lower_trail = diff_lower.solve(
                deadline=global_deadline,
                time_limit_override=lower_limit,
            )
            timing["lower_instantiation_seconds"] = perf_counter() - instantiation_started
            print(
                "Lower RKDiff instantiation time: "
                f"{timing['lower_instantiation_seconds']:.6f} seconds"
            )

    lp_target = bm.lp_file_name
    diff_effect_upper = (
        -float(diff_upper_trail["total_weight"]) if diff_upper_trail is not None else 0
    )
    diff_effect_lower = (
        -float(diff_lower_trail["total_weight"]) if diff_lower_trail is not None else 0
    )

    print("\n"+"=" * 60)
    print(f"Boomerang distinguisher for {r0} + {rm} + {r1} ")
    print("#" * 60)
    print("Summary of the results:")
    print("Upper trail:")
    if diff_upper_trail is not None:
        RKDiff.print_trail(diff_trail=diff_upper_trail)
    print("#" * 60)
    mactive_sboxes = middle_part["as"]
    print(f"Sandwich {rm} rounds in the middle with {mactive_sboxes} active S-boxes")
    print("#" * 60)
    print("Lower trail:")
    if diff_lower_trail is not None:
        RKDiff.print_trail(diff_trail=diff_lower_trail)
    print("-" * 27)
    total_weight = 0
    if diff_effect_upper != 0:
        print("differential effect of the upper trail: 2^(%0.02f)" % diff_effect_upper)
        total_weight += diff_effect_upper * 2
    if diff_effect_lower != 0:
        print("differential effect of the lower trail: 2^(%0.02f)" % diff_effect_lower)
        total_weight += diff_effect_lower * 2
    upper_bound = total_weight + (-2) * mactive_sboxes
    lower_bound = total_weight + (-2.5) * mactive_sboxes
    print("Total probability = p^2*q^2*r = 2^({:.2f}) x 2^({:.2f}) x r".format(
        diff_effect_upper * 2, diff_effect_lower * 2))
    print("2^({:.2f}) <= Total probability <= 2^({:.2f})".format(lower_bound, upper_bound))
    print("To compute the accurate value of total probability, r should be evaluated experimentally or using the (F)BCT framework")
    timing["total_solving_seconds"] = perf_counter() - solve_started
    print(f"Total solving time: {timing['total_solving_seconds']:.6f} seconds")
    if params.get("exact_verify"):
        exact_search["timing"] = timing.copy()
        _write_json(os.path.join(results_dir, "exact_summary.json"), exact_search)

    tex_content += tex_middle(upper_trail=upper_trail, midd_trail=middle_part,
                              lower_trail=lower_trail, r0=r0, rm=rm, r1=r1)
    tex_content += tex_fin(r0 + rm + r1)
    tex_path = os.path.join(results_dir, "bmd.tex")
    with open(tex_path, "w", encoding="utf-8") as texfile:
        texfile.write(tex_content)

    result = {
        "parameters": params,
        "upper_trail": upper_trail,
        "middle_part": middle_part,
        "lower_trail": lower_trail,
        "diff_upper_trail": diff_upper_trail,
        "diff_lower_trail": diff_lower_trail,
        "diff_effect_upper_log2": diff_effect_upper,
        "diff_effect_lower_log2": diff_effect_lower,
        "exact_verification": {
            "upper": upper_exact_report,
            "lower": lower_exact_report,
        },
        "timing": timing,
        "lp_file": lp_target,
    }
    upper_diff_json = os.path.join(json_dir, "upper_diff_trail.json")
    lower_diff_json = os.path.join(json_dir, "lower_diff_trail.json")
    upper_diff_txt = os.path.join(results_dir, "upper_diff_trail.txt")
    lower_diff_txt = os.path.join(results_dir, "lower_diff_trail.txt")
    with open(upper_diff_json, "w", encoding="utf-8") as handle:
        json.dump(diff_upper_trail, handle, indent=2)
    with open(lower_diff_json, "w", encoding="utf-8") as handle:
        json.dump(diff_lower_trail, handle, indent=2)
    with open(upper_diff_txt, "w", encoding="utf-8") as handle:
        handle.write("\n".join(diff_trail_to_lines(diff_upper_trail)) + "\n")
    with open(lower_diff_txt, "w", encoding="utf-8") as handle:
        handle.write("\n".join(diff_trail_to_lines(diff_lower_trail)) + "\n")
    result["diff_trail_files"] = {
        "upper_json": upper_diff_json,
        "upper_txt": upper_diff_txt,
        "lower_json": lower_diff_json,
        "lower_txt": lower_diff_txt,
    }
    probability_log = ""
    if params.get("probtest"):
        probability_started = perf_counter()
        probability_result, probability_log = save_rk_probability_checks(
            result,
            results_dir,
        )
        result["rk_probability_tests"] = probability_result
        print(probability_log, end="")
        timing["probability_test_seconds"] = perf_counter() - probability_started
        result["timing"] = timing
        print(
            "Probability test time: "
            f"{timing['probability_test_seconds']:.6f} seconds"
        )
    else:
        for stale_name in (
            "probability_tests.json",
            "probability_tests.txt",
            "rk_probability_tests.json",
            "rk_probability_tests.txt",
        ):
            stale_base = json_dir if stale_name.endswith(".json") else results_dir
            stale_path = os.path.join(stale_base, stale_name)
            if os.path.exists(stale_path):
                os.remove(stale_path)
    json_path = os.path.join(json_dir, f"{result_name}.json")
    txt_path = os.path.join(results_dir, f"{result_name}.txt")
    md_path = os.path.join(results_dir, f"{result_name}_distinguisher.md")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    with open(txt_path, "w", encoding="utf-8") as handle:
        handle.write("Summary of the results:\n")
        handle.write("Upper Truncated Trail:\n")
        handle.write("\n".join(truncated_trail_to_lines(upper_trail, bm.R0)) + "\n")
        handle.write("Lower Truncated Trail:\n")
        handle.write("\n".join(truncated_trail_to_lines(lower_trail, bm.R1)) + "\n")
        handle.write("Upper differential trail:\n")
        handle.write("\n".join(diff_trail_to_lines(diff_upper_trail)) + "\n")
        handle.write("Lower differential trail:\n")
        handle.write("\n".join(diff_trail_to_lines(diff_lower_trail)) + "\n")
        handle.write(f"Sandwich {rm} rounds in the middle with {mactive_sboxes} active S-boxes\n")
        handle.write("Total probability = p^2*q^2*r = 2^({:.2f}) x 2^({:.2f}) x r\n".format(
            diff_effect_upper * 2, diff_effect_lower * 2))
        handle.write(
            f"Total solving time: {timing['total_solving_seconds']:.6f} seconds\n"
        )
        if timing.get("probability_test_seconds") is not None:
            handle.write(
                "Probability test time: "
                f"{timing['probability_test_seconds']:.6f} seconds\n"
            )
        if probability_log:
            handle.write(probability_log)
    save_markdown_distinguisher(json_path, md_path)


def loadparameters(args):
    params = {"inputfile": "./input.yaml",
              "r0": 2,
              "rm": 3,
              "r1": 2,
              "w0": 6,
              "wm": 3,
              "w1": 6,
              "timelimit": 1200,
              "global_timelimit": None,
              "numofsols": 1,
              "probtest": False,
              "exact_verify": False,
              "exact_verify_timeout_ms": 300000,
              "exact_path_timeout_sec": None,
              "rk_mode": "rk-ladder"}
    if args.inputfile:
        with open(args.inputfile, "r", encoding="utf-8") as input_file:
            doc = yaml.load(input_file, Loader=yaml.FullLoader)
            params.update(doc)
    if args.inputfile:
        params["inputfile"] = args.inputfile
    if args.r0 is not None:
        params["r0"] = args.r0
    if args.rm is not None:
        params["rm"] = args.rm
    if args.r1 is not None:
        params["r1"] = args.r1
    if args.w0 is not None:
        params["w0"] = args.w0
    if args.wm is not None:
        params["wm"] = args.wm
    if args.w1 is not None:
        params["w1"] = args.w1
    if args.timelimit is not None:
        params["timelimit"] = args.timelimit
    if args.global_timelimit is not None:
        if args.global_timelimit <= 0:
            raise ValueError("--global-tl must be greater than zero")
        params["global_timelimit"] = args.global_timelimit
    if args.numofsols is not None:
        params["numofsols"] = args.numofsols
    if args.probtest is not None:
        params["probtest"] = (args.probtest == "t")
    if args.rk_mode is not None:
        params["rk_mode"] = args.rk_mode
    if args.exact_verify_timeout_ms is not None:
        params["exact_verify_timeout_ms"] = args.exact_verify_timeout_ms
    if args.exact_verify is not None:
        params["exact_verify"] = args.exact_verify
    if args.exact_path_timeout_sec is not None:
        if args.exact_path_timeout_sec <= 0:
            raise ValueError("--exact-path-timeout-sec must be greater than zero")
        params["exact_path_timeout_sec"] = args.exact_path_timeout_sec
    return params


def _build_argument_parser():
    parser = ArgumentParser(description="This tool finds the nearly optimum boomerang distinguisher\n"
                                         "Example:\n"
                                         "python3 rkboom.py -r0 2 -rm 3 -r1 2 -w0 6 -wm 3 -w1 6",
                            formatter_class=RawTextHelpFormatter)
    parser.add_argument('-i', '--inputfile', type=str, help="Use an input file in yaml format")
    parser.add_argument('-r0', '--r0', type=int, help="number of rounds covered by E0")
    parser.add_argument('-rm', '--rm', type=int, help="number of rounds covered by Em")
    parser.add_argument('-r1', '--r1', type=int, help="number of rounds covered by E1")
    parser.add_argument('-w0', '--w0', type=int, help="cost of active S-boxes in E0")
    parser.add_argument('-wm', '--wm', type=int, help="cost of active S-boxes in Em")
    parser.add_argument('-w1', '--w1', type=int, help="cost of active S-boxes in E1")
    parser.add_argument('-tl', '--tl', '--timelimit', dest="timelimit", type=int,
                        help="time limit in seconds for each individual MILP optimize")
    parser.add_argument('--global-tl', dest="global_timelimit", type=float,
                        help="wall-time limit in seconds for the complete distinguisher search; default unlimited")
    parser.add_argument('-ns', '--numofsols', type=int, help="number of solutions (currently disabled)")
    parser.add_argument('--probtest', choices=("t", "f"), default=None,
                        help="run optional probability tests: t=open, f=close; default f")
    parser.add_argument('--rk_mode', '--rk-mode', dest="rk_mode",
                        choices=("rk-basic", "rk-ladder", "rk-debug-independent"), default=None,
                        help="related-key mode; default rk-ladder")
    parser.add_argument('--exact-verify-timeout-ms', type=int, default=None,
                        help="Z3 timeout per concrete RKDiff candidate; default 300000 ms")
    parser.add_argument('--exact-verify', action='store_true', default=None,
                        help="enable two-level truncated/concrete exact refinement")
    parser.add_argument('--exact-path-timeout-sec', type=float, default=None,
                        help="overall exact-refinement timeout for one truncated path; default unlimited")
    return parser


def main(argv=None):
    solve_started = perf_counter()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    args = _build_argument_parser().parse_args(argv)
    params = loadparameters(args)
    case_dir_name = result_case_dir_name(params)
    results_dir = os.path.join("results", case_dir_name)
    os.makedirs(results_dir, exist_ok=True)
    terminal_log_path = os.path.join(results_dir, "terminal_print.txt")

    with _tee_terminal_output(terminal_log_path):
        global_limit = params.get("global_timelimit")
        global_deadline = (
            solve_started + float(global_limit)
            if global_limit is not None
            else None
        )
        try:
            result = _run_search(
                params,
                results_dir,
                solve_started=solve_started,
                global_deadline=global_deadline,
            )
            print(f"Results saved in {results_dir}")
            return result
        except BaseException:
            traceback.print_exc()
            print(f"Total solving time before failure: {perf_counter() - solve_started:.6f} seconds")
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
