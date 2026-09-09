#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/rk_exact_verify.py

Single-file exact-value SMT verifier for Splight related-key differential trails.

Dependency:
    pip install z3-solver

Recommended project usage:
    from tools.rk_exact_verify import verify_fixed_differences

    result = verify_fixed_differences(
        rounds=7,
        round_offset=0,
        fixed_diffs={
            "dK":   "00000000000000002000000000020002",
            "dX0":  "0000000000000A00",
            "dRK0": "00000000",
            "dY0":  "00000000",
            ...
            "dX7":  "0200000000000000",
        },
        timeout_ms=300000,
        return_witness=True,
    )

Return format:
    {
        "status": "SAT" | "UNSAT" | "UNKNOWN",
        "rounds": int,
        "round_offset": int,
        "elapsed_seconds": float,
        "reason": str | None,
        "witness": dict | None,
    }

Semantics:
    Two REAL executions are modeled:

        (X_A_0, K_A) and (X_B_0, K_B)

    Every fixed differential is constrained as:

        dV = V_A XOR V_B

    No DDT transition is assumed independently. Therefore:

        SAT   => at least one real state/master-key pair realizes ALL
                 supplied differential constraints simultaneously.

        UNSAT => no real state/master-key pair realizes ALL supplied
                 differential constraints simultaneously.

        UNKNOWN => usually timeout/resource limit; DO NOT block the MILP
                   candidate based on UNKNOWN.

Round offset:
    round_offset=0:
        local round r uses absolute Splight round r and constants C0,C1,...

    round_offset=s:
        the master key is still KS_global_0, but the key schedule is first
        advanced through rounds 0..s-1. Local round r then uses the real
        round key generated at absolute round s+r.

    This makes the same verifier usable for upper and lower RKDiff segments.

Canonical fixed-difference names
--------------------------------
Master/global key:
    dK                  master-key difference == dKSG0
    dKSGg               global key-schedule-state difference KS_global_g
    dKSGINg             sparse global key-S-box input difference
    dKSGOUTg            sparse global key-S-box output difference
    dKSGCOREg           global key-core difference after key S-boxes + SHI^1

Local state boundaries, r=0..rounds:
    dXr                 64-bit state difference, X = L || R
    dXLr                left 32-bit state difference
    dXRr                right 32-bit state difference

Local key-state boundaries, r=0..rounds:
    dKSr                difference of KS_global_(round_offset+r)
    dROUNDKSr           alias of dKS(r+1), for r=0..rounds-1

Local round-internal differences, r=0..rounds-1:
    dRKr                round-key difference
    dYr                 first state S-box output difference
    dLINr / dLr         linear-layer output difference
    dAKr                second state S-box input difference
    dZr                 second state S-box output difference
    dFXORr              Z xor R difference
    dSHIr               SHI^2 output difference

Local key-schedule internals, r=0..rounds-1:
    dKSINr              sparse vector containing only key-S-box inputs
                        at nibble positions 3 and 7; other nibbles are 0
    dKSOUTr             sparse vector containing only key-S-box outputs
    dKCOREr             key-core output after key S-boxes + SHI^1

Important integration rule:
    rkboom.py / rkdiff.py should export the candidate DIFFERENCE VALUES into
    one canonical fixed_diffs dictionary. This module deliberately does not
    import Gurobi and does not add no-good constraints. If this verifier
    returns UNSAT, rkdiff.py should block the complete current concrete
    differential assignment (scheme A) and optimize again.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from z3 import BitVec, BitVecVal, If, Solver, sat, unknown


# =============================================================================
# Splight specification
# =============================================================================

SBOX = (
    0xA, 0xD, 0xC, 0xF,
    0x9, 0xE, 0x1, 0x0,
    0x7, 0x2, 0x5, 0x4,
    0x3, 0x6, 0xB, 0x8,
)

Pair = Tuple[Sequence, Sequence]


# =============================================================================
# Small helpers
# =============================================================================

def _make_nibbles(name: str, count: int):
    return [BitVec(f"{name}_{i}", 4) for i in range(count)]


def _xor_vec(a: Sequence, b: Sequence):
    if len(a) != len(b):
        raise ValueError("nibble-vector XOR length mismatch")
    return [x ^ y for x, y in zip(a, b)]


