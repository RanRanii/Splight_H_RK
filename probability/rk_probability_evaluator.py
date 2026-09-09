"""Related-key probability checks used by rkboom.py."""

import json
import math
import re
import sys
import contextlib
import io
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
IMPL_DIR = ROOT / "Splight_implement" / "implement_py"
PROB_TEST_DIR = IMPL_DIR / "probability_tests"
sys.path.insert(0, str(IMPL_DIR))
sys.path.insert(0, str(PROB_TEST_DIR))
sys.path.insert(0, str(BASE))

from enc import (  # noqa: E402
    SplightParams,
    encrypt_state,
    hex_to_nibbles,
    key_schedule,
    nibbles_to_hex,
    rot_left_nibbles,
    rot_right_nibbles,
    round_function,
    xor_nibbles,
)
from keydiff import solve_key_schedule_diff_milp  # noqa: E402
from probability_test import SplitMix64, random_hex, run_experiment, xor_hex  # noqa: E402
from splight.sbox_constraints import ddt_weight  # noqa: E402


MAX_DATA_EXPONENT = 16
MIN_EM_DATA_EXPONENT = 12
BLOCK_HEX_LEN = 16
KEY_HEX_LEN = 32


class ResultRecoveryError(RuntimeError):
    """Raised when a saved search result cannot safely drive probtest."""


