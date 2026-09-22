"""Text, Markdown, and TikZ-style formatting helpers for Splight-RK results."""

import json

from splight.splight_spec import SBOX_SPLIGHT_S3


def mask_to_concrete_hex(mask):
    return "".join("1" if ch != "0" else "0" for ch in mask).upper()


def load_result(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def ascii_trails(result):
    sol = result.get("truncated_search", {}).get("solution", result)
    lines = ["上路径："]
    for key, value in sol.get("upper_trail", {}).items():
        lines.append(f"  {key}: {value}")
    lines.append("中间 common active S-box：")
    for key, value in sol.get("middle_part", {}).items():
        lines.append(f"  {key}: {value}")
    lines.append("下路径：")
    for key, value in sol.get("lower_trail", {}).items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def save_ascii(result_path, output_path):
    text = ascii_trails(load_result(result_path))
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
    return text


def _state_table(trail, nrounds):
    rows = [
        "| 轮数 | x | y | l | RK | ak | z |",
        "|---:|---|---|---|---|---|---|",
    ]
    for r in range(nrounds + 1):
        rows.append(
            f"| {r} | `{trail.get(f'x_{r}', 'none')}` | `{trail.get(f'y_{r}', 'none')}` | "
            f"`{trail.get(f'l_{r}', 'none')}` | `{trail.get(f'rk_{r}', 'none')}` | "
            f"`{trail.get(f'ak_{r}', 'none')}` | `{trail.get(f'z_{r}', 'none')}` |"
        )
    return "\n".join(rows)


def _diff_table(trail):
    nrounds = int(trail["nrounds"])
    round_offset = int(trail.get("round_offset", 0))
    rows = [
        "| Rounds | x | y | l | RK | ak | z | KS | pr | rw | kw |",
        "|---:|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in range(nrounds + 1):
        ks = trail.get(
            f"round_ks_{r}",
            trail.get(f"ks_global_{round_offset + r + 1}", "none") if r < nrounds else "none",
        )
        rows.append(
            f"| {r} | `{trail.get(f'x_{r}', 'none')}` | `{trail.get(f'y_{r}', 'none')}` | "
            f"`{trail.get(f'l_{r}', 'none')}` | `{trail.get(f'rk_{r}', 'none')}` | "
            f"`{trail.get(f'ak_{r}', 'none')}` | `{trail.get(f'z_{r}', 'none')}` | "
            f"`{ks}` | `{trail.get(f'pr_{r}', 'none')}` | "
            f"`{trail.get(f'rw_{r}', 'none')}` | `{trail.get(f'kw_{r}', 'none')}` |"
        )
    rows.append("")
    rows.append(f"- 主密钥输入差分：`{trail.get('master_key_diff', 'none')}`")
    rows.append(f"- Weight：`-{trail.get('total_weight', '0')}`")
    return "\n".join(rows)


def _xor_hex(a, b, width):
    return f"{(int(a, 16) ^ int(b, 16)):0{width}X}"


def _ddt_count(a, b):
    return sum(1 for x in range(16) if SBOX_SPLIGHT_S3[x] ^ SBOX_SPLIGHT_S3[x ^ a] == b)


def _ddt_weight(a, b):
    count = _ddt_count(a, b)
    if count == 16:
        return 0
    if count == 4:
        return 2
    if count == 2:
        return 3
    if count == 0:
        return "invalid"
    return f"log2(16/{count})"


def _split_key_state(ks):
    return {
        "k0": ks[0:8],
        "k1": ks[8:16],
        "k2": ks[16:24],
        "k3": ks[24:32],
    }


def _key_schedule_round(trail, global_round):
    kin = str(trail[f"ks_global_{global_round}"]).upper()
    kout = str(trail[f"ks_global_{global_round + 1}"]).upper()
    branches = _split_key_state(kin)
    out_branches = _split_key_state(kout)
    k0 = branches["k0"]
    k1 = branches["k1"]

    new_k0 = out_branches["k0"]
    rotated_core = _xor_hex(new_k0, k1, 8)
    core = rotated_core[-1:] + rotated_core[:-1]
    sbox_in = "".join(k0[i] if i in (3, 7) else "0" for i in range(8))
    sbox_out = "".join(core[i] if i in (3, 7) else "0" for i in range(8))

    details = {}
    total_weight = 0
    for pos in (3, 7):
        a = int(k0[pos], 16)
        b = int(core[pos], 16)
        weight = _ddt_weight(a, b)
        details[str(pos)] = {
            "input": f"{a:X}",
            "output": f"{b:X}",
            "ddt_count": _ddt_count(a, b),
            "weight": weight,
        }
        if isinstance(weight, int):
            total_weight += weight

    return {
        "round": global_round,
        "ks_in": kin,
        "k0": branches["k0"],
        "k1": branches["k1"],
        "k2": branches["k2"],
        "k3": branches["k3"],
        "sbox_in": sbox_in,
        "sbox_out": sbox_out,
        "core": core,
        "rot_core": rotated_core,
        "const_diff": "00000000",
        "new_k0": new_k0,
        "new_k1": out_branches["k1"],
        "new_k2": out_branches["k2"],
        "new_k3": out_branches["k3"],
        "ks_out": kout,
        "kw": f"-{total_weight}",
        "sbox_details": details,
    }


def _key_schedule_rounds(trail):
    rounds = []
    r = 0
    while f"ks_global_{r}" in trail and f"ks_global_{r + 1}" in trail:
        rounds.append(_key_schedule_round(trail, r))
        r += 1
    return rounds


def _key_schedule_diff_table(title, trail):
    if trail is None:
        return f"### {title}\n\n未生成具体相关密钥差分路径。"
    rows = _key_schedule_rounds(trail)
    headers = [
        "r",
        "ks_in",
        "k0",
        "k1",
        "k2",
        "k3",
        "sbox_in",
        "sbox_out",
        "core",
        "rot_core",
        "C",
        "new_k0/RK",
        "new_k1",
        "new_k2",
        "new_k3",
        "ks_out",
        "kw",
    ]
    mapping = {
        "r": "round",
        "C": "const_diff",
        "new_k0/RK": "new_k0",
    }
    lines = [
        f"### {title}",
        "",
        f"- `round_offset`: `{trail.get('round_offset', 0)}`",
        f"- `nrounds`: `{trail.get('nrounds', 0)}`",
        f"- `master_key_diff`: `{trail.get('master_key_diff', 'none')}`",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" if header != "r" else "---:" for header in headers) + " |",
    ]
    for row in rows:
        cells = []
        for header in headers:
            key = mapping.get(header, header)
            cells.append(f"`{row[key]}`")
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend([
        "",
        "S-box DDT 细节：",
        "",
        "| r | pos | input | output | DDT count | weight |",
        "|---:|---:|---|---|---:|---|",
    ])
    for row in rows:
        for pos in ("3", "7"):
            item = row["sbox_details"][pos]
            lines.append(
                f"| {row['round']} | {pos} | `{item['input']}` | `{item['output']}` | "
                f"{item['ddt_count']} | `{item['weight']}` |"
            )
    return "\n".join(lines)


def _key_schedule_supplement(result):
    return "\n\n".join([
        "## 密钥调度差分状态补充",
        "下面两张表分别展开 upper keydiff 与 lower keydiff 的每轮密钥调度差分状态。"
        "`C` 是轮常数差分，恒为 `00000000`；`new_k0/RK` 是该轮更新后用于加密的 32-bit 轮密钥差分，"
        "`ks_out = new_k0 || new_k1 || new_k2 || new_k3`。",
        _key_schedule_diff_table("Upper keydiff", result.get("diff_upper_trail")),
        _key_schedule_diff_table("Lower keydiff", result.get("diff_lower_trail")),
    ])


def mermaid_distinguisher(result):
    params = result["parameters"]
    r0, rm, r1 = params["r0"], params["rm"], params["r1"]
    du = result.get("diff_upper_trail") or {}
    dl = result.get("diff_lower_trail") or {}
    middle = result.get("middle_part") or {}
    delta = du.get(f"x_{r0}") or mask_to_concrete_hex(result["upper_trail"].get(f"x_{r0}", ""))
    nabla = dl.get("x_0") or mask_to_concrete_hex(result["lower_trail"].get("x_0", ""))
    input_diff = du.get("x_0") or delta
    output_diff = dl.get(f"x_{r1}") or nabla
    return "\n".join([
        "```mermaid",
        "flowchart LR",
        f'  P["输入差分\\n{input_diff}"] --> E0["E0：{r0} 轮\\n上差分路径"]',
        f'  E0 --> D["进入 Em 的 Delta\\n{delta}"]',
        f'  D --> EM["Em：{rm} 轮\\nCAS={middle.get("as", "unknown")}"]',
        f'  EM --> N["Em 输出端的 nabla\\n{nabla}"]',
        f'  N --> E1["E1：{r1} 轮\\n下差分路径"]',
        f'  E1 --> C["输出差分\\n{output_diff}"]',
        "```",
    ])


def probability_estimate_lines(result):
    """Return the same theoretical probability summary printed by rkboom.py."""
    upper_effect = float(result.get("diff_effect_upper_log2", 0))
    lower_effect = float(result.get("diff_effect_lower_log2", 0))
    common_active = float((result.get("middle_part") or {}).get("as", 0))
    total_weight = 2.0 * upper_effect + 2.0 * lower_effect
    lower_bound = total_weight - 2.5 * common_active
    upper_bound = total_weight - 2.0 * common_active

    lines = []
    if upper_effect != 0:
        lines.append(
            f"differential effect of the upper trail: 2^({upper_effect:.2f})"
        )
    if lower_effect != 0:
        lines.append(
            f"differential effect of the lower trail: 2^({lower_effect:.2f})"
        )
    lines.extend([
        "Total probability = p^2*q^2*r = "
        f"2^({2.0 * upper_effect:.2f}) x 2^({2.0 * lower_effect:.2f}) x r",
        f"2^({lower_bound:.2f}) <= Total probability <= 2^({upper_bound:.2f})",
        "To compute the accurate value of total probability, r should be evaluated "
        "experimentally or using the (F)BCT framework",
    ])
    return lines


def markdown_distinguisher(result):
    params = result["parameters"]
    r0, rm, r1 = params["r0"], params["rm"], params["r1"]
    lines = [
        f"# Splight-RK 区分器 r0={r0}, rm={rm}, r1={r1}",
        "",
        "## Boomerang 概率预估",
        "",
        "```text",
        *probability_estimate_lines(result),
        "```",
        "",
        mermaid_distinguisher(result),
        "",
        "## 上截断路径",
        "",
        _state_table(result["upper_trail"], r0 + rm),
        "",
        "## 中间 common active S-box",
        "",
        f"common active S-box 数量：`{result['middle_part'].get('as', 'unknown')}`",
        "",
    ]
    for key in sorted(k for k in result["middle_part"] if k.startswith("s_") or k.startswith("ks_")):
        lines.append(f"- `{key}`: `{result['middle_part'][key]}`")
    lines.extend([
        "",
        "## 下截断路径",
        "",
        _state_table(result["lower_trail"], rm + r1),
        "",
        "## 上具体相关密钥差分路径（E0）",
        "",
        (
            _diff_table(result["diff_upper_trail"])
            if result.get("diff_upper_trail") is not None
            else "无 E0 具体差分路径；使用上截断边界 active mask 映射为 Em 的 Delta。"
        ),
        "",
        "## 下具体相关密钥差分路径（E1）",
        "",
        (
            _diff_table(result["diff_lower_trail"])
            if result.get("diff_lower_trail") is not None
            else "无 E1 具体差分路径；使用下截断边界 active mask 映射为 Em 的 nabla。"
        ),
        "",
        _key_schedule_supplement(result),
        "",
    ])
    return "\n".join(lines)


def save_markdown_distinguisher(result_path, output_path):
    result = load_result(result_path)
    text = markdown_distinguisher(result)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return text


def tex_init():
    return "% Hadipour style Splight-RK distinguisher\n"


def tex_fin(nrounds):
    return f"% {nrounds} rounds Splight-RK distinguisher end\n"


def tex_middle(upper_trail, midd_trail, lower_trail, r0, rm, r1):
    lines = [
        "% Truncated boomerang middle summary",
        f"% r0={r0}, rm={rm}, r1={r1}",
        "% upper trail",
    ]
    for key, value in upper_trail.items():
        lines.append(f"% {key}: {value}")
    lines.append("% middle common active S-box")
    for key, value in midd_trail.items():
        lines.append(f"% {key}: {value}")
    lines.append("% lower trail")
    for key, value in lower_trail.items():
        lines.append(f"% {key}: {value}")
    return "\n".join(lines) + "\n"


def tikz_mark_input_bits(active_input_bits, color="red"):
    return f"% input active bits {active_input_bits}, color={color}\n"


def tikz_mark_output_bits(active_output_bits, color="blue"):
    return f"% output active bits {active_output_bits}, color={color}\n"


def tex_diff_trail(trail, markpattern="markupperpath", direction="->"):
    return f"% differential trail {markpattern} {direction}: {trail}\n"


def tex_diff_lower_trail(trail, upper_crossing_difference=None, markpattern="marklowerpath", direction="<-"):
    return f"% lower differential trail {markpattern} {direction}: {trail}\n"
