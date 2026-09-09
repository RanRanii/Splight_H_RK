import json
import os
import sys
from pathlib import Path
from time import perf_counter

import pytest


PROJECT_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = Path(__file__).resolve().parents[3]
IMPLEMENT_DIR = WORKSPACE_DIR / "Splight_implement" / "implement_py"
sys.path.insert(0, str(IMPLEMENT_DIR))

from enc import SplightParams, key_schedule, nibbles_to_hex  # noqa: E402
from rkboom import (  # noqa: E402
    _build_argument_parser,
    _tee_terminal_output,
    loadparameters,
    result_case_dir_name,
    run_exact_two_level_search,
    solve_rkdiff_until_exact_sat,
)
from rkdiff import RKDiff  # noqa: E402
from rktruncboom import RKTruncatedBoomerang  # noqa: E402
from probability.rk_probability_evaluator import (  # noqa: E402
    evaluate_total_boomerang_probability,
    load_probability_input_from_result_dir,
)
from tools.rk_exact_verify import verify_fixed_differences, verify_trail  # noqa: E402
from tools.maintenance.refresh_result_round_ks import (  # noqa: E402
    rename_result_directory,
    update_saved_result_paths,
)


def _objective_coefficients(model):
    objective = model.getObjective()
    return sorted(
        (objective.getVar(index).VarName, objective.getCoeff(index))
        for index in range(objective.size())
    )


def test_terminal_output_is_mirrored_and_streams_are_restored(tmp_path, capsys):
    log_path = tmp_path / "terminal_print.txt"
    stdout_before = sys.stdout
    stderr_before = sys.stderr

    with _tee_terminal_output(log_path):
        print("stdout marker")
        print("stderr marker", file=sys.stderr)

    assert sys.stdout is stdout_before
    assert sys.stderr is stderr_before
    captured = capsys.readouterr()
    assert "stdout marker" in captured.out
    assert "stderr marker" in captured.err
    assert log_path.read_text(encoding="utf-8") == "stdout marker\nstderr marker\n"


def test_probability_input_prefers_saved_exact_accepted_trails():
    case_dir = PROJECT_DIR / "results" / "4-4-4_636"
    recovered, provenance = load_probability_input_from_result_dir(case_dir)
    accepted_upper = json.loads(
        (case_dir / "truncated_0001" / "upper" / "accepted.json").read_text()
    )
    accepted_lower = json.loads(
        (case_dir / "truncated_0001" / "lower" / "accepted.json").read_text()
    )

    assert provenance["source"] == "exact_accepted"
    assert provenance["accepted_truncated_id"] == 1
    assert recovered["diff_upper_trail"] == accepted_upper["characteristic"]
    assert recovered["diff_lower_trail"] == accepted_lower["characteristic"]
    assert recovered["parameters"]["r0"] == 4
    assert recovered["parameters"]["rm"] == 4
    assert recovered["parameters"]["r1"] == 4


def test_probability_input_uses_formal_json_when_exact_result_is_absent(tmp_path):
    source = PROJECT_DIR / "results" / "4-4-4_636" / ".json" / "4-4-4.json"
    case_dir = tmp_path / "4-4-4"
    json_dir = case_dir / ".json"
    json_dir.mkdir(parents=True)
    (json_dir / "4-4-4.json").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    recovered, provenance = load_probability_input_from_result_dir(case_dir)

    assert provenance["source"] == "formal_result"
    assert provenance["accepted_truncated_id"] is None
    assert recovered["diff_upper_trail"] is not None
    assert recovered["diff_lower_trail"] is not None


