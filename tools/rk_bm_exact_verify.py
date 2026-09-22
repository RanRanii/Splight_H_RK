#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exact four-data boomerang verifier for Splight related-key trails.

This module is deliberately separate from :mod:`rk_exact_verify`.
The existing module verifies one related-key differential on two real
executions.  This module builds four real full-cipher executions and checks
whether they can form one complete related-key boomerang quartet.

The four branches use the conventional labels::

    00: (P00, K00)                 10: (P10, K10 = K00 xor DeltaK)
    01: (P01, K01 = K00 xor NablaK) 11: (P11, K11 = K00 xor DeltaK xor NablaK)

The model enforces both horizontal upper trails (00/10, 01/11), both vertical
lower trails (00/01, 10/11), and the input/output boomerang closure.  It also
accepts the saved truncated middle supports, when supplied by ``rkboom.py``.

SAT plus concrete replay PASS proves *existence* of a real four-key/data
quartet compatible with the encoded distinguisher.  It does not estimate, or
otherwise prove, the boomerang probability.

``rk_exact_verify.py`` remains unchanged.  This verifier imports its Splight
round/key-schedule primitives so the two exact models share one cipher
semantics implementation.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Mapping, MutableMapping, Optional, Sequence, Tuple

from z3 import BitVec, BitVecVal, Solver, sat, unknown

try:  # Package import used by tests and project code.
    from . import rk_exact_verify as _pair
except ImportError:  # Direct ``python tools/rk_bm_exact_verify.py`` execution.
    import rk_exact_verify as _pair


Pair = Tuple[Sequence, Sequence]
BranchName = str

_BRANCHES = ("00", "10", "01", "11")
_UPPER_PAIRS = (("D0", "00", "10"), ("D1", "01", "11"))
_LOWER_PAIRS = (("N0", "00", "01"), ("N1", "10", "11"))
_ROUND_SUPPORT_FAMILIES = ("y", "l", "rk", "ak", "z")


@dataclass
class _Branch:
    """All symbolic values of one full Splight execution."""

    name: BranchName
    master_key: list
    key_states: list
    key_records: list
    states: list
    round_records: list


@dataclass
class _BoomerangContext:
    r0: int
    rm: int
    r1: int
    total_rounds: int
    branches: Dict[BranchName, _Branch]


def _make_nibbles(name: str, count: int):
    return [BitVec(f"{name}_{index}", 4) for index in range(count)]


def _xor_hex(a: str, b: str) -> str:
    if len(a) != len(b):
        raise ValueError("hexadecimal XOR length mismatch")
    return "".join(f"{int(x, 16) ^ int(y, 16):X}" for x, y in zip(a, b))


def _support_of_hex(value: str) -> str:
    return "".join("0" if nibble == "0" else "1" for nibble in value.upper())


def _normalise_support(mask: Any, nibbles: int, label: str) -> Optional[str]:
    if mask in (None, "none"):
        return None
    if not isinstance(mask, str):
        raise ValueError(f"{label} must be a binary activity string")
    mask = mask.strip()
    if len(mask) != nibbles or any(bit not in "01" for bit in mask):
        raise ValueError(
            f"{label}: expected {nibbles} binary activity bits, got {mask!r}"
        )
    return mask


def _hex_of_values(model, values: Sequence) -> str:
    return _pair._eval_hex(model, values)


def _hex_of_pair_diff(model, pair: Pair) -> str:
    return _pair._eval_pair_diff_hex(model, pair)


def _pair_for(branch_a: _Branch, branch_b: _Branch, values_a, values_b) -> Pair:
    return values_a, values_b


def _build_context(r0: int, rm: int, r1: int) -> _BoomerangContext:
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (r0, rm, r1)):
        raise ValueError("r0, rm and r1 must be integers")
    if r0 <= 0 or r1 <= 0 or rm < 0:
        raise ValueError("r0 and r1 must be > 0 and rm must be >= 0")

    total_rounds = r0 + rm + r1
    branches: Dict[BranchName, _Branch] = {}

    for name in _BRANCHES:
        master = _make_nibbles(f"BM_K_{name}", 32)
        key_states = [master]
        key_records = []
        for absolute_round in range(total_rounds):
            next_key, round_key, inner = _pair._key_schedule_step(
                key_states[-1], absolute_round
            )
            key_records.append({
                "absolute_round": absolute_round,
                "rk": round_key,
                "key": inner,
            })
            key_states.append(next_key)

        states = [_make_nibbles(f"BM_X_{name}_0", 16)]
        round_records = []
        for absolute_round in range(total_rounds):
            next_state, data = _pair._encryption_round(
                states[-1], key_records[absolute_round]["rk"]
            )
            round_records.append({
                "absolute_round": absolute_round,
                "rk": key_records[absolute_round]["rk"],
                "key": key_records[absolute_round]["key"],
                "data": data,
            })
            states.append(next_state)

        branches[name] = _Branch(
            name=name,
            master_key=master,
            key_states=key_states,
            key_records=key_records,
            states=states,
            round_records=round_records,
        )

    return _BoomerangContext(
        r0=r0,
        rm=rm,
        r1=r1,
        total_rounds=total_rounds,
        branches=branches,
    )


