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
        self.last_solve_status = None
        self.exact_nogood_count = 0
        self._start_weight_constraint_added = False
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
        # 为nibble生成4个bit变量
        names = [f"{base}_{bit}" for bit in range(4)]
        self.milp_variables.extend(names)
        return names

    def state_variables(self, r):
        # 第r轮的状态变量
        return [self.nibble_bits(f"x_{r}_{n}") for n in range(self.state_size)]

    def key_state_variables(self, r):
        # 第r轮的密钥状态变量
        return [self.nibble_bits(f"ks_{r}_{n}") for n in range(self.key_size)]

    def round_variables(self, r):
        # 第r轮的中间状态变量, 32bits
        ys = [self.nibble_bits(f"y_{r}_{i}") for i in range(self.branch_size)]   # 第一轮 S 盒输出 8-nibble = 32-bit
        ls = [self.nibble_bits(f"l_{r}_{i}") for i in range(self.branch_size)]   # 线性层输出 8-nibble = 32-bit
        rks = [self.nibble_bits(f"rk_{r}_{i}") for i in range(self.branch_size)] # 轮密钥
        aks = [self.nibble_bits(f"ak_{r}_{i}") for i in range(self.branch_size)] # XOR轮密钥输出
        zs = [self.nibble_bits(f"z_{r}_{i}") for i in range(self.branch_size)]   # 第一轮 S 盒输出 
        return ys, ls, rks, aks, zs

    def key_core_variables(self, r, k0):
        """Return the eight-nibble key-core output without copying linear nibbles."""
        core = list(k0)
        for i in self.key_sbox_positions:
            core[i] = self.nibble_bits(f"kc_{r}_{i}") # 只有2个经过sbox
        return core

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
        # 多个nibble的XOR
        if len(inputs) == 1:
            return self.eq_bits(inputs[0], output)
        constraints = []
        acc = inputs[0]
        for idx, item in enumerate(inputs[1:], start=1):
            # 去除对应 index 和 对应值
            # 若最后一个就 =output, 否则增加中间变量存储XOR值
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
        # Earlier key-schedule rounds remain constrained for a valid master-key
        # witness, but a lower trail's objective only counts E1 key S-boxes.
        in_objective = not (
            tag is not None
            and tag[1] == "key"
            and tag[0] < self.round_offset
        )
        if in_objective:
            self.weight_terms.extend((1, var) for var in pr)
        self.sbox_probability_groups.append(
            {"tag": tag, "pr": pr, "in_objective": in_objective}
        )
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
        # Sbox的不等式约束
        pr = self.probability_variables(tag)
        return self.constraints_by_sbox(sbox_in, sbox_out, pr)

    def generate_linear_layer_constraints(self, r):
        '''
        ls[0] = ls[3] XOR ys[3]
        ls[1] = ys[0]
        ls[2] = ys[1] XOR ys[2]
        ls[3] = ys[0] XOR ys[2]
        '''
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
            k0 = kin[:8]
            k1 = kin[8:16]
            k2 = kin[16:24]
            k3 = kin[24:32]
            core = self.key_core_variables(r, k0)
            for i in range(self.branch_size):
                if i in self.key_sbox_positions:
                    constraints.extend(self.generate_sbox_constraints(k0[i], core[i], tag=(r, "key", i)))
            rotated = [core[(i + self.key_shift) % self.branch_size] for i in range(self.branch_size)] #循环移位1-nibble
            for i in range(self.branch_size):
                constraints.extend(self.xor_nibble(rotated[i], k1[i], kout[i]))
                constraints.extend(self.eq_bits(k2[i], kout[8 + i]))
                constraints.extend(self.eq_bits(k3[i], kout[16 + i]))
                constraints.extend(self.eq_bits(k0[i], kout[24 + i]))
        return constraints

    def generate_round_key_constraints(self, r):
        # 单独将rk作为变量
        _, _, rks, _, _ = self.round_variables(r)
        key_after_update = self.key_state_variables(self.round_offset + r + 1)
        constraints = []
        for i in range(self.branch_size):
            constraints.extend(self.eq_bits(rks[i], key_after_update[i]))
        return constraints

    def generate_round_constraints(self, r):
        '''
        ============================================================

        左半 L (x_in[0:8])          |        右半 R (x_in[8:16])
        ─────────────────────────────┼─────────────────────────────
                x_in[i]              |          x_in[8+i]
                │                    |               │
                ▼  S盒               |               │
                ys[i]                |               │
                │                    |               │
                ▼  线性层P置换        |               │
                ls[i]                |               │
                │                    |               │
                ▼  XOR 轮密钥 rks[i] |               │
                aks[i]               |               │
                │                    |               │
                ▼  S盒               |               │
                zs[i]                |               │
                │            右半 R (x_in[8:16])     │
                │  移位后            |               │
                └───────────⊕───────┘               │
                            │                        │
                            ▼                        │
                        x_out[out_idx]               │
                        (新左半 L')                  │
                                                     │
                x_in[i] ─────────────────────────────┘
                │   直接复制到右半
                ▼
            x_out[8+i] (新右半 R')
        ============================================================
        '''
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

    def _named_nibble_variables(self, kind, r):
        """Resolve one concrete-difference variable family to nibble bits."""
        if kind == "x":
            return self.state_variables(r)
        if kind in ("k", "ks"):
            return self.key_state_variables(r)
        if kind in ("y", "l", "rk", "ak", "z"):
            ys, ls, rks, aks, zs = self.round_variables(r)
            return {
                "y": ys,
                "l": ls,
                "rk": rks,
                "ak": aks,
                "z": zs,
            }[kind]
        if kind == "kc":
            k0 = self.key_state_variables(r)[:self.branch_size]
            return self.key_core_variables(r, k0)
        raise ValueError(f"unsupported concrete variable family: {kind}")

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
            elif len(parts) == 3 and parts[0] in ("x", "k", "ks", "y", "l", "rk", "ak", "z", "kc"):
                bits = nibble_to_bits(int(value, 16) if isinstance(value, str) else int(value))
                nibble = self._named_nibble_variables(parts[0], int(parts[1]))[int(parts[2])]
                constraints.extend(f"{var} = {bit}" for var, bit in zip(nibble, bits))
            elif len(parts) == 4:
                constraints.append(f"{name} = {int(value)}")
        return constraints

    def declare_nonzero_variables(self):
        constraints = []
        for name in self.nonzero_variables:
            parts = name.split("_")
            if len(parts) == 3 and parts[0] in ("x", "k", "ks", "y", "l", "rk", "ak", "z", "kc"):
                variables = self._named_nibble_variables(parts[0], int(parts[1]))
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

    @staticmethod
    def _xor_hex(left, right):
        if len(left) != len(right):
            raise ValueError("hexadecimal XOR operands must have equal length")
        return f"{int(left, 16) ^ int(right, 16):0{len(left)}X}"

    @staticmethod
    def _rotate_right_hex(value, amount):
        amount %= len(value)
        return value[-amount:] + value[:-amount] if amount else value

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
                key_w = self._round_weight(self.round_offset + r, "key")
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

    def _key_schedule_fixed_diffs(self, characteristic):
        """Export every modeled key-schedule difference to canonical SMT names."""
        fixed = {}
        max_key_round = self.round_offset + self.nrounds
        for g in range(max_key_round + 1):
            fixed[f"dKSG{g}"] = characteristic[f"ks_global_{g}"]

        for g in range(max_key_round):
            ks_in = characteristic[f"ks_global_{g}"]
            ks_out = characteristic[f"ks_global_{g + 1}"]
            k0 = ks_in[:8]
            k1 = ks_in[8:16]
            new_k0 = ks_out[:8]

            # new_k0 = SHI1(S_key(k0)) xor k1; round constants cancel in
            # differences.  This recovers the key-core differential exactly.
            kcore = self._xor_hex(new_k0, k1)
            transformed = self._rotate_right_hex(kcore, self.key_shift)
            ksin = "".join(k0[i] if i in self.key_sbox_positions else "0" for i in range(8))
            ksout = "".join(
                transformed[i] if i in self.key_sbox_positions else "0"
                for i in range(8)
            )
            fixed[f"dKSGIN{g}"] = ksin
            fixed[f"dKSGOUT{g}"] = ksout
            fixed[f"dKSGCORE{g}"] = kcore
        return fixed

    def build_exact_verify_trail(self, characteristic):
        """Translate an RKDiff characteristic to rk_exact_verify's format."""
        fixed = {"dK": characteristic["master_key_diff"]}
        fixed.update(self._key_schedule_fixed_diffs(characteristic))

        for r in range(self.nrounds + 1):
            fixed[f"dX{r}"] = characteristic[f"x_{r}"]
            fixed[f"dKS{r}"] = characteristic[f"ks_global_{self.round_offset + r}"]

        for r in range(self.nrounds):
            fixed[f"dROUNDKS{r}"] = characteristic[f"round_ks_{r}"]
            fixed[f"dRK{r}"] = characteristic[f"rk_{r}"]
            fixed[f"dY{r}"] = characteristic[f"y_{r}"]
            fixed[f"dLIN{r}"] = characteristic[f"l_{r}"]
            fixed[f"dAK{r}"] = characteristic[f"ak_{r}"]
            fixed[f"dZ{r}"] = characteristic[f"z_{r}"]

            # FXOR and SHI are strictly determined by the modeled next state,
            # but exporting them makes the exact characteristic explicit.
            shi = characteristic[f"x_{r + 1}"][:8]
            fixed[f"dSHI{r}"] = shi
            fixed[f"dFXOR{r}"] = self._rotate_right_hex(shi, self.shift_nibbles)

            absolute_round = self.round_offset + r
            fixed[f"dKSIN{r}"] = fixed[f"dKSGIN{absolute_round}"]
            fixed[f"dKSOUT{r}"] = fixed[f"dKSGOUT{absolute_round}"]
            fixed[f"dKCORE{r}"] = fixed[f"dKSGCORE{absolute_round}"]

        return {
            "rounds": self.nrounds,
            "round_offset": self.round_offset,
            "fixed_diffs": fixed,
        }

    @staticmethod
    def _is_concrete_difference_bit_name(name):
        parts = name.split("_")
        return (
            len(parts) == 4
            and parts[0] in {"x", "ks", "y", "l", "rk", "ak", "z", "kc"}
            and all(part.isdigit() for part in parts[1:])
        )

    def concrete_solution_signature(self):
        """Return the full concrete differential bit assignment of this solution."""
        if self.milp_model is None or not self.milp_model.SolCount:
            raise RuntimeError("no current Gurobi solution is available")

        assignment = []
        for var in sorted(self.milp_model.getVars(), key=lambda item: item.VarName):
            if not self._is_concrete_difference_bit_name(var.VarName):
                continue
            value = int(round(var.X))
            if value not in (0, 1) or abs(var.X - value) > 1e-5:
                raise RuntimeError(
                    f"non-binary value {var.X!r} for concrete variable {var.VarName}"
                )
            assignment.append((var.VarName, value))
        if not assignment:
            raise RuntimeError("the concrete trail signature is empty")
        return assignment

    def extract_solution_for_exact_verify(self):
        """Extract the current trail, full no-good signature, and objective value."""
        characteristic = self.parse_solver_output()
        return {
            "trail": self.build_exact_verify_trail(characteristic),
            "characteristic": characteristic,
            "nogood_assignment": self.concrete_solution_signature(),
            "weight": float(self.total_weight),
        }

    def add_solution_nogood(
        self,
        solution,
        scope="trail",
        candidate_id=None,
        constraint_name=None,
    ):
        """Block exactly one full concrete differential assignment.

        This does not mark any local DDT transition as invalid.  The next
        solution only has to differ in at least one concrete difference bit.
        """
        if self.milp_model is None:
            raise RuntimeError("the Gurobi model has not been loaded")
        assignment = solution.get("nogood_assignment", solution)
        if not assignment:
            raise ValueError("cannot add an empty full-trail no-good")

        terms = []
        for var_name, value in assignment:
            var = self.milp_model.getVarByName(var_name)
            if var is None:
                raise ValueError(f"unknown Gurobi variable in no-good: {var_name}")
            if value == 0:
                terms.append(var)
            elif value == 1:
                terms.append(1 - var)
            else:
                raise ValueError(f"invalid binary value in no-good: {value}")

        self.exact_nogood_count += 1
        number = candidate_id if candidate_id is not None else self.exact_nogood_count
        name = constraint_name or f"exact_nogood_{scope}_{int(number):04d}"
        self.milp_model.addConstr(quicksum(terms) >= 1, name=name)
        self.milp_model.update()
        return name

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
        self._start_weight_constraint_added = False
        self.exact_nogood_count = 0
        return self.milp_model

    def optimize_next_candidate(self, output_flag=False, time_limit_override=None):
        """Optimize the unchanged RKDiff weight objective on the current model."""
        if self.milp_model is None:
            self.load_model()
        self.milp_model.Params.OutputFlag = bool(output_flag)
        effective_time_limit = (
            time_limit_override
            if time_limit_override is not None
            else self.time_limit
        )
        if effective_time_limit is not None:
            self.milp_model.Params.TimeLimit = max(float(effective_time_limit), 1e-3)
        if self.start_weight is not None and not self._start_weight_constraint_added:
            self.milp_model.addConstr(
                self.milp_model.getObjective() >= self.start_weight,
                "start_weight_constraint",
            )
            self._start_weight_constraint_added = True

        started = time.perf_counter()
        self.milp_model.optimize()
        elapsed_seconds = time.perf_counter() - started
        self.last_solve_status = self._gurobi_status_name(self.milp_model.Status)
        if not self.milp_model.SolCount:
            return {
                "status": self.last_solve_status,
                "trail": None,
                "weight": None,
                "elapsed_seconds": elapsed_seconds,
            }

        self.total_weight = float(self.milp_model.ObjVal)
        return {
            "status": self.last_solve_status,
            "trail": self.parse_solver_output(),
            "weight": self.total_weight,
            "elapsed_seconds": elapsed_seconds,
        }

    def find_characteristic(self, deadline=None, time_limit_override=None):
        self.milp_model.Params.OutputFlag = False

        def apply_remaining_time_limit():
            limit = (
                time_limit_override
                if time_limit_override is not None
                else self.time_limit
            )
            if deadline is not None:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    return False
                limit = remaining if limit is None else min(float(limit), remaining)
            if limit is not None:
                self.milp_model.Params.TimeLimit = max(float(limit), 1e-3)
            return True

        if not apply_remaining_time_limit():
            print("Global solving time limit reached before RKDiff optimization")
            return None
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
                if apply_remaining_time_limit():
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

    def solve(self, deadline=None, time_limit_override=None):
        self.load_model()
        if self.mode == 0:
            return self.find_characteristic(
                deadline=deadline,
                time_limit_override=time_limit_override,
            )
        print("Only mode 0 is currently implemented for RKDiff.")
        return None

    def solve_and_save(self, output_path):
        trail = self.solve()
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(trail, handle, indent=2)
        return trail