def test_probability_input_accepts_weighted_case_directory(tmp_path):
    source = PROJECT_DIR / "results" / "4-4-4_636" / ".json" / "4-4-4.json"
    case_dir = tmp_path / "4-4-4_636"
    json_dir = case_dir / ".json"
    json_dir.mkdir(parents=True)
    (json_dir / "4-4-4.json").write_text(
        source.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    recovered, provenance = load_probability_input_from_result_dir(case_dir)

    assert provenance["source"] == "formal_result"
    assert Path(provenance["formal_result_file"]).name == "4-4-4.json"
    assert recovered["parameters"]["r0"] == 4
    assert recovered["parameters"]["rm"] == 4
    assert recovered["parameters"]["r1"] == 4


def test_result_case_directory_name_includes_weight_coefficients():
    base = {"r0": 1, "rm": 1, "r1": 1}

    assert result_case_dir_name({**base, "w0": 4, "wm": 2, "w1": 4}) == "1-1-1_424"
    assert result_case_dir_name({**base, "w0": 6, "wm": 3, "w1": 6}) == "1-1-1_636"


def test_legacy_result_directory_can_be_renamed_without_overwrite(tmp_path):
    legacy_dir = tmp_path / "1-1-1"
    json_dir = legacy_dir / ".json"
    json_dir.mkdir(parents=True)
    result = {
        "parameters": {"r0": 1, "rm": 1, "r1": 1, "w0": 4, "wm": 2, "w1": 4}
    }
    (json_dir / "1-1-1.json").write_text(json.dumps(result), encoding="utf-8")

    renamed_dir, status, errors = rename_result_directory(legacy_dir)

    assert status == "renamed"
    assert errors == []
    assert renamed_dir.name == "1-1-1_424"
    assert (renamed_dir / ".json" / "1-1-1.json").is_file()
    assert not legacy_dir.exists()

    conflicting_legacy = tmp_path / "1-1-1"
    conflicting_legacy.mkdir()
    (conflicting_legacy / ".json").mkdir()
    (conflicting_legacy / ".json" / "1-1-1.json").write_text(
        json.dumps(result), encoding="utf-8"
    )
    unchanged_dir, status, errors = rename_result_directory(conflicting_legacy)
    assert unchanged_dir == conflicting_legacy
    assert status == "target-exists"
    assert errors


def test_saved_result_paths_follow_renamed_case_directory():
    result = {
        "diff_trail_files": {
            "upper_json": "results\\1-1-1\\.json\\upper_diff_trail.json",
            "lower_txt": "results/1-1-1/lower_diff_trail.txt",
        }
    }

    update_saved_result_paths(result, "1-1-1", "1-1-1_424")

    assert result["diff_trail_files"]["upper_json"].startswith("results\\1-1-1_424\\")
    assert result["diff_trail_files"]["lower_txt"].startswith("results/1-1-1_424/")


def test_probability_input_never_uses_unreferenced_exact_candidate(tmp_path):
    source = PROJECT_DIR / "results" / "4-4-4_636" / ".json" / "4-4-4.json"
    case_dir = tmp_path / "4-4-4"
    json_dir = case_dir / ".json"
    json_dir.mkdir(parents=True)
    (json_dir / "4-4-4.json").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (case_dir / "exact_summary.json").write_text(
        json.dumps({
            "result": "SUCCESS",
            "upper_summary": {"accepted_truncated_id": 9},
            "lower_summary": {"accepted_truncated_id": 9},
        }),
        encoding="utf-8",
    )

    _, provenance = load_probability_input_from_result_dir(case_dir)

    assert provenance["source"] == "formal_result_fallback_after_invalid_exact"
    assert "missing result file" in provenance["exact_recovery_error"]


def test_total_boomerang_probability_uses_measured_p_r_q():
    rkdiff = {
        "upper": {"result": {"probability": 2 ** -3, "skipped": False}},
        "lower": {"result": {"probability": 2 ** -5, "skipped": False}},
    }
    em = {"estimated_r": 2 ** -7, "skipped": False}

    total = evaluate_total_boomerang_probability(rkdiff, em)

    assert total["available"] is True
    assert total["probability"] == pytest.approx(2 ** -23)
    assert total["negative_log2"] == pytest.approx(23.0)
    assert total["display"] == "2^(-23.000000)"


def test_saved_743_rejected_upper_candidate_is_unsat():
    path = (
        PROJECT_DIR
        / "results"
        / "7-4-3_636"
        / "truncated_0001"
        / "upper"
        / "rejected"
        / "candidate_0001.json"
    )
    candidate = json.loads(path.read_text(encoding="utf-8"))
    trail = {
        "rounds": candidate["characteristic"]["nrounds"],
        "round_offset": candidate["round_offset"],
        "fixed_diffs": candidate["fixed_diffs"],
    }
    result = verify_trail(trail, timeout_ms=300_000)
    assert result["status"] == "UNSAT"


def test_full_trail_nogood_changes_signature_without_changing_objective(tmp_path):
    diff = RKDiff({"nrounds": 1, "timelimit": 30, "startweight": 0})
    diff.lp_file_name = os.path.relpath(tmp_path / "rkdiff_nogood.lp", PROJECT_DIR)
    diff.make_model()

    first = diff.optimize_next_candidate()
    assert first["trail"] is not None
    candidate = diff.extract_solution_for_exact_verify()
    signature_before = tuple(candidate["nogood_assignment"])
    objective_before = _objective_coefficients(diff.milp_model)
    weight_before = candidate["weight"]

    name = diff.add_solution_nogood(candidate, scope="test", candidate_id=1)
    assert diff.milp_model.getConstrByName(name) is not None
    assert _objective_coefficients(diff.milp_model) == objective_before

    second = diff.optimize_next_candidate()
    assert second["trail"] is not None
    signature_after = tuple(diff.concrete_solution_signature())
    assert signature_after != signature_before
    assert second["weight"] >= weight_before
    assert _objective_coefficients(diff.milp_model) == objective_before
    assert diff.milp_model.getConstrByName("fix_best_weight_upper") is None
    assert diff.milp_model.getConstrByName("fix_best_weight_lower") is None


def test_nonzero_round_offset_uses_matching_reference_round_key():
    offset = 4
    key_diff = "00000000000000002000000000020002"
    result = verify_fixed_differences(
        rounds=1,
        round_offset=offset,
        fixed_diffs={"dK": key_diff},
        timeout_ms=300_000,
        return_witness=True,
        return_all_diffs=True,
    )
    assert result["status"] == "SAT"
    assert result["witness"]["concrete_replay"] == "PASS"

    witness = result["witness"]
    params = SplightParams(rounds=offset + 1)
    round_keys_a = key_schedule(witness["master_key_A"], params)
    round_keys_b = key_schedule(witness["master_key_B"], params)
    actual_diff = (
        int(nibbles_to_hex(round_keys_a[offset]), 16)
        ^ int(nibbles_to_hex(round_keys_b[offset]), 16)
    )
    assert f"{actual_diff:08X}" == witness["all_diffvariables"]["dRK0"]


def test_lower_objective_counts_only_e1_state_and_key_sboxes():
    diff = RKDiff({"nrounds": 2, "round_offset": 5, "timelimit": 30})
    diff.generate_key_schedule_constraints()
    for round_index in range(diff.nrounds):
        diff.generate_round_constraints(round_index)

    objective_vars = {name for _, name in diff.weight_terms}
    key_groups = [
        group for group in diff.sbox_probability_groups if group["tag"][1] == "key"
    ]
    state_groups = [
        group for group in diff.sbox_probability_groups if group["tag"][1].startswith("state-")
    ]

    assert {group["tag"][0] for group in key_groups} == set(range(7))
    assert all(
        not objective_vars.intersection(group["pr"])
        for group in key_groups
        if group["tag"][0] < 5
    )
    assert all(
        objective_vars.issuperset(group["pr"])
        for group in key_groups
        if group["tag"][0] >= 5
    )
    assert all(objective_vars.issuperset(group["pr"]) for group in state_groups)


def test_truncated_path_nogood_reuses_model_and_changes_signature(tmp_path):
    bm = RKTruncatedBoomerang(1, 1, 1, 6, 3, 6, time_limit=30)
    bm.lp_file_name = os.path.relpath(tmp_path / "truncated_nogood.lp", PROJECT_DIR)
    bm.make_model()
    bm.load_model()
    model_id = id(bm.milp_model)

    first = bm.optimize_next_truncated_path()
    assert first["solution"] is not None
    snapshot = bm.extract_current_truncated_path()
    signature_before = tuple(snapshot["signature"])
    objective_before = _objective_coefficients(bm.milp_model)

    name = bm.add_truncated_path_nogood(snapshot, truncated_id=1)
    assert name == "truncated_nogood_0001"
    second = bm.optimize_next_truncated_path()
    assert second["solution"] is not None
    assert id(bm.milp_model) == model_id
    assert tuple(bm.truncated_solution_signature()) != signature_before
    assert _objective_coefficients(bm.milp_model) == objective_before


class _UnknownDiff:
    nrounds = 1
    round_offset = 0

    def __init__(self):
        self.milp_model = object()
        self.nogood_calls = 0

    def optimize_next_candidate(self, output_flag=False):
        return {"status": "OPTIMAL", "trail": {}, "weight": 2.0}

    def extract_solution_for_exact_verify(self):
        characteristic = {
            "nrounds": 1,
            "round_offset": 0,
            "master_key_diff": "0" * 32,
            "total_weight": "2.00",
            "x_0": "0" * 16,
            "x_1": "0" * 16,
            "y_0": "0" * 8,
            "l_0": "0" * 8,
            "rk_0": "0" * 8,
            "ak_0": "0" * 8,
            "z_0": "0" * 8,
            "round_ks_0": "0" * 32,
            "pr_0": "-2",
            "rw_0": "-2",
            "kw_0": "-0",
        }
        return {
            "trail": {"rounds": 1, "round_offset": 0, "fixed_diffs": {}},
            "characteristic": characteristic,
            "nogood_assignment": [("x_0_0_0", 0)],
            "weight": 2.0,
        }

    def add_solution_nogood(self, *args, **kwargs):
        self.nogood_calls += 1


def test_unknown_candidate_is_timeout_skipped_without_concrete_nogood(tmp_path):
    diff = _UnknownDiff()

    def unknown_verifier(*args, **kwargs):
        return {
            "status": "UNKNOWN",
            "reason": "timeout",
            "elapsed_seconds": 0.001,
            "witness": None,
        }

    characteristic, report = solve_rkdiff_until_exact_sat(
        diff,
        "upper",
        str(tmp_path),
        1,
        [],
        timeout_ms=1,
        verifier=unknown_verifier,
    )
    assert characteristic is None
    assert report["result"] == "TIMEOUT_SKIPPED"
    assert report["reason"] == "Z3_TIMEOUT"
    assert report["unknown_candidates"] == 1
    assert diff.nogood_calls == 0
    assert (tmp_path / "unknown" / "candidate_0001.json").exists()
    assert not (tmp_path / "rejected" / "candidate_0001.json").exists()


def _fake_truncated_trail(rounds):
    trail = {"mk": "0" * 32}
    for r in range(rounds + 1):
        trail[f"x_{r}"] = "0" * 16
        for family in ("y", "l", "rk", "ak", "z"):
            trail[f"{family}_{r}"] = "0" * 8 if r < rounds else "none"
    return trail


class _FakeTruncatedBoomerang:
    r0 = 1
    rm = 1
    r1 = 1
    R0 = 2
    R1 = 2

    def __init__(self, path_count):
        self.path_count = path_count
        self.optimize_calls = 0
        self.nogood_ids = []
        self.milp_model = None

    def make_model(self):
        return "fake.lp"

    def load_model(self):
        self.milp_model = object()

    def optimize_next_truncated_path(self, output_flag=False):
        self.optimize_calls += 1
        if self.optimize_calls > self.path_count:
            return {"status": "INFEASIBLE", "solution": None}
        return {"status": "OPTIMAL", "solution": {}, "objective": 0.0}

    def extract_current_truncated_path(self):
        activity = {
            "upper_trail": _fake_truncated_trail(self.R0),
            "lower_trail": _fake_truncated_trail(self.R1),
            "middle_part": {"s_0": "0" * 16, "ks_0": "00", "as": 0},
        }
        return {
            "objective": 0.0,
            "signature": [("ux_0_0", self.optimize_calls % 2)],
            "activity": activity,
        }

    def parse_solver_output(self):
        return None

    def add_truncated_path_nogood(
        self, snapshot, truncated_id=None, constraint_name=None
    ):
        name = constraint_name or f"truncated_nogood_{truncated_id:04d}"
        self.nogood_ids.append(truncated_id if truncated_id is not None else name)
        return name


class _FakePreflightDiff:
    def __init__(self, feasible=True):
        self.feasible = feasible

    def optimize_next_candidate(self, output_flag=False):
        if self.feasible:
            return {"status": "OPTIMAL", "trail": {}, "weight": 1.0}
        return {"status": "INFEASIBLE", "trail": None, "weight": None}


def _fake_diff_builder(*args, **kwargs):
    return _FakePreflightDiff(), []


def test_outer_loop_blocks_concrete_exhausted_path(tmp_path):
    bm = _FakeTruncatedBoomerang(path_count=1)

    def exhausted_inner(*args, **kwargs):
        truncated_id = args[3]
        return None, {
            "truncated_id": truncated_id,
            "side": args[1],
            "result": "CONCRETE_EXHAUSTED",
            "total_candidates": 3,
            "rejected_candidates": 3,
            "unknown_candidates": 0,
            "elapsed_seconds": 1.0,
        }

    result = run_exact_two_level_search(
        bm,
        {"exact_verify_timeout_ms": 1, "exact_path_timeout_sec": None},
        str(tmp_path),
        diff_builder=_fake_diff_builder,
        inner_solver=exhausted_inner,
    )
    assert result["result"] == "NO_EXACT_REALIZABLE_TRAIL"
    assert bm.nogood_ids == [1]
    assert bm.optimize_calls == 2
    summary = json.loads(
        (tmp_path / "truncated_0001" / "summary.json").read_text()
    )
    assert summary["result"] == "CONCRETE_EXHAUSTED"
    assert summary["truncated_nogood"] == "truncated_nogood_0001"


def test_outer_loop_blocks_timeout_path_but_reports_incomplete(tmp_path):
    bm = _FakeTruncatedBoomerang(path_count=1)

    def timeout_inner(*args, **kwargs):
        truncated_id = args[3]
        return None, {
            "truncated_id": truncated_id,
            "side": args[1],
            "result": "TIMEOUT_SKIPPED",
            "reason": "Z3_TIMEOUT",
            "total_candidates": 1,
            "rejected_candidates": 0,
            "unknown_candidates": 1,
            "elapsed_seconds": 1.0,
        }

    result = run_exact_two_level_search(
        bm,
        {"exact_verify_timeout_ms": 1, "exact_path_timeout_sec": None},
        str(tmp_path),
        diff_builder=_fake_diff_builder,
        inner_solver=timeout_inner,
    )
    assert result["result"] == "SEARCH_INCOMPLETE_TIMEOUT"
    assert bm.nogood_ids == [1]
    assert bm.optimize_calls == 2
    assert result["upper_summary"]["timeout_skipped_paths"] == 1


def test_raw_infeasible_path_is_not_numbered_or_saved(tmp_path):
    bm = _FakeTruncatedBoomerang(path_count=2)

    def preflight_builder(bm, side, *args, **kwargs):
        feasible = not (bm.optimize_calls == 1 and side == "lower")
        return _FakePreflightDiff(feasible=feasible), []

    def timeout_inner(*args, **kwargs):
        truncated_id = args[3]
        return None, {
            "truncated_id": truncated_id,
            "side": args[1],
            "result": "TIMEOUT_SKIPPED",
            "reason": "Z3_TIMEOUT",
            "total_candidates": 1,
            "rejected_candidates": 0,
            "unknown_candidates": 1,
            "elapsed_seconds": 1.0,
        }

    result = run_exact_two_level_search(
        bm,
        {"exact_verify_timeout_ms": 1, "exact_path_timeout_sec": None},
        str(tmp_path),
        diff_builder=preflight_builder,
        inner_solver=timeout_inner,
    )
    assert result["result"] == "SEARCH_INCOMPLETE_TIMEOUT"
    assert result["raw_truncated_candidates"] == 2
    assert result["raw_rejected_before_results"] == 1
    assert bm.nogood_ids == ["raw_truncated_nogood_0001", 1]
    assert not (tmp_path / "truncated_0002").exists()
    assert (tmp_path / "truncated_0001" / "truncated_path.json").exists()
    assert (tmp_path / "truncated_0001" / "upper").is_dir()
    assert (tmp_path / "truncated_0001" / "lower").is_dir()
    assert not (tmp_path / "upper_exact").exists()
    assert not (tmp_path / "lower_exact").exists()
    assert result["upper_summary"]["truncated_paths_tested"] == 1


def test_cli_keeps_per_milp_and_global_time_limits_separate():
    args = _build_argument_parser().parse_args(["--tl", "7", "--global-tl", "11"])
    params = loadparameters(args)

    assert params["timelimit"] == 7
    assert params["global_timelimit"] == 11


def test_expired_global_limit_stops_before_first_truncated_optimize(tmp_path):
    bm = _FakeTruncatedBoomerang(path_count=1)

    result = run_exact_two_level_search(
        bm,
        {"exact_verify_timeout_ms": 1, "exact_path_timeout_sec": None},
        str(tmp_path),
        diff_builder=_fake_diff_builder,
        global_deadline=perf_counter() - 1,
    )

    assert result["result"] == "GLOBAL_TIME_LIMIT"
    assert bm.optimize_calls == 0
    assert bm.nogood_ids == []