def _add_difference_value(solver: Solver, pair: Pair, value: str, label: str):
    """Constrain the nibble-wise XOR of one pair to a hexadecimal value."""
    _pair._add_fixed_diff(solver, pair, value, label)


def _add_support_value(solver: Solver, pair: Pair, mask: Any, label: str) -> int:
    """Constrain a pair to an exact zero/non-zero nibble support pattern."""
    a, b = pair
    mask = _normalise_support(mask, len(a), label)
    if mask is None:
        return 0
    for lhs, rhs, active in zip(a, b, mask):
        difference = lhs ^ rhs
        if active == "0":
            solver.add(difference == BitVecVal(0, 4))
        else:
            solver.add(difference != BitVecVal(0, 4))
    return len(mask)


def _build_segment_registry(
    ctx: _BoomerangContext,
    branch_a_name: BranchName,
    branch_b_name: BranchName,
    *,
    rounds: int,
    round_offset: int,
) -> Dict[str, Pair]:
    """Build the same fixed-difference namespace as ``rk_exact_verify``.

    The local segment is embedded into four full-cipher executions.  Therefore
    a lower trail retains its original absolute offset while its data-state
    variables are selected from the corresponding full state trace.
    """
    if rounds <= 0 or round_offset < 0 or round_offset + rounds > ctx.total_rounds:
        raise ValueError("segment is outside the full boomerang cipher")

    branch_a = ctx.branches[branch_a_name]
    branch_b = ctx.branches[branch_b_name]
    registry: Dict[str, Pair] = {}

    registry["dK"] = (branch_a.master_key, branch_b.master_key)
    for absolute_round in range(ctx.total_rounds + 1):
        registry[f"dKSG{absolute_round}"] = (
            branch_a.key_states[absolute_round],
            branch_b.key_states[absolute_round],
        )
    for absolute_round in range(ctx.total_rounds):
        registry[f"dKSGIN{absolute_round}"] = (
            branch_a.key_records[absolute_round]["key"]["ksin"],
            branch_b.key_records[absolute_round]["key"]["ksin"],
        )
        registry[f"dKSGOUT{absolute_round}"] = (
            branch_a.key_records[absolute_round]["key"]["ksout"],
            branch_b.key_records[absolute_round]["key"]["ksout"],
        )
        registry[f"dKSGCORE{absolute_round}"] = (
            branch_a.key_records[absolute_round]["key"]["kcore"],
            branch_b.key_records[absolute_round]["key"]["kcore"],
        )

    for local_round in range(rounds + 1):
        absolute_round = round_offset + local_round
        state_a = branch_a.states[absolute_round]
        state_b = branch_b.states[absolute_round]
        registry[f"dX{local_round}"] = (state_a, state_b)
        registry[f"dXL{local_round}"] = (state_a[:8], state_b[:8])
        registry[f"dXR{local_round}"] = (state_a[8:], state_b[8:])
        registry[f"dKS{local_round}"] = (
            branch_a.key_states[absolute_round],
            branch_b.key_states[absolute_round],
        )

    for local_round in range(rounds):
        absolute_round = round_offset + local_round
        record_a = branch_a.round_records[absolute_round]
        record_b = branch_b.round_records[absolute_round]
        registry[f"dRK{local_round}"] = (record_a["rk"], record_b["rk"])
        for short, key in (
            ("Y", "y"),
            ("LIN", "lin"),
            ("AK", "ak"),
            ("Z", "z"),
            ("FXOR", "fxor"),
            ("SHI", "shi"),
        ):
            registry[f"d{short}{local_round}"] = (
                record_a["data"][key], record_b["data"][key]
            )
        registry[f"dL{local_round}"] = registry[f"dLIN{local_round}"]
        registry[f"dKSIN{local_round}"] = (
            record_a["key"]["ksin"], record_b["key"]["ksin"]
        )
        registry[f"dKSOUT{local_round}"] = (
            record_a["key"]["ksout"], record_b["key"]["ksout"]
        )
        registry[f"dKCORE{local_round}"] = (
            record_a["key"]["kcore"], record_b["key"]["kcore"]
        )
        registry[f"dROUNDKS{local_round}"] = registry[f"dKS{local_round + 1}"]

    return registry


def _apply_fixed_diffs(
    solver: Solver,
    registry: Mapping[str, Pair],
    fixed_diffs: Mapping[str, str],
    label: str,
) -> int:
    if not isinstance(fixed_diffs, Mapping) or not fixed_diffs:
        raise ValueError(f"{label} fixed_diffs must be a non-empty mapping")
    for name, value in fixed_diffs.items():
        if name not in registry:
            raise ValueError(f"{label}: unsupported fixed difference {name!r}")
        _add_difference_value(solver, registry[name], value, f"{label}.{name}")
    return len(fixed_diffs)


