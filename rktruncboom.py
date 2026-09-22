"""Related-key Hadipour three-part truncated sandwich model for Splight."""

import json
import os
import time

try:
    from gurobipy import GRB, quicksum, read
except Exception:  # pragma: no cover
    GRB = None
    quicksum = None
    read = None

from rktruncdiff import RKTruncDiff


TMP_DIR = "tmp"


class RKTruncatedBoomerang:
    def __init__(self, r0, rm, r1, w0, wm, w1, rk_mode="rk-ladder", time_limit=None):
        self.r0 = int(r0)
        self.rm = int(rm)
        self.r1 = int(r1)
        self.R0 = self.r0 + self.rm
        self.R1 = self.rm + self.r1
        self.w0 = int(w0)
        self.wm = int(wm)
        self.w1 = int(w1)
        self.rk_mode = rk_mode
        self.time_limit = time_limit
        self.milp_variables = []
        os.makedirs(TMP_DIR, exist_ok=True)
        self.lp_file_name = os.path.join(
            TMP_DIR,
            f"splight_h_rk_{self.r0}_{self.rm}_{self.r1}_{self.rk_mode}.lp",
        )
        self.upper = RKTruncDiff(self.R0, prefix="u", rk_mode=rk_mode, round_offset=0)
        self.lower = RKTruncDiff(self.R1, prefix="v", rk_mode=rk_mode, round_offset=self.r0)
        self.milp_model = None
        self.solution = {}
        self.truncated_nogood_count = 0

    @staticmethod
    def ordered_set(seq):
        seen = set()
        out = []
        for item in seq:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    def _collect(self):
        self.milp_variables = self.ordered_set(
            self.milp_variables + self.upper.milp_variables + self.lower.milp_variables
        )

    def constraint_by_xor(self, a, b, c):
        """Boomerang middle truncated XOR without cancellation."""
        return [
            f"{c} - {a} >= 0",
            f"{c} - {b} >= 0",
            f"{a} + {b} - {c} >= 0",
        ]

    def _xor_many_em(self, diff, inputs, output):
        if len(inputs) == 1:
            return diff.constraints_by_equality(inputs[0], output)
        constraints = []
        acc = inputs[0]
        for idx, item in enumerate(inputs[1:], start=1):
            out = output if idx == len(inputs) - 1 else diff._name(f"d_{diff.xor_counter}")
            if out != output:
                diff.milp_variables.append(out)
                diff.xor_counter += 1
            constraints.extend(self.constraint_by_xor(acc, item, out))
            acc = out
        return constraints

    def constraints_by_linear_layer_em(self, diff, r):
        ys, ls, _, _, _ = diff.generate_round_variables(r)
        constraints = []
        for base in (0, 4):
            constraints.extend(self._xor_many_em(diff, [ls[base + 3], ys[base + 3]], ls[base]))
            constraints.extend(diff.constraints_by_equality(ys[base], ls[base + 1]))
            constraints.extend(self._xor_many_em(diff, [ys[base + 1], ys[base + 2]], ls[base + 2]))
            constraints.extend(self._xor_many_em(diff, [ys[base], ys[base + 2]], ls[base + 3]))
        return constraints

    def generate_key_schedule_round_constraints(self, diff, global_round, em_round=False):
        constraints = []
        kin = diff.generate_key_state_variables(global_round)
        kout = diff.generate_key_state_variables(global_round + 1)
        core = diff.generate_key_core_variables(global_round)
        k0 = kin[: diff.branch_size]
        k1 = kin[diff.branch_size : 2 * diff.branch_size]
        k2 = kin[2 * diff.branch_size : 3 * diff.branch_size]
        k3 = kin[3 * diff.branch_size : 4 * diff.branch_size]
        for i in range(diff.branch_size):
            constraints.extend(diff.constraints_by_equality(k0[i], core[i]))
        rotated = [core[(i + diff.key_shift) % diff.branch_size] for i in range(diff.branch_size)]
        for i in range(diff.branch_size):
            if em_round:
                constraints.extend(self.constraint_by_xor(rotated[i], k1[i], kout[i]))
            else:
                constraints.extend(diff.constraint_by_trunc_xor(rotated[i], k1[i], kout[i]))
            constraints.extend(diff.constraints_by_equality(k2[i], kout[diff.branch_size + i]))
            constraints.extend(diff.constraints_by_equality(k3[i], kout[2 * diff.branch_size + i]))
            constraints.extend(diff.constraints_by_equality(k0[i], kout[3 * diff.branch_size + i]))
        return constraints

    def generate_key_schedule_constraints(self, diff, max_global_round):
        if self.rk_mode == "rk-debug-independent":
            return []
        constraints = []
        for global_round in range(max_global_round):
            em_round = self.r0 <= global_round < self.r0 + self.rm
            constraints.extend(self.generate_key_schedule_round_constraints(diff, global_round, em_round))
        return constraints

    def generate_round_constraints_forward_em(self, diff, r):
        x_in = diff.generate_state_variables(r)
        x_out = diff.generate_state_variables(r + 1)
        ys, ls, rks, aks, zs = diff.generate_round_variables(r)
        constraints = []
        constraints.extend(diff.generate_round_key_constraints(r))
        for i in range(diff.branch_size):
            constraints.extend(diff.constraints_by_equality(x_in[i], ys[i]))
        constraints.extend(self.constraints_by_linear_layer_em(diff, r))
        for i in range(diff.branch_size):
            constraints.extend(self.constraint_by_xor(ls[i], rks[i], aks[i]))
            constraints.extend(diff.constraints_by_equality(aks[i], zs[i]))
            out_idx = (i - diff.shift_nibbles) % diff.branch_size
            constraints.extend(self.constraint_by_xor(zs[i], x_in[diff.branch_size + i], x_out[out_idx]))
            constraints.extend(diff.constraints_by_equality(x_in[i], x_out[diff.branch_size + i]))
        return constraints

    def generate_round_constraints_backward_em(self, diff, r):
        x_in = diff.generate_state_variables(r)
        x_out = diff.generate_state_variables(r + 1)
        ys, ls, rks, aks, zs = diff.generate_round_variables(r)
        constraints = []
        constraints.extend(diff.generate_round_key_constraints(r))
        for i in range(diff.branch_size):
            constraints.extend(diff.constraints_by_equality(x_in[i], ys[i]))
        constraints.extend(self.constraints_by_linear_layer_em(diff, r))
        for i in range(diff.branch_size):
            constraints.extend(self.constraint_by_xor(ls[i], rks[i], aks[i]))
            constraints.extend(diff.constraints_by_equality(aks[i], zs[i]))
            out_idx = (i - diff.shift_nibbles) % diff.branch_size
            constraints.extend(self.constraint_by_xor(zs[i], x_out[out_idx], x_in[diff.branch_size + i]))
            constraints.extend(diff.constraints_by_equality(x_in[i], x_out[diff.branch_size + i]))
        return constraints

    def generate_upper_constraints(self):
        constraints = []
        constraints.extend(self.generate_key_schedule_constraints(self.upper, self.R0))
        for r in range(self.R0):
            if r < self.r0:
                constraints.extend(self.upper.generate_round_constraints_forward(r, "trunc"))
            else:
                constraints.extend(self.generate_round_constraints_forward_em(self.upper, r))
        self._collect()
        return constraints

    def generate_lower_constraints(self):
        constraints = []
        constraints.extend(self.generate_key_schedule_constraints(self.lower, self.r0 + self.R1))
        for r in range(self.R1):
            if r < self.rm:
                constraints.extend(self.generate_round_constraints_backward_em(self.lower, r))
            else:
                constraints.extend(self.lower.generate_round_constraints_forward(r, "trunc"))
        self._collect()
        return constraints

    def generate_common_active_variables(self, r):
        ss = [f"s_{r}_{j}" for j in range(16)]
        self.milp_variables.extend(ss)
        return ss

    def generate_common_key_active_variables(self, r):
        ks = [f"ks_common_{r}_{j}" for j in range(2)]
        self.milp_variables.extend(ks)
        return ks

    def generate_common_active_constraints(self):
        constraints = []
        for r in range(self.rm):
            ss = self.generate_common_active_variables(r)
            upper_vars = self.upper.active_sbox_vars(self.r0 + r)
            lower_vars = self.lower.active_sbox_vars(r)
            for u, v, s in zip(upper_vars, lower_vars, ss):
                constraints.append(f"{u} - {s} >= 0")
                constraints.append(f"{v} - {s} >= 0")
                constraints.append(f"- {u} - {v} + {s} >= -1")
            key_ss = self.generate_common_key_active_variables(r)
            global_round = self.r0 + r
            upper_key_sboxes = self.upper.key_sbox_vars(global_round)
            lower_key_sboxes = self.lower.key_sbox_vars(global_round)
            for u, v, s in zip(upper_key_sboxes, lower_key_sboxes, key_ss):
                constraints.append(f"{u} - {s} >= 0")
                constraints.append(f"{v} - {s} >= 0")
                constraints.append(f"- {u} - {v} + {s} >= -1")
                constraints.append(f"{u} + {v} <= 1")
        self._collect()
        return constraints

    def generate_key_ladder_constraints(self):
        if self.rk_mode != "rk-ladder":
            return []
        constraints = []
        for r in range(self.rm):
            global_round = self.r0 + r
            upper_key_sboxes = self.upper.key_sbox_vars(global_round)
            lower_key_sboxes = self.lower.key_sbox_vars(global_round)
            for u, v in zip(upper_key_sboxes, lower_key_sboxes):
                constraints.append(f"{u} + {v} <= 1")
        self._collect()
        return constraints

    def generate_objective_function(self):
        terms = []
        for r in range(self.r0):
            terms.extend(f"{self.w0} {v}" for v in self.upper.active_sbox_vars(r))
            # Include ordinary upper key-schedule S-box activity in E0.
            # The global key-state index follows the same convention as the
            # existing key-schedule constraint builder; the middle interval
            # starts at global round r0 and is therefore excluded here.
            terms.extend(f"{self.w0} {v}" for v in self.upper.key_sbox_vars(r))
        for r in range(self.rm):
            terms.extend(f"{self.wm} {v}" for v in self.generate_common_active_variables(r))
            terms.extend(f"{self.wm} {v}" for v in self.generate_common_key_active_variables(r))
        for r in range(self.rm, self.R1):
            terms.extend(f"{self.w1} {v}" for v in self.lower.active_sbox_vars(r))
            # The lower model is offset by r0.  Count only ordinary
            # key-schedule S-boxes in E1; middle key-schedule activity is
            # already represented by the common middle variables above.
            terms.extend(f"{self.w1} {v}" for v in self.lower.key_sbox_vars(self.r0 + r))
        self._collect()
        return " + ".join(terms) if terms else "0"

    def exclude_trivial_solution(self):
        ux0 = self.upper.generate_state_variables(0)
        ux_e0_out = self.upper.generate_state_variables(self.r0)
        vx0 = self.lower.generate_state_variables(0)
        vx_e1_in = self.lower.generate_state_variables(self.rm)
        vx_e1_out = self.lower.generate_state_variables(self.R1)
        umk = self.upper.master_key_vars()
        vmk = self.lower.master_key_vars()
        self._collect()
        constraints = [
            " + ".join(ux0) + " >= 1",
            " + ".join(vx0) + " >= 1",
            " + ".join(umk) + " >= 1",
            " + ".join(vmk) + " >= 1",
        ]
        if self.r0 > 0:
            constraints.append(" + ".join(ux_e0_out) + " >= 1")
        if self.r1 > 0:
            constraints.append(" + ".join(vx_e1_in) + " >= 1")
            constraints.append(" + ".join(vx_e1_out) + " >= 1")
        return constraints

    def declare_binary_vars(self):
        self._collect()
        self.milp_variables = self.ordered_set(self.milp_variables)
        return "Binary\n" + "\n".join(self.milp_variables)

    def make_model(self):
        constraints = []
        constraints.extend(self.generate_upper_constraints())
        constraints.extend(self.generate_lower_constraints())
        constraints.extend(self.generate_common_active_constraints())
        constraints.extend(self.generate_key_ladder_constraints())
        constraints.extend(self.exclude_trivial_solution())
        lp = "\\ Splight related-key Hadipour truncated boomerang/sandwich model\n"
        lp += "Minimize\n" + self.generate_objective_function() + "\n"
        lp += "Subject To\n" + "\n".join(constraints) + "\n"
        lp += self.declare_binary_vars() + "\nEnd\n"
        with open(self.lp_file_name, "w", encoding="utf-8") as handle:
            handle.write(lp)
        return self.lp_file_name

    @staticmethod
    def _gurobi_status_name(status):
        names = {
            GRB.OPTIMAL: "OPTIMAL",
            GRB.INFEASIBLE: "INFEASIBLE",
            GRB.INF_OR_UNBD: "INF_OR_UNBD",
            GRB.UNBOUNDED: "UNBOUNDED",
            GRB.TIME_LIMIT: "TIME_LIMIT",
            GRB.INTERRUPTED: "INTERRUPTED",
        }
        return names.get(status, f"GUROBI_STATUS_{status}")

    def load_model(self):
        if read is None:
            raise RuntimeError("gurobipy is required to solve the MILP")
        if not os.path.exists(self.lp_file_name):
            self.make_model()
        self.milp_model = read(self.lp_file_name)
        self.truncated_nogood_count = 0
        return self.milp_model

    def optimize_next_truncated_path(self, output_flag=False, time_limit_override=None):
        """Optimize the current truncated model without rebuilding it."""
        if self.milp_model is None:
            self.load_model()
        self.milp_model.setParam(GRB.Param.OutputFlag, bool(output_flag))
        effective_time_limit = (
            time_limit_override
            if time_limit_override is not None
            else self.time_limit
        )
        if effective_time_limit is not None:
            self.milp_model.Params.TimeLimit = max(float(effective_time_limit), 1e-3)
        start_time = time.time()
        self.milp_model.optimize()
        elapsed_time = time.time() - start_time
        status = self._gurobi_status_name(self.milp_model.Status)
        if not self.milp_model.SolCount:
            return {
                "status": status,
                "solution": None,
                "objective": None,
                "elapsed_seconds": elapsed_time,
            }
        parsed = self.parse_solution()
        objective = float(self.milp_model.ObjVal)
        return {
            "status": status,
            "solution": parsed,
            "objective": objective,
            "elapsed_seconds": elapsed_time,
        }

    def find_truncated_boomerang_trail(self, time_limit_override=None):
        """Preserve the original one-shot search used when exact mode is off."""
        self.make_model()
        self.load_model()
        self.milp_model.Params.PoolSearchMode = 2
        self.milp_model.Params.PoolSolutions = 10
        self.milp_model.Params.SolutionNumber = 0
        result = self.optimize_next_truncated_path(
            output_flag=True,
            time_limit_override=time_limit_override,
        )
        if result["solution"] is not None:
            print(f"Number of active S-boxes: {result['objective']}")
        else:
            print("No feasible related-key truncated boomerang trail found")
        print("Total time to find the trail: %0.02f seconds" % result["elapsed_seconds"])
        return result

    def _var_value(self, name):
        var = self.milp_model.getVarByName(name)
        if var is None:
            raise ValueError(f"unknown truncated Gurobi variable: {name}")
        value = int(round(var.X))
        if value not in (0, 1) or abs(var.X - value) > 1e-5:
            raise RuntimeError(f"non-binary value {var.X!r} for truncated variable {name}")
        return value

    @staticmethod
    def _is_truncated_activity_name(name):
        """Select real activity bits and omit temporary XOR auxiliaries."""
        if name.startswith(("ux_", "uy_", "ul_", "urk_", "uak_", "uz_", "uks_", "ukc_")):
            return True
        if name.startswith(("vx_", "vy_", "vl_", "vrk_", "vak_", "vz_", "vks_", "vkc_")):
            return True
        return name.startswith(("s_", "ks_common_"))

    def truncated_solution_signature(self):
        """Return the complete current truncated activity assignment."""
        if self.milp_model is None or not self.milp_model.SolCount:
            raise RuntimeError("no current truncated Gurobi solution is available")
        assignment = []
        for var in sorted(self.milp_model.getVars(), key=lambda item: item.VarName):
            if self._is_truncated_activity_name(var.VarName):
                assignment.append((var.VarName, self._var_value(var.VarName)))
        if not assignment:
            raise RuntimeError("the truncated activity signature is empty")
        return assignment

    def extract_current_truncated_path(self):
        """Freeze the current path before another optimize overwrites Var.X."""
        if self.milp_model is None or not self.milp_model.SolCount:
            raise RuntimeError("no current truncated Gurobi solution is available")
        return {
            "objective": float(self.milp_model.ObjVal),
            "signature": self.truncated_solution_signature(),
            "activity": self.parse_solution(),
            "truncated_model_id": id(self.milp_model),
        }

    def add_truncated_path_nogood(
        self,
        solution,
        truncated_id=None,
        constraint_name=None,
    ):
        """Block one full activity pattern on the existing truncated model."""
        if self.milp_model is None:
            raise RuntimeError("the truncated Gurobi model has not been loaded")
        assignment = solution.get("signature", solution)
        if not assignment:
            raise ValueError("cannot add an empty truncated-path no-good")
        terms = []
        for var_name, value in assignment:
            var = self.milp_model.getVarByName(var_name)
            if var is None:
                raise ValueError(f"unknown Gurobi variable in truncated no-good: {var_name}")
            if value == 0:
                terms.append(var)
            elif value == 1:
                terms.append(1 - var)
            else:
                raise ValueError(f"invalid binary value in truncated no-good: {value}")
        self.truncated_nogood_count += 1
        number = truncated_id if truncated_id is not None else self.truncated_nogood_count
        name = constraint_name or f"truncated_nogood_{int(number):04d}"
        self.milp_model.addConstr(quicksum(terms) >= 1, name=name)
        self.milp_model.update()
        return name

    def _bits(self, names):
        return "".join(str(self._var_value(name)) for name in names)

    def parse_solution(self):
        if self.milp_model is None or not self.milp_model.SolCount:
            return {}
        upper_trail = {}
        lower_trail = {}
        middle = {}
        for r in range(self.R0 + 1):
            upper_trail[f"x_{r}"] = self._bits(self.upper.generate_state_variables(r))
            if r < self.R0:
                ys, ls, rks, aks, zs = self.upper.generate_round_variables(r)
                upper_trail[f"y_{r}"] = self._bits(ys)
                upper_trail[f"l_{r}"] = self._bits(ls)
                upper_trail[f"rk_{r}"] = self._bits(rks)
                upper_trail[f"ak_{r}"] = self._bits(aks)
                upper_trail[f"z_{r}"] = self._bits(zs)
            else:
                for name in ("y", "l", "rk", "ak", "z"):
                    upper_trail[f"{name}_{r}"] = "none"
        for r in range(self.R1 + 1):
            lower_trail[f"x_{r}"] = self._bits(self.lower.generate_state_variables(r))
            if r < self.R1:
                ys, ls, rks, aks, zs = self.lower.generate_round_variables(r)
                lower_trail[f"y_{r}"] = self._bits(ys)
                lower_trail[f"l_{r}"] = self._bits(ls)
                lower_trail[f"rk_{r}"] = self._bits(rks)
                lower_trail[f"ak_{r}"] = self._bits(aks)
                lower_trail[f"z_{r}"] = self._bits(zs)
            else:
                for name in ("y", "l", "rk", "ak", "z"):
                    lower_trail[f"{name}_{r}"] = "none"
        upper_trail["mk"] = self._bits(self.upper.master_key_vars())
        lower_trail["mk"] = self._bits(self.lower.master_key_vars())
        for r in range(self.R0 + 1):
            upper_trail[f"ks_global_{r}"] = self._bits(self.upper.generate_key_state_variables(r))
            if r < self.R0:
                upper_trail[f"kc_global_{r}"] = self._bits(self.upper.generate_key_core_variables(r))
        for r in range(self.r0 + self.R1 + 1):
            lower_trail[f"ks_global_{r}"] = self._bits(self.lower.generate_key_state_variables(r))
            if r < self.r0 + self.R1:
                lower_trail[f"kc_global_{r}"] = self._bits(self.lower.generate_key_core_variables(r))
        common_count = 0
        common_state_count = 0
        common_key_count = 0
        for r in range(self.rm):
            names = self.generate_common_active_variables(r)
            vals = [self._var_value(name) for name in names]
            state_sum = sum(vals)
            common_state_count += state_sum
            common_count += state_sum
            middle[f"s_{r}"] = "".join(str(v) for v in vals)
            key_names = self.generate_common_key_active_variables(r)
            key_vals = [self._var_value(name) for name in key_names]
            key_sum = sum(key_vals)
            common_key_count += key_sum
            common_count += key_sum
            middle[f"ks_{r}"] = "".join(str(v) for v in key_vals)
        middle["common_active_sboxes"] = common_count
        middle["common_active_state_sboxes"] = common_state_count
        middle["common_active_key_sboxes"] = common_key_count
        middle["as"] = common_count
        middle["rk_mode"] = self.rk_mode
        return {"upper_trail": upper_trail, "middle_part": middle, "lower_trail": lower_trail}

    def parse_solver_output(self):
        parsed = self.parse_solution()
        self.upper_trail = parsed.get("upper_trail", {})
        self.middle_part = parsed.get("middle_part", {})
        self.lower_trail = parsed.get("lower_trail", {})
        print("\nUpper Related-Key Truncated Trail:\n")
        print("Rounds  x                 y         l         rk        ak        z        ")
        print("-" * 76)
        for r in range(self.R0 + 1):
            print(
                f"{r:<7} {self.upper_trail.get(f'x_{r}', ''):<17} "
                f"{self.upper_trail.get(f'y_{r}', 'none'):<9} "
                f"{self.upper_trail.get(f'l_{r}', 'none'):<9} "
                f"{self.upper_trail.get(f'rk_{r}', 'none'):<9} "
                f"{self.upper_trail.get(f'ak_{r}', 'none'):<9} "
                f"{self.upper_trail.get(f'z_{r}', 'none'):<9}"
            )
        print(f"Upper master-key activity: {self.upper_trail.get('mk', '')}")
        print("\n%s\n%s" % ("+" * 16, "#" * 16))
        print("Lower Related-Key Truncated Trail:\n")
        print("Rounds  x                 y         l         rk        ak        z        ")
        print("-" * 76)
        for r in range(self.R1 + 1):
            print(
                f"{r:<7} {self.lower_trail.get(f'x_{r}', ''):<17} "
                f"{self.lower_trail.get(f'y_{r}', 'none'):<9} "
                f"{self.lower_trail.get(f'l_{r}', 'none'):<9} "
                f"{self.lower_trail.get(f'rk_{r}', 'none'):<9} "
                f"{self.lower_trail.get(f'ak_{r}', 'none'):<9} "
                f"{self.lower_trail.get(f'z_{r}', 'none'):<9}"
            )
        print(f"Lower master-key activity: {self.lower_trail.get('mk', '')}")
        print("\n%s\n%s" % ("#" * 16, "#" * 16))
        print("Middle Part:\n")
        print("Round   state common                         key-schedule common")
        print("-" * 68)
        for r in range(self.rm):
            value = self.middle_part.get(f"s_{r}", "")
            key_value = self.middle_part.get(f"ks_{r}", "")
            if value:
                state_cols = "*".join(value[:8]) + "* " + "*".join(value[8:]) + "*"
            else:
                state_cols = ""
            key_cols = "*".join(key_value) + "*" if key_value else ""
            print(f"{r:<7} {state_cols:<37} {key_cols}")
        print(
            "\nNumber of common active S-boxes: "
            f"{self.middle_part.get('as', 0)} "
            f"(state={self.middle_part.get('common_active_state_sboxes', 0)}, "
            f"key={self.middle_part.get('common_active_key_sboxes', 0)})"
        )
        return self.upper_trail, self.middle_part, self.lower_trail

    def save_result(self, path):
        data = self.solution or {"lp_file": self.lp_file_name}
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        return data
