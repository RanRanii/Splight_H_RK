"""Nibble-level related-key truncated differential propagation for Splight."""

import os
import time

try:
    from gurobipy import GRB, read
except Exception:  # pragma: no cover
    GRB = None
    read = None


TMP_DIR = "tmp"


class RKTruncDiff:
    def __init__(
        self,
        nrounds=1,
        prefix="",
        mode="standard",
        rk_mode="rk-ladder",
        round_offset=0,
        time_limit=None,
        lp_file_name=None,
    ):
        self.nrounds = int(nrounds)
        self.prefix = prefix
        self.mode = mode
        self.rk_mode = rk_mode
        self.round_offset = int(round_offset)
        self.time_limit = time_limit
        self.branch_size = 8
        self.state_size = 16
        self.key_size = 32
        self.shift_nibbles = 2
        self.key_shift = 1
        self.key_sbox_positions = (3, 7)
        self.milp_variables = []
        self.xor_counter = 0
        os.makedirs(TMP_DIR, exist_ok=True)
        self.lp_file_name = lp_file_name or os.path.join(
            TMP_DIR, f"splight_h_rk_td_{os.getpid()}_{int(time.time() * 1000)}.lp"
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

    def _name(self, base):
        return f"{self.prefix}{base}" if self.prefix else base

    def generate_state_variables(self, r):
        xs = [self._name(f"x_{r}_{i}") for i in range(self.state_size)]
        self.milp_variables.extend(xs)
        return xs

    def generate_round_variables(self, r):
        ys = [self._name(f"y_{r}_{i}") for i in range(self.branch_size)]
        ls = [self._name(f"l_{r}_{i}") for i in range(self.branch_size)]
        rks = [self._name(f"rk_{r}_{i}") for i in range(self.branch_size)]
        aks = [self._name(f"ak_{r}_{i}") for i in range(self.branch_size)]
        zs = [self._name(f"z_{r}_{i}") for i in range(self.branch_size)]
        self.milp_variables.extend(ys + ls + rks + aks + zs)
        return ys, ls, rks, aks, zs

    def generate_key_state_variables(self, r):
        ks = [self._name(f"ks_{r}_{i}") for i in range(self.key_size)]
        self.milp_variables.extend(ks)
        return ks

    def generate_key_core_variables(self, r):
        core = [self._name(f"kc_{r}_{i}") for i in range(self.branch_size)]
        self.milp_variables.extend(core)
        return core

    def key_sbox_vars(self, global_round):
        k = self.generate_key_state_variables(global_round)
        return [k[pos] for pos in self.key_sbox_positions]

    def master_key_vars(self):
        return self.generate_key_state_variables(0)

    def constraints_by_equality(self, u, v):
        return [f"{u} - {v} = 0"]

    def constraint_by_trunc_xor(self, a, b, c):
        """Truncated XOR allowing cancellation: (1, 1) may map to 0 or 1."""
        return [
            f"{a} + {b} - {c} >= 0",
            f"{a} - {b} + {c} >= 0",
            f"- {a} + {b} + {c} >= 0",
        ]

    def _xor_constraints(self, u, v, w, mode):
        return self.constraint_by_trunc_xor(u, v, w)

    def _xor_many(self, inputs, output, mode):
        if len(inputs) == 1:
            return self.constraints_by_equality(inputs[0], output)
        constraints = []
        acc = inputs[0]
        for idx, item in enumerate(inputs[1:], start=1):
            out = output if idx == len(inputs) - 1 else self._name(f"d_{self.xor_counter}")
            if out != output:
                self.milp_variables.append(out)
                self.xor_counter += 1
            constraints.extend(self._xor_constraints(acc, item, out, mode))
            acc = out
        return constraints

    def constraints_by_linear_layer(self, r, mode):
        ys, ls, _, _, _ = self.generate_round_variables(r)
        constraints = []
        for base in (0, 4):
            constraints.extend(self._xor_many([ls[base + 3], ys[base + 3]], ls[base], mode))
            constraints.extend(self.constraints_by_equality(ys[base], ls[base + 1]))
            constraints.extend(self._xor_many([ys[base + 1], ys[base + 2]], ls[base + 2], mode))
            constraints.extend(self._xor_many([ys[base], ys[base + 2]], ls[base + 3], mode))
        return constraints

    def generate_key_schedule_constraints(self, max_global_round, mode=None):
        if self.rk_mode == "rk-debug-independent":
            return []
        mode = mode or self.mode
        constraints = []
        for r in range(max_global_round):
            kin = self.generate_key_state_variables(r)
            kout = self.generate_key_state_variables(r + 1)
            core = self.generate_key_core_variables(r)
            k0 = kin[:8]
            k1 = kin[8:16]
            k2 = kin[16:24]
            k3 = kin[24:32]
            for i in range(self.branch_size):
                if i in self.key_sbox_positions:
                    constraints.extend(self.constraints_by_equality(k0[i], core[i]))
                else:
                    constraints.extend(self.constraints_by_equality(k0[i], core[i]))
            rotated = [core[(i + self.key_shift) % self.branch_size] for i in range(self.branch_size)]
            for i in range(self.branch_size):
                constraints.extend(self._xor_constraints(rotated[i], k1[i], kout[i], mode))
                constraints.extend(self.constraints_by_equality(k2[i], kout[8 + i]))
                constraints.extend(self.constraints_by_equality(k3[i], kout[16 + i]))
                constraints.extend(self.constraints_by_equality(k0[i], kout[24 + i]))
        return constraints

    def generate_round_key_constraints(self, local_round):
        if self.rk_mode == "rk-debug-independent":
            return []
        _, _, rks, _, _ = self.generate_round_variables(local_round)
        global_round = self.round_offset + local_round
        key_after_update = self.generate_key_state_variables(global_round + 1)
        constraints = []
        for i in range(self.branch_size):
            constraints.extend(self.constraints_by_equality(rks[i], key_after_update[i]))
        return constraints

    def generate_round_constraints_forward(self, r, mode=None):
        mode = mode or self.mode
        x_in = self.generate_state_variables(r)
        x_out = self.generate_state_variables(r + 1)
        ys, ls, rks, aks, zs = self.generate_round_variables(r)
        constraints = []
        constraints.extend(self.generate_round_key_constraints(r))
        for i in range(self.branch_size):
            constraints.extend(self.constraints_by_equality(x_in[i], ys[i]))
        constraints.extend(self.constraints_by_linear_layer(r, mode))
        for i in range(self.branch_size):
            constraints.extend(self._xor_constraints(ls[i], rks[i], aks[i], mode))
            constraints.extend(self.constraints_by_equality(aks[i], zs[i]))
            out_idx = (i - self.shift_nibbles) % self.branch_size
            constraints.extend(self._xor_constraints(zs[i], x_in[self.branch_size + i], x_out[out_idx], mode))
            constraints.extend(self.constraints_by_equality(x_in[i], x_out[self.branch_size + i]))
        return constraints

    def generate_round_constraints_backward(self, r, mode=None):
        mode = mode or self.mode
        x_in = self.generate_state_variables(r)
        x_out = self.generate_state_variables(r + 1)
        ys, ls, rks, aks, zs = self.generate_round_variables(r)
        constraints = []
        constraints.extend(self.generate_round_key_constraints(r))
        for i in range(self.branch_size):
            constraints.extend(self.constraints_by_equality(x_in[i], ys[i]))
        constraints.extend(self.constraints_by_linear_layer(r, mode))
        for i in range(self.branch_size):
            constraints.extend(self._xor_constraints(ls[i], rks[i], aks[i], mode))
            constraints.extend(self.constraints_by_equality(aks[i], zs[i]))
            out_idx = (i - self.shift_nibbles) % self.branch_size
            constraints.extend(self._xor_constraints(zs[i], x_out[out_idx], x_in[self.branch_size + i], mode))
            constraints.extend(self.constraints_by_equality(x_in[i], x_out[self.branch_size + i]))
        return constraints

    def active_sbox_vars(self, r):
        x = self.generate_state_variables(r)
        _, _, _, aks, _ = self.generate_round_variables(r)
        return x[:self.branch_size] + aks

    def active_round_key_vars(self, r):
        _, _, rks, _, _ = self.generate_round_variables(r)
        return rks

    def generate_objective_function(self):
        terms = []
        for r in range(self.nrounds):
            terms.extend(self.active_sbox_vars(r))
        return " + ".join(terms) if terms else "0"

    def exclude_trivial_solution(self):
        x0 = self.generate_state_variables(0)
        mk = self.master_key_vars()
        return [" + ".join(x0) + " >= 1", " + ".join(mk) + " >= 1"]

    def declare_binary_vars(self):
        self.milp_variables = self.ordered_set(self.milp_variables)
        return "Binary\n" + "\n".join(self.milp_variables)

    def make_model(self):
        constraints = []
        constraints.extend(self.generate_key_schedule_constraints(self.round_offset + self.nrounds, self.mode))
        for r in range(self.nrounds):
            constraints.extend(self.generate_round_constraints_forward(r, self.mode))
        constraints.extend(self.exclude_trivial_solution())
        lp = "\\ Splight related-key nibble truncated differential model\n"
        lp += "Minimize\n" + self.generate_objective_function() + "\n"
        lp += "Subject To\n" + "\n".join(constraints) + "\n"
        lp += self.declare_binary_vars() + "\nEnd\n"
        with open(self.lp_file_name, "w", encoding="utf-8") as handle:
            handle.write(lp)
        return self.lp_file_name

    def solve(self):
        if read is None:
            raise RuntimeError("gurobipy is required to solve the MILP")
        self.make_model()
        self.milp_model = read(self.lp_file_name)
        self.milp_model.Params.OutputFlag = False
        if self.time_limit is not None:
            self.milp_model.Params.TimeLimit = self.time_limit
        self.milp_model.optimize()
        status = self.milp_model.Status
        objective = None
        if status in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.INTERRUPTED) and self.milp_model.SolCount:
            objective = self.milp_model.objVal
        return {"status": int(status), "objective": objective, "lp_file": self.lp_file_name}