def _require_hex_diff(fixed_diffs: Mapping[str, str], name: str, nibbles: int, label: str) -> str:
    if name not in fixed_diffs:
        raise ValueError(f"{label} is missing required fixed difference {name}")
    return _pair._normalize_hex(fixed_diffs[name], nibbles, f"{label}.{name}")


def _add_key_quartet_constraints(
    solver: Solver,
    ctx: _BoomerangContext,
    upper_fixed_diffs: Mapping[str, str],
    lower_fixed_diffs: Mapping[str, str],
):
    delta_key = _require_hex_diff(upper_fixed_diffs, "dK", 32, "upper")
    nabla_key = _require_hex_diff(lower_fixed_diffs, "dK", 32, "lower")
    keys = {name: ctx.branches[name].master_key for name in _BRANCHES}

    _add_difference_value(solver, (keys["00"], keys["10"]), delta_key, "DeltaK")
    _add_difference_value(solver, (keys["01"], keys["11"]), delta_key, "DeltaK shifted")
    _add_difference_value(solver, (keys["00"], keys["01"]), nabla_key, "NablaK")
    _add_difference_value(solver, (keys["10"], keys["11"]), nabla_key, "NablaK shifted")
    return delta_key, nabla_key


def _add_boomerang_boundary_constraints(
    solver: Solver,
    ctx: _BoomerangContext,
    upper_fixed_diffs: Mapping[str, str],
    lower_fixed_diffs: Mapping[str, str],
):
    delta_input = _require_hex_diff(upper_fixed_diffs, "dX0", 16, "upper")
    nabla_output = _require_hex_diff(
        lower_fixed_diffs, f"dX{ctx.r1}", 16, "lower"
    )
    states = {name: ctx.branches[name].states for name in _BRANCHES}

    _add_difference_value(solver, (states["00"][0], states["10"][0]), delta_input, "Delta input")
    _add_difference_value(solver, (states["01"][0], states["11"][0]), delta_input, "Delta input closure")
    _add_difference_value(
        solver,
        (states["00"][-1], states["01"][-1]),
        nabla_output,
        "Nabla output",
    )
    _add_difference_value(
        solver,
        (states["10"][-1], states["11"][-1]),
        nabla_output,
        "Nabla output closure",
    )
    return delta_input, nabla_output


def _pair_values_for_support(
    ctx: _BoomerangContext,
    branch_a_name: BranchName,
    branch_b_name: BranchName,
    family: str,
    absolute_round: int,
) -> Pair:
    branch_a = ctx.branches[branch_a_name]
    branch_b = ctx.branches[branch_b_name]
    if family == "x":
        return branch_a.states[absolute_round], branch_b.states[absolute_round]
    if family == "ks_global":
        return branch_a.key_states[absolute_round], branch_b.key_states[absolute_round]
    if family == "kc_global":
        if absolute_round >= ctx.total_rounds:
            raise ValueError("key-core support requested after the final key state")
        return (
            branch_a.key_records[absolute_round]["key"]["kcore"],
            branch_b.key_records[absolute_round]["key"]["kcore"],
        )
    if absolute_round >= ctx.total_rounds:
        raise ValueError(f"{family} support requested after the final cipher round")
    key_map = {"y": "y", "l": "lin", "rk": "rk", "ak": "ak", "z": "z"}
    if family not in key_map:
        raise ValueError(f"unknown truncated support family {family}")
    if family == "rk":
        return branch_a.round_records[absolute_round]["rk"], branch_b.round_records[absolute_round]["rk"]
    return (
        branch_a.round_records[absolute_round]["data"][key_map[family]],
        branch_b.round_records[absolute_round]["data"][key_map[family]],
    )


