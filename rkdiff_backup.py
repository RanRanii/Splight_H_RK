"""Bit-wise related-key Splight differential search.

This model instantiates complete related-key differential trails.  It includes
state propagation, master-key difference propagation through Splight's key
schedule, and every round-key difference used by the round function.


ks_g = K0_g || K1_g || K2_g || K3_g
                │
                ▼
        K0 经过 key core
       （位置3、7经过S-box）
                │
            nibble轮转
                │
          与 K1 异或
                ▼
ks_{g+1} = K0' || K2 || K3 || K0

"""

import json
import os
import time

try:
    from gurobipy import GRB, quicksum, read
except Exception:  # pragma: no cover
    GRB = None
    read = None

from splight.splight_spec import nibble_to_bits


TMP_DIR = os.path.join("tmp", "boomerang")


class RKDiff:
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

    def __init__(self, params, fixed_variables=None, time_limit=None):
        if isinstance(params, dict):
            self.nrounds = int(params.get("nrounds", 1))
            self.fixed_variables = params.get("fixedVariables", fixed_variables or {})
            self.nonzero_variables = params.get("nonzeroVariables", [])
            self.time_limit = params.get("timelimit", time_limit)
            self.mode = int(params.get("mode", 0))
            self.start_weight = params.get("startweight", 0)
            self.end_weight = params.get("endweight", 256)
            self.number_of_trails = params.get("numberoftrails", 1)
            self.rk_mode = params.get("rk_mode", "rk-ladder")
            self.round_offset = int(params.get("round_offset", 0))
        else:
            self.nrounds = int(params)
            self.fixed_variables = fixed_variables or {}
            self.nonzero_variables = []
            self.time_limit = time_limit
            self.mode = 0
            self.start_weight = 0
            self.end_weight = 256
            self.number_of_trails = 1
            self.rk_mode = "rk-ladder"
            self.round_offset = 0

        self.branch_size = 8
        self.state_size = 16
        self.key_size = 32
        self.shift_nibbles = 2
        self.key_shift = 1
        self.key_sbox_positions = (3, 7)
        self.milp_variables = []
        self.xor_counter = 0
        self.weight_terms = []
        self.sbox_probability_groups = []
        self.sbox_counter = 0
        self.total_weight = 0
        os.makedirs(TMP_DIR, exist_ok=True)
        self.lp_file_name = os.path.join(
            TMP_DIR, f"splight_h_rkdiff_{os.getpid()}_{int(time.time() * 1000)}.lp"
        )
        self.milp_model = None

    @staticmethod
    def ordered_set(seq):
        seen = set()
        out = []
        for item in seq:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    def nibble_bits(self, base):
        names = [f"{base}_{bit}" for bit in range(4)]
        self.milp_variables.extend(names)
        return names

    def state_variables(self, r):
        return [self.nibble_bits(f"x_{r}_{n}") for n in range(self.state_size)]

    def key_state_variables(self, r):
        return [self.nibble_bits(f"ks_{r}_{n}") for n in range(self.key_size)]

    def round_variables(self, r):
        ys = [self.nibble_bits(f"y_{r}_{i}") for i in range(self.branch_size)]
        ls = [self.nibble_bits(f"l_{r}_{i}") for i in range(self.branch_size)]
        rks = [self.nibble_bits(f"rk_{r}_{i}") for i in range(self.branch_size)]
        aks = [self.nibble_bits(f"ak_{r}_{i}") for i in range(self.branch_size)]
        zs = [self.nibble_bits(f"z_{r}_{i}") for i in range(self.branch_size)]
        return ys, ls, rks, aks, zs

    def key_core_variables(self, r):
        return [self.nibble_bits(f"kc_{r}_{i}") for i in range(self.branch_size)]

    def eq_bits(self, left, right):
        return [f"{u} - {v} = 0" for u, v in zip(left, right)]

    def xor_bit(self, u, v, w):
        return [
            f"{u} + {v} + {w} <= 2",
            f"{u} + {v} - {w} >= 0",
            f"{u} - {v} + {w} >= 0",
            f"- {u} + {v} + {w} >= 0",
        ]

    def xor_nibble(self, left, right, out):
        constraints = []
        for u, v, w in zip(left, right, out):
            constraints.extend(self.xor_bit(u, v, w))
        return constraints

    def xor_many_nibbles(self, inputs, output):
        if len(inputs) == 1:
            return self.eq_bits(inputs[0], output)
        constraints = []
        acc = inputs[0]
        for idx, item in enumerate(inputs[1:], start=1):
            out = output if idx == len(inputs) - 1 else self.nibble_bits(f"d_{self.xor_counter}")
            if out is not output:
                self.xor_counter += 1
            constraints.extend(self.xor_nibble(acc, item, out))
            acc = out
        return constraints

    def probability_variables(self, tag=None):
        group_id = self.sbox_counter
        self.sbox_counter += 1
        pr = [f"pr_{group_id}_{bit}" for bit in range(3)]
        self.milp_variables.extend(pr)
        self.weight_terms.extend((1, var) for var in pr)
        self.sbox_probability_groups.append({"tag": tag, "pr": pr})
        return pr

    def constraints_by_sbox(self, di, do, pr):
        constraints = []
        for ineq in self.sbox_inequalities:
            temp = ineq
            for i in range(4):
                temp = temp.replace(f"a{i}", di[i])
            for i in range(4):
                temp = temp.replace(f"b{i}", do[i])
            for i in range(3):
                temp = temp.replace(f"pr{i}", pr[i])
            constraints.append(temp.replace("*", " "))
        return constraints

    def generate_sbox_constraints(self, sbox_in, sbox_out, tag=None):
        pr = self.probability_variables(tag)
        return self.constraints_by_sbox(sbox_in, sbox_out, pr)

    def generate_linear_layer_constraints(self, r):
        ys, ls, _, _, _ = self.round_variables(r)
        constraints = []
        for base in (0, 4):
            constraints.extend(self.xor_many_nibbles([ls[base + 3], ys[base + 3]], ls[base]))
            constraints.extend(self.eq_bits(ys[base], ls[base + 1]))
            constraints.extend(self.xor_many_nibbles([ys[base + 1], ys[base + 2]], ls[base + 2]))
            constraints.extend(self.xor_many_nibbles([ys[base], ys[base + 2]], ls[base + 3]))
        return constraints

    def generate_key_schedule_constraints(self):
        constraints = []
        for r in range(self.round_offset + self.nrounds):
            kin = self.key_state_variables(r)
            kout = self.key_state_variables(r + 1)
            core = self.key_core_variables(r)
            k0 = kin[:8]
            k1 = kin[8:16]
            k2 = kin[16:24]
            k3 = kin[24:32]
            for i in range(self.branch_size):
                if i in self.key_sbox_positions:
                    constraints.extend(self.generate_sbox_constraints(k0[i], core[i], tag=(r, "key", i)))
                else:
                    constraints.extend(self.eq_bits(k0[i], core[i]))
            rotated = [core[(i + self.key_shift) % self.branch_size] for i in range(self.branch_size)]
            for i in range(self.branch_size):
                constraints.extend(self.xor_nibble(rotated[i], k1[i], kout[i]))
                constraints.extend(self.eq_bits(k2[i], kout[8 + i]))
                constraints.extend(self.eq_bits(k3[i], kout[16 + i]))
                constraints.extend(self.eq_bits(k0[i], kout[24 + i]))
        return constraints

    def generate_round_key_constraints(self, r):
        _, _, rks, _, _ = self.round_variables(r)
        key_after_update = self.key_state_variables(self.round_offset + r + 1)
        constraints = []
        for i in range(self.branch_size):
            constraints.extend(self.eq_bits(rks[i], key_after_update[i]))
        return constraints

    def generate_round_constraints(self, r):
        x_in = self.state_variables(r)
        x_out = self.state_variables(r + 1)
        ys, ls, rks, aks, zs = self.round_variables(r)
        constraints = []
        constraints.extend(self.generate_round_key_constraints(r))
        for i in range(self.branch_size):
            constraints.extend(self.generate_sbox_constraints(x_in[i], ys[i], tag=(r, "state-y", i)))
        constraints.extend(self.generate_linear_layer_constraints(r))
        for i in range(self.branch_size):
            constraints.extend(self.xor_nibble(ls[i], rks[i], aks[i]))
            constraints.extend(self.generate_sbox_constraints(aks[i], zs[i], tag=(r, "state-z", i)))
            out_idx = (i - self.shift_nibbles) % self.branch_size
            constraints.extend(self.xor_nibble(zs[i], x_in[self.branch_size + i], x_out[out_idx]))
            constraints.extend(self.eq_bits(x_in[i], x_out[self.branch_size + i]))
        return constraints

    def declare_fixed_variables(self):
        constraints = []
        for name, value in self.fixed_variables.items():
            parts = name.split("_")
            if len(parts) == 2 and parts[0] in ("x", "k", "ks"):
                expected = 64 if parts[0] == "x" else 128
                nibbles = 16 if parts[0] == "x" else 32
                bits = f"{int(value, 16):0{expected}b}" if isinstance(value, str) else f"{int(value):0{expected}b}"
                variables = self.state_variables(int(parts[1])) if parts[0] == "x" else self.key_state_variables(int(parts[1]))
                flat = [bit for nibble in variables for bit in nibble]
                if len(bits) != 4 * nibbles:
                    raise ValueError(f"fixed variable {name} has invalid length")
                constraints.extend(f"{var} = {val}" for var, val in zip(flat, bits))
            elif len(parts) == 3 and parts[0] in ("x", "k", "ks"):
                bits = nibble_to_bits(int(value, 16) if isinstance(value, str) else int(value))
                constraints.extend(f"{name}_{i} = {bit}" for i, bit in enumerate(bits))
            elif len(parts) == 4:
                constraints.append(f"{name} = {int(value)}")
        return constraints

    def declare_nonzero_variables(self):
        constraints = []
        for name in self.nonzero_variables:
            parts = name.split("_")
            if len(parts) == 3 and parts[0] in ("x", "k", "ks"):
                variables = self.state_variables(int(parts[1])) if parts[0] == "x" else self.key_state_variables(int(parts[1]))
                nibble = variables[int(parts[2])]
                constraints.append(" + ".join(nibble) + " >= 1")
            elif len(parts) == 2 and parts[0] in ("x", "k", "ks"):
                variables = self.state_variables(int(parts[1])) if parts[0] == "x" else self.key_state_variables(int(parts[1]))
                flat = [bit for nibble in variables for bit in nibble]
                constraints.append(" + ".join(flat) + " >= 1")
            else:
                raise ValueError(f"nonzero variable {name} is not a supported nibble/state variable")
        return constraints

    def flatten_state(self, s):
        return [bit for nibble in s for bit in nibble]

    def nibble_value(self, bits):
        return int("".join(str(int(round(self.milp_model.getVarByName(bit).X))) for bit in bits), 2)

    def nibbles_to_hex_from_bits(self, nibbles):
        return "".join(f"{self.nibble_value(bits):X}" for bits in nibbles).upper()

    def generate_objective_function(self):
        if not self.weight_terms:
            return "0"
        return " + ".join(f"{weight} {var}" for weight, var in self.weight_terms)

    def make_model(self):
        self.milp_variables = []
        self.xor_counter = 0
        self.weight_terms = []
        self.sbox_probability_groups = []
        self.sbox_counter = 0
        constraints = []
        constraints.extend(self.generate_key_schedule_constraints())
        for r in range(self.nrounds):
            constraints.extend(self.generate_round_constraints(r))
        state_bits = [bit for nibble in self.state_variables(0) for bit in nibble]
        key_bits = [bit for nibble in self.key_state_variables(0) for bit in nibble]
        constraints.append(" + ".join(state_bits) + " >= 1")
        constraints.append(" + ".join(key_bits) + " >= 1")
        constraints.extend(self.declare_fixed_variables())
        constraints.extend(self.declare_nonzero_variables())
        lp = "\\ Splight bit-wise related-key differential model\n"
        lp += "Minimize\n" + self.generate_objective_function() + "\n"
        lp += "Subject To\n" + "\n".join(constraints) + "\n"
        self.milp_variables = self.ordered_set(self.milp_variables)
        lp += "Binary\n" + "\n".join(self.milp_variables) + "\nEnd\n"
        with open(self.lp_file_name, "w", encoding="utf-8") as handle:
            handle.write(lp)
        return self.lp_file_name

    def _round_weight(self, r, kind):
        weight = 0
        for group in self.sbox_probability_groups:
            tag = group["tag"]
            if tag is None or tag[0] != r or tag[1] != kind:
                continue
            weight += sum(int(round(self.milp_model.getVarByName(var).X)) for var in group["pr"])
        return weight

    def parse_solver_output(self):
        get_bit_value = lambda name: str(int(round(self.milp_model.getVarByName(name).X)))
        characteristic = {}
        max_key_round = self.round_offset + self.nrounds
        for r in range(max_key_round + 1):
            k_bits = self.flatten_state(self.key_state_variables(r))
            characteristic[f"ks_global_{r}"] = f"{int(''.join(map(get_bit_value, k_bits)), 2):032X}"
        for r in range(self.nrounds + 1):
            x_bits = self.flatten_state(self.state_variables(r))
            k_bits = self.flatten_state(self.key_state_variables(r))
            characteristic[f"x_{r}"] = f"{int(''.join(map(get_bit_value, x_bits)), 2):016X}"
            characteristic[f"ks_{r}"] = f"{int(''.join(map(get_bit_value, k_bits)), 2):032X}"
            if r < self.nrounds:
                global_round_key_index = self.round_offset + r + 1
                characteristic[f"round_ks_{r}"] = characteristic[f"ks_global_{global_round_key_index}"]
                characteristic[f"round_ks_global_index_{r}"] = global_round_key_index
                ys, ls, rks, aks, zs = self.round_variables(r)
                characteristic[f"y_{r}"] = self.nibbles_to_hex_from_bits(ys)
                characteristic[f"l_{r}"] = self.nibbles_to_hex_from_bits(ls)
                characteristic[f"rk_{r}"] = self.nibbles_to_hex_from_bits(rks)
                characteristic[f"ak_{r}"] = self.nibbles_to_hex_from_bits(aks)
                characteristic[f"z_{r}"] = self.nibbles_to_hex_from_bits(zs)
                state_w = self._round_weight(r, "state-y") + self._round_weight(r, "state-z")
                key_w = self._round_weight(r, "key")
                characteristic[f"rw_{r}"] = f"-{state_w}"
                characteristic[f"kw_{r}"] = f"-{key_w}"
                characteristic[f"pr_{r}"] = f"-{state_w + key_w}"
            else:
                for name in ("y", "l", "rk", "ak", "z", "round_ks", "round_ks_global_index", "rw", "kw", "pr"):
                    characteristic[f"{name}_{r}"] = "none"
        characteristic["total_weight"] = "%0.02f" % self.total_weight
        characteristic["nrounds"] = self.nrounds
        characteristic["round_offset"] = self.round_offset
        characteristic["master_key_diff"] = characteristic["ks_0"]
        return characteristic

    @staticmethod
    def print_trail(diff_trail):
        print("Rounds  x                 y         l         RK        ak        z         KS                                  pr      rw      kw     ")
        print("-" * 132)
        round_offset = int(diff_trail.get("round_offset", 0))
        for r in range(diff_trail["nrounds"] + 1):
            ks = diff_trail.get(
                f"round_ks_{r}",
                diff_trail.get(f"ks_global_{round_offset + r + 1}", "none") if r < diff_trail["nrounds"] else "none",
            )
            print(
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
        print(f"Master key diff: {diff_trail.get('master_key_diff', 'none')}")
        print(f"Weight: -{diff_trail.get('total_weight', '0')}")

    def find_characteristic(self):
        self.milp_model.Params.OutputFlag = False
        if self.time_limit is not None:
            self.milp_model.Params.TimeLimit = self.time_limit
        obj = self.milp_model.getObjective()
        if self.start_weight is not None:
            self.milp_model.addConstr(obj >= self.start_weight, "start_weight_constraint")
        start_time = time.time()
        self.milp_model.optimize()
        diff_trail = None
        if self.milp_model.Status in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.INTERRUPTED) and self.milp_model.SolCount:
            self.total_weight = self.milp_model.objVal
            if self.milp_model.Status == GRB.OPTIMAL:
                self.milp_model.addConstr(obj <= self.total_weight, "fix_best_weight_upper")
                self.milp_model.addConstr(obj >= self.total_weight, "fix_best_weight_lower")
                mk_vars = [
                    self.milp_model.getVarByName(bit)
                    for nibble in self.key_state_variables(0)
                    for bit in nibble
                ]
                self.milp_model.setObjective(quicksum(mk_vars), GRB.MINIMIZE)
                self.milp_model.optimize()
            print(f"\nThe probability of the best related-key differential characteristic: 2^-({self.total_weight})")
            print("\nRelated-key differential trail:\n")
            diff_trail = self.parse_solver_output()
            self.print_trail(diff_trail)
        elif self.milp_model.Status == GRB.INFEASIBLE:
            print("The model is infeasible!")
        else:
            print("Unknown error!")
        print("Time used: %0.02f" % (time.time() - start_time))
        return diff_trail

    def solve(self):
        if read is None:
            raise RuntimeError("gurobipy is required to solve the MILP")
        if not os.path.exists(self.lp_file_name):
            self.make_model()
        self.milp_model = read(self.lp_file_name)
        if self.mode == 0:
            return self.find_characteristic()
        print("Only mode 0 is currently implemented for RKDiff.")
        return None

    def solve_and_save(self, output_path):
        trail = self.solve()
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(trail, handle, indent=2)
        return trail