def _rotl(values: Sequence, shift: int):
    shift %= len(values)
    return list(values[shift:]) + list(values[:shift])


def _sbox4(x):
    out = BitVecVal(SBOX[15], 4)
    for i in range(14, -1, -1):
        out = If(
            x == BitVecVal(i, 4),
            BitVecVal(SBOX[i], 4),
            out,
        )
    return out


def _s_layer(values: Sequence):
    return [_sbox4(x) for x in values]


def _linear_layer(values: Sequence):
    """
    Splight 4-nibble linear map, independently on each 4-nibble group:

        y0 = x0 xor x2 xor x3
        y1 = x0
        y2 = x1 xor x2
        y3 = x0 xor x2
    """
    if len(values) % 4:
        raise ValueError("linear layer requires a multiple of four nibbles")

    out = []
    for base in range(0, len(values), 4):
        x0, x1, x2, x3 = values[base:base + 4]
        t = x0 ^ x2
        out.extend((t ^ x3, x0, x1 ^ x2, t))
    return out


def _round_constant(round_index: int):
    """
    Current project convention:
        C_r = r mod 32, represented as 8 nibbles.
    """
    value = round_index & 0x1F
    return [
        BitVecVal((value >> (4 * (7 - i))) & 0xF, 4)
        for i in range(8)
    ]


# =============================================================================
# Symbolic key schedule and encryption round
# =============================================================================

def _key_schedule_step(ks: Sequence, absolute_round: int):
    """
    ks = K0 || K1 || K2 || K3, each Ki is 8 nibbles.

    transformed K0:
        S-box at nibble positions 3 and 7
        then SHI^1 (left rotate by one nibble)

    RK_r = KCORE_r xor K1_r xor C_r
    KS_(r+1) = RK_r || K2_r || K3_r || K0_r
    """
    if len(ks) != 32:
        raise ValueError("key state must contain 32 nibbles")

    k0 = list(ks[0:8])
    k1 = list(ks[8:16])
    k2 = list(ks[16:24])
    k3 = list(ks[24:32])

    # Sparse key-S-box input/output vectors. Only positions 3 and 7 are real
    # key-S-box coordinates; other positions are intentionally zero.
    ksin = [BitVecVal(0, 4) for _ in range(8)]
    ksout = [BitVecVal(0, 4) for _ in range(8)]

    transformed = list(k0)
    for pos in (3, 7):
        ksin[pos] = k0[pos]
        ksout[pos] = _sbox4(k0[pos])
        transformed[pos] = ksout[pos]

    kcore = _rotl(transformed, 1)
    rk = _xor_vec(
        _xor_vec(kcore, k1),
        _round_constant(absolute_round),
    )
    next_ks = list(rk) + k2 + k3 + k0

    return next_ks, rk, {
        "k0": k0,
        "k1": k1,
        "k2": k2,
        "k3": k3,
        "ksin": ksin,
        "ksout": ksout,
        "kcore": kcore,
    }


def _encryption_round(state: Sequence, rk: Sequence):
    """
    X_r = XL_r || XR_r

        Y_r     = S(XL_r)
        LIN_r   = L(Y_r)
        AK_r    = LIN_r xor RK_r
        Z_r     = S(AK_r)
        FXOR_r  = Z_r xor XR_r
        SHI_r   = SHI^2(FXOR_r)
        X_(r+1) = SHI_r || XL_r
    """
    if len(state) != 16:
        raise ValueError("state must contain 16 nibbles")
    if len(rk) != 8:
        raise ValueError("round key must contain 8 nibbles")

    xl = list(state[:8])
    xr = list(state[8:])
    y = _s_layer(xl)
    lin = _linear_layer(y)
    ak = _xor_vec(lin, rk)
    z = _s_layer(ak)
    fxor = _xor_vec(z, xr)
    shi = _rotl(fxor, 2)
    next_state = shi + xl

    return next_state, {
        "xl": xl,
        "xr": xr,
        "y": y,
        "lin": lin,
        "ak": ak,
        "z": z,
        "fxor": fxor,
        "shi": shi,
    }


# =============================================================================
# Concrete ordinary-Python replay
# =============================================================================

def _c_round_constant(round_index: int):
    value = round_index & 0x1F
    return [
        (value >> (4 * (7 - i))) & 0xF
        for i in range(8)
    ]