def _apply_truncated_side_support(
    solver: Solver,
    ctx: _BoomerangContext,
    trail: Mapping[str, Any],
    *,
    side: str,
) -> int:
    """Apply all saved zero/non-zero supports of one truncated side.

    ``upper_trail`` starts at absolute round zero.  ``lower_trail`` starts at
    absolute round ``r0`` (the start of the middle), as in ``rktruncboom``.
    """
    if side == "upper":
        total_side_rounds = ctx.r0 + ctx.rm
        start_absolute_round = 0
        pairs = _UPPER_PAIRS
    elif side == "lower":
        total_side_rounds = ctx.rm + ctx.r1
        start_absolute_round = ctx.r0
        pairs = _LOWER_PAIRS
    else:
        raise ValueError(f"unknown truncated side {side!r}")

    if not isinstance(trail, Mapping):
        raise ValueError(f"truncated {side} trail must be a mapping")

    constraint_count = 0
    for local_round in range(total_side_rounds + 1):
        key = f"x_{local_round}"
        if key not in trail:
            raise ValueError(f"truncated {side} trail is missing {key}")
        absolute_round = start_absolute_round + local_round
        for label, branch_a, branch_b in pairs:
            constraint_count += _add_support_value(
                solver,
                _pair_values_for_support(ctx, branch_a, branch_b, "x", absolute_round),
                trail[key],
                f"{label}.{key}",
            )

    for local_round in range(total_side_rounds):
        absolute_round = start_absolute_round + local_round
        for family in _ROUND_SUPPORT_FAMILIES:
            key = f"{family}_{local_round}"
            if key not in trail:
                raise ValueError(f"truncated {side} trail is missing {key}")
            for label, branch_a, branch_b in pairs:
                constraint_count += _add_support_value(
                    solver,
                    _pair_values_for_support(
                        ctx, branch_a, branch_b, family, absolute_round
                    ),
                    trail[key],
                    f"{label}.{key}",
                )

    max_global_key_round = start_absolute_round + total_side_rounds
    for absolute_round in range(max_global_key_round + 1):
        key = f"ks_global_{absolute_round}"
        if key not in trail:
            raise ValueError(f"truncated {side} trail is missing {key}")
        for label, branch_a, branch_b in pairs:
            constraint_count += _add_support_value(
                solver,
                _pair_values_for_support(ctx, branch_a, branch_b, "ks_global", absolute_round),
                trail[key],
                f"{label}.{key}",
            )
        if absolute_round < max_global_key_round:
            core_key = f"kc_global_{absolute_round}"
            if core_key not in trail:
                raise ValueError(f"truncated {side} trail is missing {core_key}")
            for label, branch_a, branch_b in pairs:
                constraint_count += _add_support_value(
                    solver,
                    _pair_values_for_support(ctx, branch_a, branch_b, "kc_global", absolute_round),
                    trail[core_key],
                    f"{label}.{core_key}",
                )
    return constraint_count


def _validate_common_middle_support(
    truncated_path: Mapping[str, Any],
    *,
    r0: int,
    rm: int,
):
    """Check that ``middle_part`` matches the two saved truncated trails."""
    upper = truncated_path.get("upper_trail")
    lower = truncated_path.get("lower_trail")
    middle = truncated_path.get("middle_part")
    if not all(isinstance(value, Mapping) for value in (upper, lower, middle)):
        raise ValueError("truncated path must contain upper_trail, lower_trail and middle_part")

    for middle_round in range(rm):
        upper_state = _normalise_support(
            upper.get(f"x_{r0 + middle_round}"), 16, f"upper.x_{r0 + middle_round}"
        )
        lower_state = _normalise_support(
            lower.get(f"x_{middle_round}"), 16, f"lower.x_{middle_round}"
        )
        upper_ak = _normalise_support(
            upper.get(f"ak_{r0 + middle_round}"), 8, f"upper.ak_{r0 + middle_round}"
        )
        lower_ak = _normalise_support(
            lower.get(f"ak_{middle_round}"), 8, f"lower.ak_{middle_round}"
        )
        actual_state = _normalise_support(
            middle.get(f"s_{middle_round}"), 16, f"middle.s_{middle_round}"
        )
        expected_state = "".join(
            "1" if left == "1" and right == "1" else "0"
            for left, right in zip(upper_state[:8] + upper_ak, lower_state[:8] + lower_ak)
        )
        if actual_state != expected_state:
            raise ValueError(
                f"middle.s_{middle_round} disagrees with the saved upper/lower supports "
                f"({actual_state} != {expected_state})"
            )

        global_round = r0 + middle_round
        upper_key = _normalise_support(
            upper.get(f"ks_global_{global_round}"), 32, f"upper.ks_global_{global_round}"
        )
        lower_key = _normalise_support(
            lower.get(f"ks_global_{global_round}"), 32, f"lower.ks_global_{global_round}"
        )
        actual_key = _normalise_support(
            middle.get(f"ks_{middle_round}"), 2, f"middle.ks_{middle_round}"
        )
        expected_key = "".join(
            "1" if upper_key[position] == "1" and lower_key[position] == "1" else "0"
            for position in (3, 7)
        )
        if actual_key != expected_key:
            raise ValueError(
                f"middle.ks_{middle_round} disagrees with the saved upper/lower supports "
                f"({actual_key} != {expected_key})"
            )


def _replay_branch_or_raise(model, branch: _Branch, total_rounds: int):
    key = [int(value, 16) for value in _hex_of_values(model, branch.master_key)]
    round_keys = []
    for absolute_round in range(total_rounds):
        next_key, round_key = _pair._c_key_schedule_step(key, absolute_round)
        symbolic_key = [
            int(value, 16)
            for value in _hex_of_values(model, branch.key_states[absolute_round + 1])
        ]
        if next_key != symbolic_key:
            raise RuntimeError(
                f"{branch.name}: concrete key-schedule mismatch at round {absolute_round}"
            )
        round_keys.append(round_key)
        key = next_key

    state = [int(value, 16) for value in _hex_of_values(model, branch.states[0])]
    for absolute_round, round_key in enumerate(round_keys):
        next_state = _pair._c_encryption_round(state, round_key)
        symbolic_state = [
            int(value, 16)
            for value in _hex_of_values(model, branch.states[absolute_round + 1])
        ]
        if next_state != symbolic_state:
            raise RuntimeError(
                f"{branch.name}: concrete encryption mismatch at round {absolute_round}"
            )
        state = next_state