def _read_result_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ResultRecoveryError(f"missing result file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ResultRecoveryError(f"invalid JSON result file: {path}") from exc
    if not isinstance(data, dict):
        raise ResultRecoveryError(f"result JSON must be an object: {path}")
    return data


def _parse_result_rounds(result_dir):
    match = re.fullmatch(r"(\d+)-(\d+)-(\d+)(?:_\d+)?", Path(result_dir).name)
    if match is None:
        raise ResultRecoveryError(
            "result directory name must be <r0>-<rm>-<r1> or "
            "<r0>-<rm>-<r1>_<w0><wm><w1>, "
            f"got {Path(result_dir).name!r}"
        )
    return tuple(int(value) for value in match.groups())


def _load_primary_result_json(result_dir):
    result_dir = Path(result_dir)
    case_name = result_dir.name
    r0, rm, r1 = _parse_result_rounds(result_dir)
    artifact_name = f"{r0}-{rm}-{r1}"
    names = list(dict.fromkeys((artifact_name, case_name)))
    candidates = []
    for name in names:
        candidates.extend((
            result_dir / ".json" / f"{name}.json",
            result_dir / f"{name}.json",
        ))
    for candidate in candidates:
        if candidate.is_file():
            return _read_result_json(candidate), candidate
    return None, None


def _normalise_saved_parameters(primary_result, result_dir):
    r0, rm, r1 = _parse_result_rounds(result_dir)
    parameters = dict((primary_result or {}).get("parameters") or {})
    parameters.update({"r0": r0, "rm": rm, "r1": r1})
    parameters.setdefault("timelimit", 1200)
    parameters.setdefault("rk_mode", "rk-ladder")
    parameters.setdefault("probtest", True)
    return parameters


def _load_exact_probability_input(result_dir, exact_summary, primary_result, primary_path):
    if exact_summary.get("result") != "SUCCESS":
        raise ResultRecoveryError(
            "exact_summary.json does not report SUCCESS; no accepted exact trail is available"
        )
    upper_summary = exact_summary.get("upper_summary") or {}
    lower_summary = exact_summary.get("lower_summary") or {}
    accepted_ids = {
        value
        for value in (
            exact_summary.get("accepted_truncated_id"),
            upper_summary.get("accepted_truncated_id"),
            lower_summary.get("accepted_truncated_id"),
        )
        if value is not None
    }
    if len(accepted_ids) != 1:
        raise ResultRecoveryError(
            "exact_summary.json does not identify one shared accepted truncated_id"
        )
    truncated_id = int(accepted_ids.pop())
    path_dir = Path(result_dir) / f"truncated_{truncated_id:04d}"
    truncated_path = _read_result_json(path_dir / "truncated_path.json")
    upper_path = path_dir / "upper" / "accepted.json"
    lower_path = path_dir / "lower" / "accepted.json"
    upper_accepted = _read_result_json(upper_path)
    lower_accepted = _read_result_json(lower_path)

    for side, accepted in (("upper", upper_accepted), ("lower", lower_accepted)):
        if accepted.get("truncated_id") != truncated_id:
            raise ResultRecoveryError(
                f"{side} accepted trail truncated_id does not match exact_summary.json"
            )
        if accepted.get("status") != "SAT":
            raise ResultRecoveryError(f"{side} accepted trail status is not SAT")
        if accepted.get("concrete_replay") != "PASS":
            raise ResultRecoveryError(f"{side} accepted trail replay is not PASS")
        if not isinstance(accepted.get("characteristic"), dict):
            raise ResultRecoveryError(f"{side} accepted trail has no characteristic object")

    missing = [
        key for key in ("upper_trail", "middle_part", "lower_trail")
        if not isinstance(truncated_path.get(key), dict)
    ]
    if missing:
        raise ResultRecoveryError(
            "accepted truncated path lacks required fields: " + ", ".join(missing)
        )
    result = {
        "parameters": _normalise_saved_parameters(primary_result, result_dir),
        "upper_trail": truncated_path["upper_trail"],
        "middle_part": truncated_path["middle_part"],
        "lower_trail": truncated_path["lower_trail"],
        "diff_upper_trail": upper_accepted["characteristic"],
        "diff_lower_trail": lower_accepted["characteristic"],
    }
    provenance = {
        "source": "exact_accepted",
        "accepted_truncated_id": truncated_id,
        "exact_summary_file": str(Path(result_dir) / "exact_summary.json"),
        "truncated_path_file": str(path_dir / "truncated_path.json"),
        "upper_trail_file": str(upper_path),
        "lower_trail_file": str(lower_path),
        "formal_result_file": str(primary_path) if primary_path else None,
    }
    return result, provenance


def _load_formal_probability_input(result_dir, primary_result, primary_path):
    if primary_result is None:
        raise ResultRecoveryError(
            "missing formal result JSON; expected the round-only or full-case "
            "JSON basename under .json/ or the case directory. Text trails "
            "alone do not retain the key-state "
            "alignment required for RK Em probability testing."
        )
    required = (
        "upper_trail",
        "middle_part",
        "lower_trail",
        "diff_upper_trail",
        "diff_lower_trail",
    )
    missing = [key for key in required if key not in primary_result]
    if missing:
        raise ResultRecoveryError(
            "formal result JSON lacks required fields: " + ", ".join(missing)
        )
    result = {
        "parameters": _normalise_saved_parameters(primary_result, result_dir),
        "upper_trail": primary_result["upper_trail"],
        "middle_part": primary_result["middle_part"],
        "lower_trail": primary_result["lower_trail"],
        "diff_upper_trail": primary_result["diff_upper_trail"],
        "diff_lower_trail": primary_result["diff_lower_trail"],
    }
    provenance = {
        "source": "formal_result",
        "accepted_truncated_id": None,
        "formal_result_file": str(primary_path),
        "upper_trail_file": str(primary_path) + "#diff_upper_trail",
        "lower_trail_file": str(primary_path) + "#diff_lower_trail",
    }
    return result, provenance


def load_probability_input_from_result_dir(result_dir):
    """Recover a saved final trail for the existing RK probability evaluator.

    Exact results are accepted only through the truncated id recorded in
    exact_summary.json. If that chain is incomplete, the formal result JSON is
    used as the documented non-exact fallback; rejected/unknown candidates are
    never considered.
    """

    result_dir = Path(result_dir).resolve()
    if not result_dir.is_dir():
        raise ResultRecoveryError(f"result directory does not exist: {result_dir}")
    _parse_result_rounds(result_dir)
    primary_result, primary_path = _load_primary_result_json(result_dir)
    exact_path = result_dir / "exact_summary.json"
    if exact_path.is_file():
        try:
            return _load_exact_probability_input(
                result_dir,
                _read_result_json(exact_path),
                primary_result,
                primary_path,
            )
        except ResultRecoveryError as exact_error:
            try:
                result, provenance = _load_formal_probability_input(
                    result_dir, primary_result, primary_path
                )
            except ResultRecoveryError as formal_error:
                raise ResultRecoveryError(
                    f"exact result recovery failed: {exact_error}; "
                    f"formal fallback failed: {formal_error}"
                ) from formal_error
            provenance["exact_recovery_error"] = str(exact_error)
            provenance["source"] = "formal_result_fallback_after_invalid_exact"
            return result, provenance
    return _load_formal_probability_input(result_dir, primary_result, primary_path)


def today_seed():
    return int(datetime.now().strftime("%Y%m%d"))


def log2_or_none(value):
    return None if value <= 0 else math.log2(value)


def data_exponent(weight):
    return int(math.ceil(float(weight))) + 2


def data_size_from_exponent(exponent):
    return 2 ** int(exponent)


def should_skip(exponent):
    return int(exponent) >= MAX_DATA_EXPONENT


def skipped_result(kind, exponent, reason):
    return {
        "kind": kind,
        "skipped": True,
        "data_size_exponent": int(exponent),
        "data_size": f"2^({int(exponent)})",
        "reason": reason,
    }


def mask_to_concrete_hex(mask):
    return "".join("1" if ch != "0" else "0" for ch in mask).upper()


def encrypt_segment_state(state_hex, master_key_hex, rounds, round_offset):
    p = SplightParams(rounds=round_offset + rounds)
    state = hex_to_nibbles(state_hex, expected_len=BLOCK_HEX_LEN)
    left = state[:p.branch_nibbles]
    right = state[p.branch_nibbles:]
    round_keys = key_schedule(master_key_hex, p)
    for rk in round_keys[round_offset:round_offset + rounds]:
        f_out = round_function(left, rk, p)
        new_left = rot_left_nibbles(xor_nibbles(f_out, right), p.round_shift)
        new_right = left
        left, right = new_left, new_right
    return nibbles_to_hex(left + right)


def encrypt_segment_from_key_state(state_hex, key_state_hex, rounds, round_offset):
    """Encrypt a segment whose 128-bit key state is fixed at round_offset."""
    p = SplightParams(rounds=rounds, round_const_start=round_offset)
    return encrypt_state(state_hex, key_state_hex, p)


def decrypt_segment_state(state_hex, master_key_hex, rounds, round_offset):
    p = SplightParams(rounds=round_offset + rounds)
    state = hex_to_nibbles(state_hex, expected_len=BLOCK_HEX_LEN)
    left = state[:p.branch_nibbles]
    right = state[p.branch_nibbles:]
    round_keys = key_schedule(master_key_hex, p)
    for rk in reversed(round_keys[round_offset:round_offset + rounds]):
        prev_left = right
        prev_right = xor_nibbles(
            round_function(prev_left, rk, p),
            rot_right_nibbles(left, p.round_shift),
        )
        left, right = prev_left, prev_right
    return nibbles_to_hex(left + right)


def run_rkdiff_experiment(trail, seed, data_size):
    rng = SplitMix64(seed)
    rounds = int(trail["nrounds"])
    round_offset = int(trail.get("round_offset", 0))
    key_diff = trail["master_key_diff"].upper()
    input_diff = trail["x_0"].upper()
    output_diff = trail[f"x_{rounds}"].upper()
    right = 0
    for _ in range(data_size):
        key0 = random_hex(rng, KEY_HEX_LEN)
        key1 = xor_hex(key0, key_diff, KEY_HEX_LEN)
        p0 = random_hex(rng, BLOCK_HEX_LEN)
        p1 = xor_hex(p0, input_diff, BLOCK_HEX_LEN)
        c0 = encrypt_segment_state(p0, key0, rounds, round_offset)
        c1 = encrypt_segment_state(p1, key1, rounds, round_offset)
        if xor_hex(c0, c1, BLOCK_HEX_LEN).upper() == output_diff:
            right += 1
    probability = right / data_size
    return {
        "mode": "rkdiff",
        "rounds": rounds,
        "round_offset": round_offset,
        "input_diff": input_diff,
        "output_diff": output_diff,
        "key_diff": key_diff,
        "trials": 1,
        "data_size_count": data_size,
        "right": right,
        "total": data_size,
        "probability": probability,
    }


def run_lower_rkdiff_experiment(trail, seed, data_size):
    """Test E1 from its absolute-round key state, not from global ks_0."""
    rng = SplitMix64(seed)
    rounds = int(trail["nrounds"])
    round_offset = int(trail.get("round_offset", 0))
    key_state_name = f"ks_global_{round_offset}"
    if key_state_name not in trail:
        raise ResultRecoveryError(
            f"lower concrete trail lacks required E1 key state: {key_state_name}"
        )
    key_diff = trail[key_state_name].upper()
    input_diff = trail["x_0"].upper()
    output_diff = trail[f"x_{rounds}"].upper()
    right = 0
    for _ in range(data_size):
        key0 = random_hex(rng, KEY_HEX_LEN)
        key1 = xor_hex(key0, key_diff, KEY_HEX_LEN)
        p0 = random_hex(rng, BLOCK_HEX_LEN)
        p1 = xor_hex(p0, input_diff, BLOCK_HEX_LEN)
        c0 = encrypt_segment_from_key_state(p0, key0, rounds, round_offset)
        c1 = encrypt_segment_from_key_state(p1, key1, rounds, round_offset)
        if xor_hex(c0, c1, BLOCK_HEX_LEN).upper() == output_diff:
            right += 1
    probability = right / data_size
    return {
        "mode": "rkdiff",
        "rounds": rounds,
        "round_offset": round_offset,
        "input_diff": input_diff,
        "output_diff": output_diff,
        "key_diff": key_diff,
        "key_diff_source": key_state_name,
        "trials": 1,
        "data_size_count": data_size,
        "right": right,
        "total": data_size,
        "probability": probability,
    }


def run_rkboomerang_segment(delta, nabla, delta_key_diff, nabla_key_diff, rounds, seed, data_size):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        raw = run_experiment(
            overrides={
                "mode": "rkboomerang",
                "rounds": rounds,
                "input_diff": delta,
                "output_diff": nabla,
                "delta_key_diff": delta_key_diff,
                "nabla_key_diff": nabla_key_diff,
                "trials": 1,
                "batch_size": data_size,
                "seed": seed,
            }
        )
    probability = raw["probability"]
    return {
        "mode": "rkboomerang",
        "returned_count": raw["right"],
        "total": raw["total"],
        "estimated_r": probability,
        "log2_r": log2_or_none(probability),
        "probability_test_stdout": buffer.getvalue(),
    }


def trail_key_state(trail, global_round, fallback_round=None):
    if trail is None:
        return None
    key = f"ks_global_{global_round}"
    if key in trail:
        return trail[key]
    if fallback_round is not None and f"ks_{fallback_round}" in trail:
        return trail[f"ks_{fallback_round}"]
    return None


def concrete_key_schedule_details(trail, total_rounds):
    """Recover display details from one accepted concrete key schedule."""
    states = []
    for global_round in range(total_rounds + 1):
        key = f"ks_global_{global_round}"
        if key not in trail:
            return None
        states.append(trail[key].upper())

    params = SplightParams()
    round_details = []
    total_weight = 0
    for global_round in range(total_rounds):
        ks_in = states[global_round]
        ks_out = states[global_round + 1]
        k0 = ks_in[:8]
        k1 = ks_in[8:16]
        rotated_core = xor_hex(ks_out[:8], k1, 8)
        core_output = nibbles_to_hex(
            rot_right_nibbles(
                hex_to_nibbles(rotated_core, expected_len=8),
                params.key_shift,
            )
        )
        by_sbox = {}
        round_weight = 0
        for nibble in params.key_sbox_positions:
            weight = ddt_weight(int(k0[nibble], 16), int(core_output[nibble], 16))
            if not math.isfinite(weight):
                raise ResultRecoveryError(
                    "accepted lower key schedule contains an invalid S-box transition: "
                    f"round={global_round}, nibble={nibble}, "
                    f"input={k0[nibble]}, output={core_output[nibble]}"
                )
            by_sbox[str(nibble)] = int(weight)
            round_weight += int(weight)
        total_weight += round_weight
        round_details.append({
            "round": global_round,
            "ks_in": ks_in,
            "sbox_input_32": k0,
            "ks_out": ks_out,
            "sbox_weight": round_weight,
            "sbox_weight_by_nibble": by_sbox,
            "probability": f"2^(-{round_weight})",
        })

    return {
        "nrounds": total_rounds,
        "states": states,
        "round_details": round_details,
        "input_state": states[0],
        "output_state": states[-1],
        "weight": float(total_weight),
        "probability": f"2^(-{total_weight})",
        "source": "accepted_concrete_trail",
    }


def evaluate_rkdiff_probability(result, seed):
    experiments = {}
    for name, trail in (("upper", result["diff_upper_trail"]), ("lower", result["diff_lower_trail"])):
        if trail is None:
            experiments[name] = {"result": None}
            continue
        theory_weight = float(trail["total_weight"])
        exponent = data_exponent(theory_weight)
        if should_skip(exponent):
            experiments[name] = {
                "result": skipped_result(
                    "rkdiff",
                    exponent,
                    f"data size 2^({exponent}) >= 2^({MAX_DATA_EXPONENT}); skip test",
                )
            }
            continue
        data_size = data_size_from_exponent(exponent)
        if name == "lower":
            exp_result = run_lower_rkdiff_experiment(trail, seed, data_size)
        else:
            exp_result = run_rkdiff_experiment(trail, seed, data_size)
        exp_result["skipped"] = False
        exp_result["data_size_exponent"] = exponent
        exp_result["data_size"] = f"2^({exponent})"
        exp_result["log2_probability"] = log2_or_none(exp_result["probability"])
        exp_result["theory_log2"] = -theory_weight
        experiments[name] = {"result": exp_result}
    return experiments


def evaluate_rk_em_boomerang_probability(result, seed):
    params = result["parameters"]
    r0 = int(params["r0"])
    rm = int(params["rm"])
    common_active = int(result["middle_part"]["as"])
    common_state_active = int(result["middle_part"].get("common_active_state_sboxes", common_active))
    common_key_active = int(result["middle_part"].get("common_active_key_sboxes", 0))
    upper = result.get("diff_upper_trail")
    lower = result.get("diff_lower_trail")
    time_limit = int(params.get("timelimit", 60))
    if upper is None:
        delta = mask_to_concrete_hex(result["upper_trail"][f"x_{r0}"])
        upper_master_key_diff = mask_to_concrete_hex(result["upper_trail"].get("mk", "0" * KEY_HEX_LEN))
        delta_source = f"upper_trail[x_{r0}] active mask mapped to concrete 0x1"
        delta_key_source = f"key_schedule_milp_forward(upper_trail[mk], r0={r0})"
    else:
        delta = upper[f"x_{r0}"]
        upper_master_key_diff = upper["master_key_diff"]
        delta_source = f"diff_upper_trail[x_{r0}]"
        delta_key_source = f"key_schedule_milp_forward(diff_upper_trail[master_key_diff], r0={r0})"
    if lower is None:
        nabla = mask_to_concrete_hex(result["lower_trail"]["x_0"])
        lower_master_key_diff = mask_to_concrete_hex(result["lower_trail"].get("mk", "0" * KEY_HEX_LEN))
        nabla_source = "lower_trail[x_0] active mask mapped to concrete 0x1"
        nabla_key_source = f"key_schedule_milp_backward(lower_trail[mk], rm={rm})"
    else:
        nabla = lower["x_0"]
        lower_em_end_key = lower.get(f"ks_global_{r0 + rm}")
        if lower_em_end_key is None:
            lower_em_end_key = lower.get(f"ks_{int(lower.get('round_offset', r0 + rm))}")
        if lower_em_end_key is None:
            lower_em_end_key = lower["master_key_diff"]
        lower_master_key_diff = lower_em_end_key
        nabla_source = "diff_lower_trail[x_0]"
        nabla_key_source = f"key_schedule_milp_backward(diff_lower_trail[ks_global_{r0 + rm}], rm={rm})"

    delta_key_milp = solve_key_schedule_diff_milp(
        upper_master_key_diff,
        r0,
        "forward",
        time_limit=time_limit,
    )
    nabla_key_milp = solve_key_schedule_diff_milp(
        lower_master_key_diff,
        rm,
        "backward",
        time_limit=time_limit,
    )
    delta_key_diff = delta_key_milp["output_state"]
    nabla_key_diff = nabla_key_milp["input_state"]
    em_weight = 2.0 * common_active
    exponent = max(MIN_EM_DATA_EXPONENT, data_exponent(em_weight))
    base = {
        "mode": "rkboomerang",
        "test_scope": "Em only with related keys",
        "rounds": rm,
        "round_offset": r0,
        "input_diff_delta": delta,
        "output_diff_nabla": nabla,
        "delta_key_diff": delta_key_diff,
        "nabla_key_diff": nabla_key_diff,
        "delta_key_diff_source": delta_key_source,
        "nabla_key_diff_source": nabla_key_source,
        "delta_key_milp": delta_key_milp,
        "nabla_key_milp": nabla_key_milp,
        "delta_source": delta_source,
        "nabla_source": nabla_source,
        "common_active_sboxes": common_active,
        "common_active_state_sboxes": common_state_active,
        "common_active_key_sboxes": common_key_active,
        "hadipour_upper_log2": -2.0 * common_active,
        "hadipour_lower_log2": -2.5 * common_active,
        "data_size_exponent": exponent,
        "data_size": f"2^({exponent})",
    }
    if should_skip(exponent):
        base.update({
            "skipped": True,
            "reason": f"data size 2^({exponent}) >= 2^({MAX_DATA_EXPONENT}); skip test",
        })
        return base
    data_size = data_size_from_exponent(exponent)
    em = run_rkboomerang_segment(delta, nabla, delta_key_diff, nabla_key_diff, rm, seed, data_size)
    em.update(base)
    em["skipped"] = False
    return em


def evaluate_aligned_key_schedule(result):
    params = result["parameters"]
    r0 = int(params["r0"])
    rm = int(params["rm"])
    r1 = int(params["r1"])
    total_rounds = r0 + rm + r1
    time_limit = int(params.get("timelimit", 60))
    upper = result.get("diff_upper_trail")
    lower = result.get("diff_lower_trail")

    if upper is None:
        upper_fixed = mask_to_concrete_hex(result["upper_trail"].get("mk", "0" * KEY_HEX_LEN))
    else:
        upper_fixed = upper["master_key_diff"]
    upper_rounds = r0 + rm
    upper_milp = solve_key_schedule_diff_milp(
        upper_fixed,
        upper_rounds,
        "forward",
        time_limit=time_limit,
    )
    upper_global_start = 0
    upper_states = {
        upper_global_start + index: state
        for index, state in enumerate(upper_milp.get("states", []))
    }
    upper_round_details = {
        upper_global_start + int(item["round"]): item
        for item in upper_milp.get("round_details", [])
    }

    lower_milp = (
        concrete_key_schedule_details(lower, total_rounds)
        if lower is not None
        else None
    )
    if lower_milp is not None:
        lower_global_start = 0
        lower_rounds = total_rounds
        lower_fixed_global = total_rounds
        lower_fixed = lower_milp["output_state"]
    else:
        lower_global_start = r0 + 1
        lower_rounds = max(0, total_rounds - lower_global_start)
        if lower is None:
            lower_fixed = mask_to_concrete_hex(result["lower_trail"].get("mk", "0" * KEY_HEX_LEN))
            lower_fixed_global = total_rounds
        else:
            lower_fixed_global = total_rounds
            lower_fixed = lower.get(f"ks_global_{lower_fixed_global}")
            if lower_fixed is None:
                lower_fixed = lower.get(f"ks_{lower.get('nrounds', 0)}")
            if lower_fixed is None:
                lower_fixed = lower["master_key_diff"]
                lower_fixed_global = 0
        lower_milp = solve_key_schedule_diff_milp(
            lower_fixed,
            lower_rounds,
            "backward",
            time_limit=time_limit,
        )
    lower_states = {
        lower_global_start + index: state
        for index, state in enumerate(lower_milp.get("states", []))
    }
    lower_round_details = {
        lower_global_start + int(item["round"]): item
        for item in lower_milp.get("round_details", [])
    }

    return {
        "total_rounds": total_rounds,
        "em_start_round": r0,
        "em_end_round": r0 + rm,
        "upper": {
            "label": "ksu",
            "direction": "forward",
            "global_start": upper_global_start,
            "global_end": upper_global_start + upper_rounds,
            "fixed_global": 0,
            "fixed_state": upper_fixed,
            "derived_output_global": upper_global_start + upper_rounds,
            "derived_output_state": upper_milp.get("output_state"),
            "milp": upper_milp,
            "states_by_global_round": {str(k): v for k, v in upper_states.items()},
            "round_details_by_global_round": {
                str(k): v for k, v in upper_round_details.items()
            },
        },
        "lower": {
            "label": "ksl",
            "direction": "backward",
            "global_start": lower_global_start,
            "global_end": lower_global_start + lower_rounds,
            "fixed_global": lower_fixed_global,
            "fixed_state": lower_fixed,
            "derived_output_global": lower_global_start,
            "derived_output_state": lower_milp.get("input_state"),
            "milp": lower_milp,
            "states_by_global_round": {str(k): v for k, v in lower_states.items()},
            "round_details_by_global_round": {
                str(k): v for k, v in lower_round_details.items()
            },
        },
    }


def format_log2(value):
    return f"{value:.6f}" if value is not None else "-inf (no right pairs/quartets observed)"


def format_rkdiff_section(label, entry):
    result = entry["result"]
    lines = ["", "-" * 72, f"{label}相关密钥差分概率测试"]
    if result is None:
        lines.append("未生成具体相关密钥差分路径，跳过测试。")
        return lines
    if result.get("skipped"):
        lines.extend([
            "mode          : rkdiff",
            f"data size     : {result['data_size']}",
            f"skip reason   : {result['reason']}",
        ])
        return lines
    lines.extend([
        f"mode          : {result['mode']}",
        f"rounds        : {result['rounds']}",
        f"round offset  : {result['round_offset']}",
        f"input diff    : {result['input_diff']}",
        f"output diff   : {result['output_diff']} (L_r||R_r)",
        f"key diff      : {result['key_diff']}",
        "trials        : 1",
        f"data size     : {result['data_size']}",
        f"trial 0001: right={result['right']} total={result['data_size']} probability={result['probability']:.12g}",
        "-" * 72,
        f"aggregate right pairs/quartets : {result['right']}",
        f"aggregate total pairs/quartets : {result['data_size']}",
        f"estimated probability          : {result['probability']:.12g}",
        f"log2(probability)              : {format_log2(result['log2_probability'])}",
        f"theory log2                    : {format_log2(result['theory_log2'])}",
    ])
    return lines


def format_em_section(em):
    lines = ["", "-" * 72, "Em 中间相关密钥 boomerang switch 概率测试"]
    lines.extend([
        f"mode          : {em['mode']}",
        f"scope         : {em['test_scope']}",
        f"rounds        : {em['rounds']}",
        f"round offset  : {em['round_offset']}",
        f"input diff    : {em['input_diff_delta']} (Delta from upper output)",
        f"output diff   : {em['output_diff_nabla']} (nabla from lower input)",
        f"delta key diff: {em['delta_key_diff']} ({em['delta_key_diff_source']})",
        f"nabla key diff: {em['nabla_key_diff']} ({em['nabla_key_diff_source']})",
        f"common active : {em['common_active_sboxes']}",
        f"  state/key   : {em.get('common_active_state_sboxes', em['common_active_sboxes'])}"
        f"/{em.get('common_active_key_sboxes', 0)}",
        f"data size     : {em['data_size']}",
    ])
    if em.get("skipped"):
        lines.append(f"skip reason   : {em['reason']}")
        return lines
    lines.extend([
        f"trial 0001: returned={em['returned_count']} total={em['data_size']} probability={em['estimated_r']:.12g}",
        "-" * 72,
        f"aggregate returned quartets     : {em['returned_count']}",
        f"aggregate total quartets        : {em['data_size']}",
        f"estimated probability           : {em['estimated_r']:.12g}",
        f"log2(probability)               : {format_log2(em['log2_r'])}",
    ])
    return lines


def format_aligned_key_schedule_section(aligned):
    upper = aligned["upper"]
    lower = aligned["lower"]
    lines = [
        "",
        "-" * 72,
        "Em 前相关密钥调度推导",
        f"upper forward : fixed ks_{upper['fixed_global']} = {upper['fixed_state']}",
        f"                output ks_{upper['derived_output_global']} = {upper['derived_output_state']}",
        f"                total weight = -{upper.get('milp', {}).get('weight', 'none')}",
        f"lower backward: fixed ks_{lower['fixed_global']} = {lower['fixed_state']}",
        f"                output ks_{lower['derived_output_global']} = {lower['derived_output_state']}",
        f"                total weight = -{lower.get('milp', {}).get('weight', 'none')}",
        "",
        "Rounds  ksu                                 ksl                                 u_sbox_in  l_sbox_in  wu      wl     ",
        "-" * 120,
    ]
    upper_states = upper["states_by_global_round"]
    lower_states = lower["states_by_global_round"]
    upper_details = upper.get("round_details_by_global_round", {})
    lower_details = lower.get("round_details_by_global_round", {})
    em_start_round = int(aligned["em_start_round"])
    em_end_round = int(aligned["em_end_round"])
    for r in range(int(aligned["total_rounds"]) + 1):
        if r == em_start_round:
            lines.extend([
                "",
                f" Em start: global round {em_start_round} ".center(120, "-"),
                "",
            ])
        if r == em_end_round:
            lines.extend([
                "",
                f" Em end / E1 start: global round {em_end_round} ".center(120, "-"),
                "",
            ])
        ksu = upper_states.get(str(r), "none")
        ksl = lower_states.get(str(r), "none")
        u_detail = upper_details.get(str(r), {})
        l_detail = lower_details.get(str(r), {})
        u_sbox = u_detail.get("sbox_input_32", "none")
        l_sbox = l_detail.get("sbox_input_32", "none")
        u_weight = u_detail.get("sbox_weight")
        l_weight = l_detail.get("sbox_weight")
        wu = f"-{u_weight}" if u_weight is not None else "none"
        wl = f"-{l_weight}" if l_weight is not None else "none"
        lines.append(f"{r:<7} {ksu:<35} {ksl:<35} {u_sbox:<10} {l_sbox:<10} {wu:<7} {wl:<7}")
    return lines


def evaluate_total_boomerang_probability(rkdiff, em):
    """Combine measured p, r and q as p^2 * r * q^2."""

    components = {
        "p": (rkdiff.get("upper") or {}).get("result"),
        "q": (rkdiff.get("lower") or {}).get("result"),
        "r": em,
    }
    for name, component in components.items():
        if component is None:
            return {
                "formula": "p^2 * r * q^2",
                "available": False,
                "display": None,
                "reason": f"{name} probability result is missing",
            }
        if component.get("skipped"):
            return {
                "formula": "p^2 * r * q^2",
                "available": False,
                "display": None,
                "reason": f"{name} probability test was skipped: {component.get('reason')}",
            }

    p = components["p"].get("probability")
    q = components["q"].get("probability")
    r = components["r"].get("estimated_r")
    if any(value is None for value in (p, q, r)):
        return {
            "formula": "p^2 * r * q^2",
            "available": False,
            "display": None,
            "reason": "at least one measured probability is unavailable",
        }
    p, q, r = float(p), float(q), float(r)
    if min(p, q, r) <= 0:
        return {
            "formula": "p^2 * r * q^2",
            "available": False,
            "p": p,
            "r": r,
            "q": q,
            "probability": 0.0,
            "log2_probability": None,
            "negative_log2": None,
            "display": "2^(-infinity)",
            "reason": "at least one experiment observed zero right pairs/quartets",
        }

    log2_probability = 2.0 * math.log2(p) + math.log2(r) + 2.0 * math.log2(q)
    negative_log2 = -log2_probability
    return {
        "formula": "p^2 * r * q^2",
        "available": True,
        "p": p,
        "r": r,
        "q": q,
        "probability": p ** 2 * r * q ** 2,
        "log2_probability": log2_probability,
        "negative_log2": negative_log2,
        "display": f"2^(-{negative_log2:.6f})",
        "reason": None,
    }


def format_total_boomerang_section(total):
    lines = ["", "-" * 72, "整个相关密钥 boomerang 区分器实验概率"]
    lines.append(f"formula       : {total['formula']}")
    if not total.get("available"):
        if total.get("display"):
            lines.append(f"result        : {total['display']}")
        lines.append(f"status        : unavailable ({total.get('reason')})")
        return lines
    lines.extend([
        f"p             : {total['p']:.12g}",
        f"r             : {total['r']:.12g}",
        f"q             : {total['q']:.12g}",
        f"p^2 * r * q^2: {total['probability']:.12g}",
        f"result        : {total['display']}",
    ])
    return lines


def format_rk_probability_log(probability_result):
    lines = ["", "=" * 72, "搜索后的相关密钥概率实验"]
    lines.extend(format_rkdiff_section("上路径", probability_result["rkdiff"]["upper"]))
    lines.extend(format_rkdiff_section("下路径", probability_result["rkdiff"]["lower"]))
    lines.extend(format_aligned_key_schedule_section(probability_result["aligned_key_schedule"]))
    lines.extend(format_em_section(probability_result["rk_em_boomerang"]))
    lines.extend(format_total_boomerang_section(probability_result["total_boomerang_probability"]))
    return "\n".join(lines) + "\n"


def format_keydiff_milp_log(label, entry):
    probability = entry.get("probability") or f"2^(-{entry.get('weight')})"
    lines = [
        f"{label} key schedule MILP 调用结果",
        "-" * 72,
        f"direction      : {entry.get('direction')}",
        f"nrounds        : {entry.get('nrounds')}",
        f"fixed state    : {entry.get('fixed_state')}",
        f"fixedVariables : {json.dumps(entry.get('fixedVariables', {}), ensure_ascii=False)}",
        f"weight         : {entry.get('weight')}",
        f"probability    : {probability}",
        f"lp file        : {entry.get('lp_file')}",
        "",
        "Rounds  ks_in                               sbox_in_32  ks_out                              sbox weight",
        "-" * 112,
    ]
    for item in entry.get("round_details", []):
        lines.append(
            f"{item.get('round'):<7} "
            f"{item.get('ks_in'):<35} "
            f"{item.get('sbox_input_32'):<11} "
            f"{item.get('ks_out'):<35} "
            f"-{item.get('sbox_weight')} ({item.get('probability')})"
        )
    lines.extend([
        "",
        "Key schedule states:",
    ])
    for index, state in enumerate(entry.get("states", [])):
        lines.append(f"ks_{index:<3} {state}")
    return "\n".join(lines) + "\n"


def run_rk_probability_checks(result, seed=None):
    seed = today_seed() if seed is None else int(seed)
    rkdiff = evaluate_rkdiff_probability(result, seed)
    aligned_key_schedule = evaluate_aligned_key_schedule(result)
    em = evaluate_rk_em_boomerang_probability(result, seed)
    total_boomerang = evaluate_total_boomerang_probability(rkdiff, em)
    return {
        "parameters": {
            "seed": seed,
            "max_data_size": f"2^({MAX_DATA_EXPONENT})",
            "sample_rule": "rkdiff data size = 2^(ceil(weight)+2); RK Em data size = max(2^12, 2^(2*CAS+2)); skip when data size >= 2^16",
        },
        "rkdiff": rkdiff,
        "aligned_key_schedule": aligned_key_schedule,
        "rk_em_boomerang": em,
        "total_boomerang_probability": total_boomerang,
    }


def save_rk_probability_checks(result, output_dir, seed=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_dir = output_dir / ".json"
    json_dir.mkdir(parents=True, exist_ok=True)
    probability_result = run_rk_probability_checks(result, seed)
    (json_dir / "rk_probability_tests.json").write_text(
        json.dumps(probability_result, indent=2),
        encoding="utf-8",
    )
    log_text = format_rk_probability_log(probability_result)
    (output_dir / "rk_probability_tests.txt").write_text(log_text, encoding="utf-8")
    em = probability_result["rk_em_boomerang"]
    keydiff_outputs = {
        "delta_keydiff_forward": em.get("delta_key_milp"),
        "nabla_keydiff_backward": em.get("nabla_key_milp"),
    }
    for name, entry in keydiff_outputs.items():
        if not entry:
            continue
        (json_dir / f"{name}.json").write_text(
            json.dumps(entry, indent=2),
            encoding="utf-8",
        )
        (output_dir / f"{name}.txt").write_text(
            format_keydiff_milp_log(name, entry),
            encoding="utf-8",
        )
    aligned = probability_result.get("aligned_key_schedule")
    if aligned:
        (json_dir / "aligned_key_schedule.json").write_text(
            json.dumps(aligned, indent=2),
            encoding="utf-8",
        )
        (output_dir / "aligned_key_schedule.txt").write_text(
            "\n".join(format_aligned_key_schedule_section(aligned)).lstrip() + "\n",
            encoding="utf-8",
        )
    return probability_result, log_text