def _c_linear(values):
    out = []
    for base in range(0, len(values), 4):
        x0, x1, x2, x3 = values[base:base + 4]
        t = x0 ^ x2
        out.extend([
            (t ^ x3) & 0xF,
            x0 & 0xF,
            (x1 ^ x2) & 0xF,
            t & 0xF,
        ])
    return out


def _c_key_schedule_step(ks, absolute_round: int):
    k0 = list(ks[0:8])
    k1 = list(ks[8:16])
    k2 = list(ks[16:24])
    k3 = list(ks[24:32])

    transformed = list(k0)
    transformed[3] = SBOX[transformed[3]]
    transformed[7] = SBOX[transformed[7]]
    kcore = _rotl(transformed, 1)

    c = _c_round_constant(absolute_round)
    rk = [
        (kcore[i] ^ k1[i] ^ c[i]) & 0xF
        for i in range(8)
    ]
    next_ks = rk + k2 + k3 + k0
    return next_ks, rk


def _c_encryption_round(state, rk):
    xl = list(state[:8])
    xr = list(state[8:])
    y = [SBOX[v] for v in xl]
    lin = _c_linear(y)
    ak = [(lin[i] ^ rk[i]) & 0xF for i in range(8)]
    z = [SBOX[v] for v in ak]
    fxor = [(z[i] ^ xr[i]) & 0xF for i in range(8)]
    shi = _rotl(fxor, 2)
    return shi + xl


# =============================================================================
# Model building and registry
# =============================================================================

@dataclass
class _Context:
    rounds: int
    round_offset: int
    local_states_a: list
    local_states_b: list
    global_keys_a: list
    global_keys_b: list
    global_records: list
    local_records: list


def _build_model(rounds: int, round_offset: int, timeout_ms: int):
    if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds <= 0:
        raise ValueError("rounds must be a positive integer")
    if (
        not isinstance(round_offset, int)
        or isinstance(round_offset, bool)
        or round_offset < 0
    ):
        raise ValueError("round_offset must be an integer >= 0")
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be > 0")

    solver = Solver()
    solver.set(timeout=timeout_ms)

    # Local data-state pair. For upper with offset 0 these are plaintexts.
    # For a lower/local segment they are simply the real boundary states at
    # the beginning of that segment.
    x_a0 = _make_nibbles("LOCAL_X_A_0", 16)
    x_b0 = _make_nibbles("LOCAL_X_B_0", 16)

    # Always start the key schedule from REAL master keys.
    master_a = _make_nibbles("MASTER_K_A", 32)
    master_b = _make_nibbles("MASTER_K_B", 32)

    # Build global key schedule from absolute round 0 through the last local
    # round. Local round r uses global round key at abs = offset + r.
    total_key_rounds = round_offset + rounds
    global_keys_a = [master_a]
    global_keys_b = [master_b]
    global_records = []

    for abs_r in range(total_key_rounds):
        next_a, rk_a, inner_a = _key_schedule_step(global_keys_a[-1], abs_r)
        next_b, rk_b, inner_b = _key_schedule_step(global_keys_b[-1], abs_r)
        global_records.append({
            "absolute_round": abs_r,
            "rk_a": rk_a,
            "rk_b": rk_b,
            "key_a": inner_a,
            "key_b": inner_b,
        })
        global_keys_a.append(next_a)
        global_keys_b.append(next_b)

    local_states_a = [x_a0]
    local_states_b = [x_b0]
    local_records = []

    for local_r in range(rounds):
        abs_r = round_offset + local_r
        grec = global_records[abs_r]
        next_x_a, data_a = _encryption_round(
            local_states_a[-1],
            grec["rk_a"],
        )
        next_x_b, data_b = _encryption_round(
            local_states_b[-1],
            grec["rk_b"],
        )
        local_records.append({
            "local_round": local_r,
            "absolute_round": abs_r,
            "rk_a": grec["rk_a"],
            "rk_b": grec["rk_b"],
            "key_a": grec["key_a"],
            "key_b": grec["key_b"],
            "data_a": data_a,
            "data_b": data_b,
        })
        local_states_a.append(next_x_a)
        local_states_b.append(next_x_b)

    ctx = _Context(
        rounds=rounds,
        round_offset=round_offset,
        local_states_a=local_states_a,
        local_states_b=local_states_b,
        global_keys_a=global_keys_a,
        global_keys_b=global_keys_b,
        global_records=global_records,
        local_records=local_records,
    )

    registry = _build_diff_registry(ctx)
    return solver, ctx, registry