def _assert_fixed_diffs_or_raise(model, registry: Mapping[str, Pair], fixed: Mapping[str, str], label: str):
    for name, expected in fixed.items():
        actual = _hex_of_pair_diff(model, registry[name])
        expected = _pair._normalize_hex(expected, len(registry[name][0]), f"{label}.{name}")
        if actual != expected:
            raise RuntimeError(
                f"{label}.{name}: replay difference mismatch ({actual} != {expected})"
            )


def _assert_support_or_raise(
    model,
    ctx: _BoomerangContext,
    truncated_path: Mapping[str, Any],
):
    for side, trail, total_side_rounds, start_absolute_round, pairs in (
        ("upper", truncated_path["upper_trail"], ctx.r0 + ctx.rm, 0, _UPPER_PAIRS),
        ("lower", truncated_path["lower_trail"], ctx.rm + ctx.r1, ctx.r0, _LOWER_PAIRS),
    ):
        for local_round in range(total_side_rounds + 1):
            for label, branch_a, branch_b in pairs:
                pair = _pair_values_for_support(
                    ctx, branch_a, branch_b, "x", start_absolute_round + local_round
                )
                actual = _support_of_hex(_hex_of_pair_diff(model, pair))
                expected = _normalise_support(trail[f"x_{local_round}"], 16, f"{side}.x_{local_round}")
                if actual != expected:
                    raise RuntimeError(f"{label}.{side}.x_{local_round}: support replay mismatch")
        for local_round in range(total_side_rounds):
            absolute_round = start_absolute_round + local_round
            for family in _ROUND_SUPPORT_FAMILIES:
                expected = _normalise_support(
                    trail[f"{family}_{local_round}"], 8, f"{side}.{family}_{local_round}"
                )
                for label, branch_a, branch_b in pairs:
                    pair = _pair_values_for_support(ctx, branch_a, branch_b, family, absolute_round)
                    if _support_of_hex(_hex_of_pair_diff(model, pair)) != expected:
                        raise RuntimeError(
                            f"{label}.{side}.{family}_{local_round}: support replay mismatch"
                        )


def _build_witness(
    model,
    ctx: _BoomerangContext,
    registries: Mapping[str, Mapping[str, Pair]],
    upper_fixed_diffs: Mapping[str, str],
    lower_fixed_diffs: Mapping[str, str],
    truncated_path: Optional[Mapping[str, Any]],
    return_all_diffs: bool,
) -> Dict[str, Any]:
    for branch in ctx.branches.values():
        _replay_branch_or_raise(model, branch, ctx.total_rounds)

    _assert_fixed_diffs_or_raise(model, registries["D0"], upper_fixed_diffs, "D0")
    _assert_fixed_diffs_or_raise(model, registries["D1"], upper_fixed_diffs, "D1")
    _assert_fixed_diffs_or_raise(model, registries["N0"], lower_fixed_diffs, "N0")
    _assert_fixed_diffs_or_raise(model, registries["N1"], lower_fixed_diffs, "N1")
    if truncated_path is not None:
        _assert_support_or_raise(model, ctx, truncated_path)

    keys = {name: _hex_of_values(model, ctx.branches[name].master_key) for name in _BRANCHES}
    plaintexts = {name: _hex_of_values(model, ctx.branches[name].states[0]) for name in _BRANCHES}
    ciphertexts = {name: _hex_of_values(model, ctx.branches[name].states[-1]) for name in _BRANCHES}
    relationships = {
        "delta_key": _xor_hex(keys["00"], keys["10"]),
        "nabla_key": _xor_hex(keys["00"], keys["01"]),
        "delta_key_shifted": _xor_hex(keys["01"], keys["11"]),
        "nabla_key_shifted": _xor_hex(keys["10"], keys["11"]),
        "delta_input": _xor_hex(plaintexts["00"], plaintexts["10"]),
        "delta_input_closure": _xor_hex(plaintexts["01"], plaintexts["11"]),
        "nabla_output": _xor_hex(ciphertexts["00"], ciphertexts["01"]),
        "nabla_output_closure": _xor_hex(ciphertexts["10"], ciphertexts["11"]),
    }
    witness: Dict[str, Any] = {
        "master_keys": keys,
        "plaintexts": plaintexts,
        "ciphertexts": ciphertexts,
        "relationships": relationships,
        "state_traces": {
            name: [_hex_of_values(model, branch.states[r]) for r in range(ctx.total_rounds + 1)]
            for name, branch in ctx.branches.items()
        },
        "key_state_traces": {
            name: [_hex_of_values(model, branch.key_states[r]) for r in range(ctx.total_rounds + 1)]
            for name, branch in ctx.branches.items()
        },
        "fixed_diffs_actual": {
            label: {
                name: _hex_of_pair_diff(model, pair)
                for name, pair in registry.items()
                if name in (upper_fixed_diffs if label.startswith("D") else lower_fixed_diffs)
            }
            for label, registry in registries.items()
        },
        "middle_support": "PASS" if truncated_path is not None else "NOT_REQUESTED",
        "concrete_replay": "PASS",
    }
    if return_all_diffs:
        witness["all_diffvariables"] = {
            label: {name: _hex_of_pair_diff(model, pair) for name, pair in sorted(registry.items())}
            for label, registry in registries.items()
        }
    return witness


