"""Bit-level MILP for Splight related-key key-schedule differences."""

import os
import re
import time

try:
    from gurobipy import GRB, Model, quicksum
except Exception:  # pragma: no cover
    GRB = None
    Model = None
    quicksum = None

from splight.splight_spec import nibble_to_bits


TMP_DIR = os.path.join("tmp", "keydiff")
KEY_HEX_LEN = 32


class KeyDiff:
    sbox_inequalities = [
        "- a0 - 2*a1 - a2 - a3 + b1 + b2 + pr0 + 3*pr2 >= 0",
        "- a0 - 3*a1 - a2 - a3 - b0 - b1 - b2 + 2*pr0 + 6*pr2 >= 0",
        "- a0 + a1 - a2 - a3 - b0 - pr0 + 4*pr2 >= 0",
        "- a0 - a1 + a3 - 3*b0 - 2*b1 + b2 - b3 + 3*pr0 + 4*pr2 >= 0",
        "- a0 - a1 + a2 - 3*b0 - b1 - b3 + 2*pr0 + 4*pr2 >= 0",
        "a0 - a1 - a2 - a3 - 2*b0 - b1 + b2 - b3 + 3*pr0 + 3*pr2 >= 0",
        "a1 + b3 - pr0 >= 0",
        "a0 - a1 - a3 - 2*b0 + b1 - b2 - b3 + 2*pr0 + 3*pr2 >= 0",
        "- a0 - a1 - 2*a2 + a3 - 2*b0 + b1 - b2 - 2*b3 + 4*pr0 + 4*pr2 >= 0",
        "- 3*a1 - a2 - b0 - b1 - b2 + b3 + 2*pr0 + 4*pr2 >= 0",
        "a1 - a3 + b0 + b3 >= 0",
        "- a0 + a2 + b0 + b1 >= 0",
        "a0 - a1 + a3 - 2*b0 - b1 + b2 - 2*b3 + 4*pr0 + 2*pr2 >= 0",
        "3*a0 - 6*a1 - a2 - 3*a3 - b0 - 3*b1 - 7*b2 + b3 + 8*pr0 + 12*pr2 >= 0",
        "a1 + 2*a3 + 2*b0 - b2 - b3 - pr0 + pr2 >= 0",
        "a0 - a2 + a3 - b0 - b1 - b2 - pr0 + 4*pr2 >= 0",
        "2*a0 + 2*a1 + a2 + a3 - pr0 - pr2 >= 0",
        "a0 + 2*a2 + 2*b1 + b3 - pr0 - pr2 >= 0",
        "a0 + a3 - b0 + b1 + b2 - 2*b3 + pr0 + pr2 >= 0",
        "b0 + b1 + 2*b2 + 2*b3 - pr0 - pr2 >= 0",
        "a2 + b0 - pr0 >= 0",
        "- a1 - 3*a2 - a3 + 2*b0 + b2 + 2*pr0 + 2*pr2 >= 0",
        "- a0 + 2*a1 + 2*a2 + a3 - b0 - 3*b1 + 3*pr0 + 2*pr2 >= 0",
        "pr1 - pr2 >= 0",
        "- pr1 + pr2 >= 0",
    ]

    """MILP model for key-schedule-only difference propagation.

    fixedVariables is optional. When present, it accepts full key states such
    as {"ks_0": "...128-bit hex..."} or individual bits such as
    {"ks_0_3_2": 1}.
    """

    def __init__(self, params):
        self.nrounds = int(params.get("nrounds", 1))
        self.fixed_variables = params.get("fixedVariables", {})
        self.time_limit = params.get("timelimit", 60)
        self.outputflag = int(params.get("outputflag", 0))
        self.branch_size = 8
        self.key_size = 32
        self.key_shift = 1
        self.key_sbox_positions = (3, 7)
        self.model = None
        self.states = []
        self.weight_terms = []
        self.sbox_probability_groups = []
        os.makedirs(TMP_DIR, exist_ok=True)
        self.lp_file_name = params.get("lp_file_name") or os.path.join(
            TMP_DIR,
            f"splight_h_keydiff_{self.nrounds}_{os.getpid()}_{int(time.time() * 1000)}.lp",
        )

    def nibble_bits(self, name):
        return [self.model.addVar(vtype=GRB.BINARY, name=f"{name}_{bit}") for bit in range(4)]

    def key_state_variables(self, r):
        return [self.nibble_bits(f"ks_{r}_{n}") for n in range(self.key_size)]

    def key_core_variables(self, r, k0):
        """Return key-core outputs, allocating variables only for key S-boxes."""
        core = list(k0)
        for i in self.key_sbox_positions:
            core[i] = self.nibble_bits(f"kc_{r}_{i}")
        return core

    @staticmethod
    def xor_bit(model, u, v, w):
        model.addConstr(u + v + w <= 2)
        model.addConstr(u + v - w >= 0)
        model.addConstr(u - v + w >= 0)
        model.addConstr(-u + v + w >= 0)

    def probability_variables(self, tag):
        pr = [self.model.addVar(vtype=GRB.BINARY, name=f"pr_{tag}_{bit}") for bit in range(3)]
        self.weight_terms.extend(pr)
        round_index, nibble_index = map(int, str(tag).split("_"))
        self.sbox_probability_groups.append({
            "round": round_index,
            "nibble": nibble_index,
            "pr": pr,
        })
        return pr

    @staticmethod
    def _linear_expr_from_inequality(left, variables):
        expr = 0
        for sign, coeff, name in re.findall(r"([+-]?)\s*(?:(\d+)\*)?\s*([A-Za-z]+\d+)", left):
            value = int(coeff) if coeff else 1
            if sign == "-":
                value = -value
            expr += value * variables[name]
        return expr

    def constraints_by_sbox(self, di, do, pr):
        variables = {f"a{i}": di[i] for i in range(4)}
        variables.update({f"b{i}": do[i] for i in range(4)})
        variables.update({f"pr{i}": pr[i] for i in range(3)})
        for ineq in self.sbox_inequalities:
            left, right = ineq.split(">=")
            expr = self._linear_expr_from_inequality(left, variables)
            self.model.addConstr(expr >= int(right.strip()))

    def add_sbox_constraints(self, sbox_in, sbox_out, tag):
        pr = self.probability_variables(tag)
        self.constraints_by_sbox(sbox_in, sbox_out, pr)

    def generate_key_schedule_constraints(self):
        for r in range(self.nrounds):
            kin = self.states[r]
            kout = self.states[r + 1]
            k0 = kin[:8]
            k1 = kin[8:16]
            k2 = kin[16:24]
            k3 = kin[24:32]
            core = self.key_core_variables(r, k0)
            for i in range(self.branch_size):
                if i in self.key_sbox_positions:
                    self.add_sbox_constraints(k0[i], core[i], f"{r}_{i}")
            rotated = [core[(i + self.key_shift) % self.branch_size] for i in range(self.branch_size)]
            for i in range(self.branch_size):
                for bit in range(4):
                    self.xor_bit(self.model, rotated[i][bit], k1[i][bit], kout[i][bit])
                    self.model.addConstr(kout[8 + i][bit] == k2[i][bit])
                    self.model.addConstr(kout[16 + i][bit] == k3[i][bit])
                    self.model.addConstr(kout[24 + i][bit] == k0[i][bit])

    def declare_fixed_variables(self):
        if not self.fixed_variables:
            return
        for name, value in self.fixed_variables.items():
            parts = name.split("_")
            if len(parts) == 2 and parts[0] == "ks":
                bits = f"{int(str(value), 16):0128b}" if isinstance(value, str) else f"{int(value):0128b}"
                flat = [bit for nibble in self.states[int(parts[1])] for bit in nibble]
                for var, bit in zip(flat, bits):
                    self.model.addConstr(var == int(bit))
            elif len(parts) == 3 and parts[0] == "ks":
                bits = nibble_to_bits(int(value, 16) if isinstance(value, str) else int(value))
                nibble = self.states[int(parts[1])][int(parts[2])]
                for var, bit in zip(nibble, bits):
                    self.model.addConstr(var == int(bit))
            elif len(parts) == 4 and parts[0] == "ks":
                self.model.addConstr(self.states[int(parts[1])][int(parts[2])][int(parts[3])] == int(value))
            else:
                raise ValueError(f"unsupported fixed variable: {name}")

    @staticmethod
    def state_to_hex(model, state_vars):
        bits = "".join(str(int(round(var.X))) for nibble in state_vars for var in nibble)
        return f"{int(bits, 2):032X}"

    @staticmethod
    def nibbles_to_hex(model, nibbles):
        bits = "".join(str(int(round(var.X))) for nibble in nibbles for var in nibble)
        return f"{int(bits, 2):0{len(nibbles)}X}"

    def round_sbox_weight(self, r):
        weight = 0
        by_sbox = {}
        for group in self.sbox_probability_groups:
            if group["round"] != r:
                continue
            value = sum(int(round(var.X)) for var in group["pr"])
            by_sbox[str(group["nibble"])] = value
            weight += value
        return weight, by_sbox

    def make_model(self):
        if Model is None:
            raise RuntimeError("gurobipy is required for KeyDiff")
        self.model = Model("splight_keydiff")
        self.model.Params.OutputFlag = self.outputflag
        if self.time_limit is not None:
            self.model.Params.TimeLimit = int(self.time_limit)
        self.states = [self.key_state_variables(r) for r in range(self.nrounds + 1)]
        self.generate_key_schedule_constraints()
        self.declare_fixed_variables()
        self.model.setObjective(quicksum(self.weight_terms) if self.weight_terms else 0, GRB.MINIMIZE)
        self.model.update()
        self.model.write(self.lp_file_name)
        return self.lp_file_name

    def solve(self):
        if self.model is None:
            self.make_model()
        self.model.optimize()
        if self.model.Status not in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.INTERRUPTED) or self.model.SolCount == 0:
            raise RuntimeError("keydiff MILP has no feasible solution")
        states = [self.state_to_hex(self.model, state) for state in self.states]
        round_details = []
        for r in range(self.nrounds):
            weight, by_sbox = self.round_sbox_weight(r)
            round_details.append({
                "round": r,
                "ks_in": states[r],
                "sbox_input_32": self.nibbles_to_hex(self.model, self.states[r][:8]),
                "ks_out": states[r + 1],
                "sbox_weight": weight,
                "sbox_weight_by_nibble": by_sbox,
                "probability": f"2^(-{weight})",
            })
        return {
            "nrounds": self.nrounds,
            "fixedVariables": self.fixed_variables,
            "states": states,
            "round_details": round_details,
            "input_state": states[0],
            "output_state": states[-1],
            "weight": float(self.model.ObjVal),
            "probability": f"2^(-{float(self.model.ObjVal):g})",
            "lp_file": self.lp_file_name,
        }


def solve_key_schedule_diff_milp(fixed_state_hex, rounds, direction, time_limit=60):
    fixed_name = "ks_0" if direction == "forward" else f"ks_{int(rounds)}"
    keydiff = KeyDiff({
        "nrounds": int(rounds),
        "fixedVariables": {fixed_name: fixed_state_hex},
        "timelimit": time_limit,
    })
    result = keydiff.solve()
    result["direction"] = direction
    result["fixed_state"] = fixed_state_hex
    return result


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Solve Splight key-schedule difference MILP.")
    parser.add_argument("--rounds", type=int, required=True)
    parser.add_argument("--fix", action="append", default=[],
                        help="Fixed variable assignment, e.g. ks_0=001122... or ks_0_3_2=1")
    parser.add_argument("--time-limit", type=int, default=60)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    fixed = {}
    for item in args.fix:
        if "=" not in item:
            raise SystemExit(f"--fix expects name=value, got {item}")
        name, value = item.split("=", 1)
        fixed[name] = value
    solver = KeyDiff({
        "nrounds": args.rounds,
        "fixedVariables": fixed,
        "timelimit": args.time_limit,
    })
    result = solver.solve()
    text = json.dumps(result, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