def _build_diff_registry(ctx: _Context) -> Dict[str, Pair]:
    registry: Dict[str, Pair] = {}

    # -------------------------------------------------------------------------
    # Master/global key states
    # -------------------------------------------------------------------------
    registry["dK"] = (ctx.global_keys_a[0], ctx.global_keys_b[0])

    for g in range(len(ctx.global_keys_a)):
        registry[f"dKSG{g}"] = (
            ctx.global_keys_a[g],
            ctx.global_keys_b[g],
        )

    for g, rec in enumerate(ctx.global_records):
        registry[f"dKSGIN{g}"] = (
            rec["key_a"]["ksin"],
            rec["key_b"]["ksin"],
        )
        registry[f"dKSGOUT{g}"] = (
            rec["key_a"]["ksout"],
            rec["key_b"]["ksout"],
        )
        registry[f"dKSGCORE{g}"] = (
            rec["key_a"]["kcore"],
            rec["key_b"]["kcore"],
        )

    # -------------------------------------------------------------------------
    # Local state and local key-state boundaries
    # -------------------------------------------------------------------------
    for r in range(ctx.rounds + 1):
        xa = ctx.local_states_a[r]
        xb = ctx.local_states_b[r]
        registry[f"dX{r}"] = (xa, xb)
        registry[f"dXL{r}"] = (xa[:8], xb[:8])
        registry[f"dXR{r}"] = (xa[8:], xb[8:])

        g = ctx.round_offset + r
        registry[f"dKS{r}"] = (
            ctx.global_keys_a[g],
            ctx.global_keys_b[g],
        )

    # -------------------------------------------------------------------------
    # Local round internals
    # -------------------------------------------------------------------------
    for r in range(ctx.rounds):
        rec = ctx.local_records[r]
        registry[f"dRK{r}"] = (rec["rk_a"], rec["rk_b"])

        for short, key in (
            ("Y", "y"),
            ("LIN", "lin"),
            ("AK", "ak"),
            ("Z", "z"),
            ("FXOR", "fxor"),
            ("SHI", "shi"),
        ):
            registry[f"d{short}{r}"] = (
                rec["data_a"][key],
                rec["data_b"][key],
            )

        registry[f"dL{r}"] = registry[f"dLIN{r}"]

        registry[f"dKSIN{r}"] = (
            rec["key_a"]["ksin"],
            rec["key_b"]["ksin"],
        )
        registry[f"dKSOUT{r}"] = (
            rec["key_a"]["ksout"],
            rec["key_b"]["ksout"],
        )
        registry[f"dKCORE{r}"] = (
            rec["key_a"]["kcore"],
            rec["key_b"]["kcore"],
        )

        # README convention: round_ks_r is the updated key state used to
        # expose RK_r, namely KS_global_(round_offset+r+1).
        registry[f"dROUNDKS{r}"] = registry[f"dKS{r + 1}"]

    return registry


# =============================================================================
# Difference constraints
# =============================================================================