def verify_boomerang(
    *,
    r0: int,
    rm: int,
    r1: int,
    upper_fixed_diffs: Mapping[str, str],
    lower_fixed_diffs: Mapping[str, str],
    truncated_path: Optional[Mapping[str, Any]] = None,
    timeout_ms: int = 600_000,
    return_witness: bool = True,
    return_all_diffs: bool = False,
) -> Dict[str, Any]:
    """Verify one full related-key boomerang as a four-execution SMT model.

    ``upper_fixed_diffs`` and ``lower_fixed_diffs`` use the unchanged
    ``rk_exact_verify`` fixed-difference namespace.  The upper trail is
    applied to both pairs ``00/10`` and ``01/11``; the lower trail is applied
    to both pairs ``00/01`` and ``10/11``.
    """
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be > 0")

    ctx = _build_context(r0, rm, r1)
    solver = Solver()
    solver.set(timeout=int(timeout_ms))

    delta_key, nabla_key = _add_key_quartet_constraints(
        solver, ctx, upper_fixed_diffs, lower_fixed_diffs
    )
    delta_input, nabla_output = _add_boomerang_boundary_constraints(
        solver, ctx, upper_fixed_diffs, lower_fixed_diffs
    )

    registries = {
        label: _build_segment_registry(
            ctx, branch_a, branch_b, rounds=ctx.r0, round_offset=0
        )
        for label, branch_a, branch_b in _UPPER_PAIRS
    }
    registries.update({
        label: _build_segment_registry(
            ctx,
            branch_a,
            branch_b,
            rounds=ctx.r1,
            round_offset=ctx.r0 + ctx.rm,
        )
        for label, branch_a, branch_b in _LOWER_PAIRS
    })

    upper_fixed_count = sum(
        _apply_fixed_diffs(solver, registries[label], upper_fixed_diffs, label)
        for label, _, _ in _UPPER_PAIRS
    )
    lower_fixed_count = sum(
        _apply_fixed_diffs(solver, registries[label], lower_fixed_diffs, label)
        for label, _, _ in _LOWER_PAIRS
    )

    support_constraint_count = 0
    if truncated_path is not None:
        if not isinstance(truncated_path, Mapping):
            raise ValueError("truncated_path must be a mapping or None")
        _validate_common_middle_support(truncated_path, r0=ctx.r0, rm=ctx.rm)
        support_constraint_count += _apply_truncated_side_support(
            solver, ctx, truncated_path["upper_trail"], side="upper"
        )
        support_constraint_count += _apply_truncated_side_support(
            solver, ctx, truncated_path["lower_trail"], side="lower"
        )

    started = perf_counter()
    result = solver.check()
    elapsed = perf_counter() - started
    base: Dict[str, Any] = {
        "status": None,
        "reason": None,
        "r0": ctx.r0,
        "rm": ctx.rm,
        "r1": ctx.r1,
        "total_rounds": ctx.total_rounds,
        "elapsed_seconds": elapsed,
        "upper_fixed_diff_count_per_pair": len(upper_fixed_diffs),
        "lower_fixed_diff_count_per_pair": len(lower_fixed_diffs),
        "fixed_constraint_count": upper_fixed_count + lower_fixed_count,
        "support_constraint_count": support_constraint_count,
        "constraint_profile": {
            "four_key_schedule": True,
            "upper_exact_two_pairs": True,
            "lower_exact_two_pairs": True,
            "boomerang_closure": True,
            "middle_support": truncated_path is not None,
        },
        "expected_relationships": {
            "delta_key": delta_key,
            "nabla_key": nabla_key,
            "delta_input": delta_input,
            "nabla_output": nabla_output,
        },
        "witness": None,
    }
    if result == sat:
        base["status"] = "SAT"
        if return_witness:
            base["witness"] = _build_witness(
                solver.model(),
                ctx,
                registries,
                upper_fixed_diffs,
                lower_fixed_diffs,
                truncated_path,
                return_all_diffs,
            )
        return base
    if result == unknown:
        base["status"] = "UNKNOWN"
        base["reason"] = solver.reason_unknown()
        return base
    base["status"] = "UNSAT"
    return base


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_case_parameters(case_dir: Path) -> Mapping[str, Any]:
    json_dir = case_dir / ".json"
    if json_dir.is_dir():
        for path in sorted(json_dir.glob("*.json")):
            payload = _read_json(path)
            parameters = payload.get("parameters")
            if isinstance(parameters, Mapping) and all(key in parameters for key in ("r0", "rm", "r1")):
                return parameters

    match = re.fullmatch(r"(\d+)-(\d+)-(\d+)(?:_[^\\/]+)?", case_dir.name)
    if match:
        return {"r0": int(match.group(1)), "rm": int(match.group(2)), "r1": int(match.group(3))}
    raise ValueError(
        f"cannot determine r0/rm/r1 for {case_dir}; expected .json result parameters"
    )


def load_boomerang_input_from_result_dir(
    result_dir: str | Path,
    *,
    truncated_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Load the accepted outer trails and truncated path for one result case."""
    case_dir = Path(result_dir).resolve()
    if not case_dir.is_dir():
        raise ValueError(f"result directory does not exist: {case_dir}")
    parameters = _load_case_parameters(case_dir)
    r0, rm, r1 = (int(parameters[key]) for key in ("r0", "rm", "r1"))

    exact_summary_path = case_dir / "exact_summary.json"
    if truncated_id is None:
        summary = _read_json(exact_summary_path)
        upper_id = (summary.get("upper_summary") or {}).get("accepted_truncated_id")
        lower_id = (summary.get("lower_summary") or {}).get("accepted_truncated_id")
        if upper_id is None or lower_id is None or int(upper_id) != int(lower_id):
            raise ValueError("exact_summary.json has no common accepted truncated_id")
        truncated_id = int(upper_id)
    elif int(truncated_id) <= 0:
        raise ValueError("truncated_id must be positive")
    else:
        truncated_id = int(truncated_id)

    path_dir = case_dir / f"truncated_{truncated_id:04d}"
    truncated_path = _read_json(path_dir / "truncated_path.json")
    upper_accepted = _read_json(path_dir / "upper" / "accepted.json")
    lower_accepted = _read_json(path_dir / "lower" / "accepted.json")

    for expected_side, accepted in (("upper", upper_accepted), ("lower", lower_accepted)):
        if accepted.get("status") != "SAT" or accepted.get("concrete_replay") != "PASS":
            raise ValueError(f"{expected_side} accepted result is not SAT with replay PASS")
        if int(accepted.get("truncated_id", -1)) != truncated_id:
            raise ValueError(f"{expected_side} accepted result has a mismatching truncated_id")

    upper_characteristic = upper_accepted.get("characteristic")
    lower_characteristic = lower_accepted.get("characteristic")
    if not isinstance(upper_characteristic, Mapping) or not isinstance(lower_characteristic, Mapping):
        raise ValueError("accepted result is missing its characteristic")
    if int(upper_characteristic.get("nrounds", -1)) != r0:
        raise ValueError("accepted upper characteristic does not cover r0 rounds")
    if int(lower_characteristic.get("nrounds", -1)) != r1:
        raise ValueError("accepted lower characteristic does not cover r1 rounds")
    if int(upper_characteristic.get("round_offset", -1)) != 0:
        raise ValueError("accepted upper characteristic must have round_offset 0")
    if int(lower_characteristic.get("round_offset", -1)) != r0 + rm:
        raise ValueError("accepted lower characteristic has an invalid round_offset")

    upper_witness = upper_accepted.get("witness")
    lower_witness = lower_accepted.get("witness")
    if not isinstance(upper_witness, Mapping) or not isinstance(lower_witness, Mapping):
        raise ValueError("accepted result is missing an exact-verifier witness")
    upper_fixed = upper_witness.get("fixed_diffs_actual")
    lower_fixed = lower_witness.get("fixed_diffs_actual")
    if not isinstance(upper_fixed, Mapping) or not isinstance(lower_fixed, Mapping):
        raise ValueError("accepted witness is missing fixed_diffs_actual")

    return {
        "result_dir": str(case_dir),
        "parameters": {"r0": r0, "rm": rm, "r1": r1},
        "truncated_id": truncated_id,
        "truncated_path": truncated_path,
        "upper_fixed_diffs": dict(upper_fixed),
        "lower_fixed_diffs": dict(lower_fixed),
        "source": {
            "upper_accepted": str(path_dir / "upper" / "accepted.json"),
            "lower_accepted": str(path_dir / "lower" / "accepted.json"),
            "truncated_path": str(path_dir / "truncated_path.json"),
        },
    }


def _witness_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# Full Boomerang Exact Verification",
        "",
        f"- SMT status: `{result['status']}`",
        f"- Concrete replay: `{(result.get('witness') or {}).get('concrete_replay', 'NOT_RUN')}`",
        f"- Rounds: `{result['r0']}-{result['rm']}-{result['r1']}`",
        f"- Elapsed seconds: `{float(result['elapsed_seconds']):.6f}`",
        "- Meaning: SAT plus replay PASS proves existence of a compatible real four-key/data quartet; it does not prove probability.",
    ]
    witness = result.get("witness")
    if not isinstance(witness, Mapping):
        return "\n".join(lines) + "\n"
    lines.extend([
        "",
        "## Four keys and data values",
        "",
        "| Branch | Master key | Plaintext | Ciphertext |",
        "|---|---|---|---|",
    ])
    for branch in _BRANCHES:
        lines.append(
            f"| `{branch}` | `{witness['master_keys'][branch]}` | "
            f"`{witness['plaintexts'][branch]}` | `{witness['ciphertexts'][branch]}` |"
        )
    lines.extend(["", "## Closure differences", ""])
    for name, value in witness["relationships"].items():
        lines.append(f"- `{name}`: `{value}`")
    return "\n".join(lines) + "\n"


def write_verification_artifacts(result: Mapping[str, Any], output_dir: str | Path) -> Dict[str, str]:
    """Write a compact summary plus the full SAT witness, if one exists."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    summary = {key: value for key, value in result.items() if key != "witness"}
    summary["concrete_replay"] = (result.get("witness") or {}).get("concrete_replay")
    summary_path = directory / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    witness_path = directory / "witness.json"
    if result.get("witness") is not None:
        witness_path.write_text(
            json.dumps(result["witness"], indent=2) + "\n", encoding="utf-8"
        )
    elif witness_path.exists():
        witness_path.unlink()

    markdown_path = directory / "witness.md"
    markdown_path.write_text(_witness_markdown(result), encoding="utf-8")
    terminal_path = directory / "terminal_print.txt"
    terminal_path.write_text(
        "\n".join([
            f"Full boomerang exact verification: {result['status']}",
            f"Concrete replay: {(result.get('witness') or {}).get('concrete_replay', 'NOT_RUN')}",
            f"Elapsed seconds: {float(result['elapsed_seconds']):.6f}",
            "SAT + PASS proves realizability of one real four-key/data quartet, not probability.",
            "",
        ]),
        encoding="utf-8",
    )
    return {
        "summary_json": str(summary_path),
        "witness_json": str(witness_path) if witness_path.exists() else "",
        "witness_markdown": str(markdown_path),
        "terminal_print": str(terminal_path),
    }


def verify_boomerang_result_dir(
    result_dir: str | Path,
    *,
    truncated_id: Optional[int] = None,
    timeout_ms: int = 600_000,
    output_dir: Optional[str | Path] = None,
    return_all_diffs: bool = False,
) -> Dict[str, Any]:
    """Load one final result folder, verify it, and write verification files."""
    loaded = load_boomerang_input_from_result_dir(result_dir, truncated_id=truncated_id)
    parameters = loaded["parameters"]
    result = verify_boomerang(
        r0=parameters["r0"],
        rm=parameters["rm"],
        r1=parameters["r1"],
        upper_fixed_diffs=loaded["upper_fixed_diffs"],
        lower_fixed_diffs=loaded["lower_fixed_diffs"],
        truncated_path=loaded["truncated_path"],
        timeout_ms=timeout_ms,
        return_witness=True,
        return_all_diffs=return_all_diffs,
    )
    result["truncated_id"] = loaded["truncated_id"]
    result["source"] = loaded["source"]
    target_dir = Path(output_dir) if output_dir is not None else Path(loaded["result_dir"]) / "bm_exact_verify"
    result["artifacts"] = write_verification_artifacts(result, target_dir)
    return result


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a full Splight related-key boomerang with four real executions."
    )
    parser.add_argument("--result-dir", required=True, help="results/{r0}-{rm}-{r1}_{weights} directory")
    parser.add_argument("--truncated-id", type=int, default=None, help="accepted truncated path ID")
    parser.add_argument("--timeout-ms", type=int, default=600_000, help="Z3 timeout in milliseconds")
    parser.add_argument("--output-dir", default=None, help="default: <result-dir>/bm_exact_verify")
    parser.add_argument("--return-all-diffs", action="store_true", help="include every registered difference in witness.json")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    try:
        result = verify_boomerang_result_dir(
            args.result_dir,
            truncated_id=args.truncated_id,
            timeout_ms=args.timeout_ms,
            output_dir=args.output_dir,
            return_all_diffs=args.return_all_diffs,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Full boomerang exact verification failed: {type(exc).__name__}: {exc}")
        return 2
    print(f"Full boomerang exact verification: {result['status']}")
    print(f"Concrete replay: {(result.get('witness') or {}).get('concrete_replay', 'NOT_RUN')}")
    print(f"Elapsed seconds: {float(result['elapsed_seconds']):.6f}")
    print(f"Results saved in: {Path(result['artifacts']['summary_json']).parent}")
    return 0


__all__ = [
    "load_boomerang_input_from_result_dir",
    "verify_boomerang",
    "verify_boomerang_result_dir",
    "write_verification_artifacts",
]


if __name__ == "__main__":
    raise SystemExit(main())