def _normalize_hex(value: Any, nibbles: int, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a hexadecimal string")

    value = (
        value.replace("0x", "")
        .replace("0X", "")
        .replace("_", "")
        .replace(" ", "")
        .upper()
    )

    if len(value) != nibbles:
        raise ValueError(
            f"{label}: expected {nibbles} hex digits, got {len(value)} ({value})"
        )
    if any(c not in "0123456789ABCDEF" for c in value):
        raise ValueError(f"{label}: invalid hexadecimal value {value}")
    return value


def _add_fixed_diff(solver: Solver, pair: Pair, value_hex: str, label: str):
    a, b = pair
    value_hex = _normalize_hex(value_hex, len(a), label)
    for x, y, c in zip(a, b, value_hex):
        solver.add((x ^ y) == BitVecVal(int(c, 16), 4))


def _apply_fixed_diffs(
    solver: Solver,
    registry: Mapping[str, Pair],
    fixed_diffs: Mapping[str, str],
):
    if not isinstance(fixed_diffs, Mapping):
        raise ValueError("fixed_diffs must be a mapping {name: hex_value}")

    for name, value in fixed_diffs.items():
        if name not in registry:
            valid = ", ".join(sorted(registry))
            raise ValueError(
                f"unknown fixed difference '{name}'. Valid names are: {valid}"
            )
        _add_fixed_diff(solver, registry[name], value, name)


def _eval_hex(model, values: Sequence) -> str:
    return "".join(
        f"{model.eval(x, model_completion=True).as_long() & 0xF:X}"
        for x in values
    )


def _eval_pair_diff_hex(model, pair: Pair) -> str:
    a, b = pair
    return "".join(
        f"{(model.eval(x, model_completion=True).as_long() ^ model.eval(y, model_completion=True).as_long()) & 0xF:X}"
        for x, y in zip(a, b)
    )


# =============================================================================
# Concrete replay
# =============================================================================

def _concrete_replay_or_raise(model, ctx: _Context):
    local_xa = [int(c, 16) for c in _eval_hex(model, ctx.local_states_a[0])]
    local_xb = [int(c, 16) for c in _eval_hex(model, ctx.local_states_b[0])]
    master_a = [int(c, 16) for c in _eval_hex(model, ctx.global_keys_a[0])]
    master_b = [int(c, 16) for c in _eval_hex(model, ctx.global_keys_b[0])]

    # Replay the complete key schedule from master key through the end of this
    # local segment.
    ka = master_a
    kb = master_b
    concrete_rks_a = []
    concrete_rks_b = []

    total_key_rounds = ctx.round_offset + ctx.rounds
    for abs_r in range(total_key_rounds):
        nka, rka = _c_key_schedule_step(ka, abs_r)
        nkb, rkb = _c_key_schedule_step(kb, abs_r)

        z3_nka = [int(c, 16) for c in _eval_hex(model, ctx.global_keys_a[abs_r + 1])]
        z3_nkb = [int(c, 16) for c in _eval_hex(model, ctx.global_keys_b[abs_r + 1])]

        if nka != z3_nka or nkb != z3_nkb:
            raise RuntimeError(
                f"concrete key-schedule replay mismatch at absolute round {abs_r}"
            )

        concrete_rks_a.append(rka)
        concrete_rks_b.append(rkb)
        ka, kb = nka, nkb

    # Replay the local data segment using the corresponding absolute round keys.
    xa = local_xa
    xb = local_xb
    for local_r in range(ctx.rounds):
        abs_r = ctx.round_offset + local_r
        nxa = _c_encryption_round(xa, concrete_rks_a[abs_r])
        nxb = _c_encryption_round(xb, concrete_rks_b[abs_r])

        z3_nxa = [int(c, 16) for c in _eval_hex(model, ctx.local_states_a[local_r + 1])]
        z3_nxb = [int(c, 16) for c in _eval_hex(model, ctx.local_states_b[local_r + 1])]

        if nxa != z3_nxa or nxb != z3_nxb:
            raise RuntimeError(
                f"concrete state replay mismatch at local round {local_r} "
                f"(absolute round {abs_r})"
            )

        xa, xb = nxa, nxb


def _build_witness(
    model,
    ctx: _Context,
    registry: Mapping[str, Pair],
    fixed_diffs: Mapping[str, str],
    return_all_diffs: bool,
):
    _concrete_replay_or_raise(model, ctx)

    witness = {
        "state_A_0": _eval_hex(model, ctx.local_states_a[0]),
        "state_B_0": _eval_hex(model, ctx.local_states_b[0]),
        "state_A_final": _eval_hex(model, ctx.local_states_a[-1]),
        "state_B_final": _eval_hex(model, ctx.local_states_b[-1]),
        "master_key_A": _eval_hex(model, ctx.global_keys_a[0]),
        "master_key_B": _eval_hex(model, ctx.global_keys_b[0]),
        "master_key_diff": _eval_pair_diff_hex(model, registry["dK"]),
        "fixed_diffs_actual": {
            name: _eval_pair_diff_hex(model, registry[name])
            for name in fixed_diffs
        },
        "concrete_replay": "PASS",
    }

    if return_all_diffs:
        witness["all_diffvariables"] = {
            name: _eval_pair_diff_hex(model, pair)
            for name, pair in sorted(registry.items())
        }

    return witness


# =============================================================================
# Public API
# =============================================================================

def list_diff_variables(rounds: int, round_offset: int = 0) -> Dict[str, int]:
    """
    Return all accepted fixed-difference names and their widths in hex digits.
    Useful while connecting RKDiff output fields to this verifier.
    """
    _, _, registry = _build_model(
        rounds=rounds,
        round_offset=round_offset,
        timeout_ms=1,
    )
    return {
        name: len(pair[0])
        for name, pair in sorted(registry.items())
    }


def verify_fixed_differences(
    *,
    rounds: int,
    fixed_diffs: Mapping[str, str],
    round_offset: int = 0,
    timeout_ms: int = 300_000,
    return_witness: bool = True,
    return_all_diffs: bool = False,
) -> Dict[str, Any]:
    """
    Generic exact-realizability oracle used by rkboom.py.

    Parameters
    ----------
    rounds:
        Number of LOCAL encryption rounds in the candidate trail.

    fixed_diffs:
        Canonical difference dictionary. Every supplied entry is enforced
        simultaneously on two real executions.

    round_offset:
        Absolute Splight round corresponding to local round 0.
        Upper E0 normally uses 0. A later lower/local segment can use its
        absolute starting round while still deriving all round keys from the
        real master key KS_global_0.

    timeout_ms:
        Z3 timeout for this candidate.

    return_witness:
        For SAT, return one real local-state/master-key witness and replay it.

    return_all_diffs:
        For SAT, additionally return every registered difference in the model.
        Normally False because this can be large.

    Returns
    -------
    dict with:
        status: SAT / UNSAT / UNKNOWN
        reason: None or Z3 reason for UNKNOWN
        witness: dict or None
        elapsed_seconds

    Integration rule
    ----------------
    if result["status"] == "SAT":
        accept candidate

    elif result["status"] == "UNSAT":
        add full-trail MILP no-good and optimize again

    elif result["status"] == "UNKNOWN":
        DO NOT block the candidate; record/stop/retry with a larger timeout
    """
    if fixed_diffs is None:
        raise ValueError("fixed_diffs must not be None")

    solver, ctx, registry = _build_model(
        rounds=rounds,
        round_offset=round_offset,
        timeout_ms=timeout_ms,
    )

    _apply_fixed_diffs(solver, registry, fixed_diffs)

    t0 = perf_counter()
    result = solver.check()
    elapsed = perf_counter() - t0

    base = {
        "rounds": rounds,
        "round_offset": round_offset,
        "elapsed_seconds": elapsed,
        "fixed_diff_count": len(fixed_diffs),
        "reason": None,
        "witness": None,
    }

    if result == sat:
        base["status"] = "SAT"
        if return_witness:
            base["witness"] = _build_witness(
                solver.model(),
                ctx,
                registry,
                fixed_diffs,
                return_all_diffs,
            )
        return base

    if result == unknown:
        base["status"] = "UNKNOWN"
        base["reason"] = solver.reason_unknown()
        return base

    base["status"] = "UNSAT"
    return base


def verify_trail(
    trail: Mapping[str, Any],
    *,
    timeout_ms: int = 300_000,
    return_witness: bool = True,
    return_all_diffs: bool = False,
) -> Dict[str, Any]:
    """
    Convenience wrapper if rkdiff.extract_solution() returns this standard form:

        trail = {
            "rounds": 7,
            "round_offset": 0,
            "fixed_diffs": {...},
            ... other MILP metadata are ignored ...
        }

    This is the recommended one-line call from rkboom.py.
    """
    if not isinstance(trail, Mapping):
        raise ValueError("trail must be a mapping")

    if "rounds" not in trail:
        raise ValueError("trail is missing 'rounds'")
    if "fixed_diffs" not in trail:
        raise ValueError("trail is missing 'fixed_diffs'")

    return verify_fixed_differences(
        rounds=int(trail["rounds"]),
        round_offset=int(trail.get("round_offset", 0)),
        fixed_diffs=trail["fixed_diffs"],
        timeout_ms=timeout_ms,
        return_witness=return_witness,
        return_all_diffs=return_all_diffs,
    )


__all__ = [
    "SBOX",
    "list_diff_variables",
    "verify_fixed_differences",
    "verify_trail",
]
