#!/usr/bin/env python3
"""Add detailed key-schedule difference tables to the existing 7-4-3 result."""

import json
from pathlib import Path
import sys


BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))
from splight.splight_spec import SBOX_SPLIGHT_S3


RESULT_DIR = BASE_DIR / "results" / "7-4-3"
JSON_DIR = RESULT_DIR / ".json"
RESULT_JSON = JSON_DIR / "7-4-3.json"


def xor_hex(a, b, width):
    return f"{(int(a, 16) ^ int(b, 16)):0{width}X}"


def rot_left_1(s):
    return s[1:] + s[:1]


def ddt_count(a, b):
    count = 0
    for x in range(16):
        if SBOX_SPLIGHT_S3[x] ^ SBOX_SPLIGHT_S3[x ^ a] == b:
            count += 1
    return count


def ddt_weight(a, b):
    count = ddt_count(a, b)
    if count == 16:
        return 0
    if count == 4:
        return 2
    if count == 2:
        return 3
    if count == 0:
        return "invalid"
    return f"log2(16/{count})"


def split_key_state(ks):
    return {
        "k0": ks[0:8],
        "k1": ks[8:16],
        "k2": ks[16:24],
        "k3": ks[24:32],
    }


def derive_key_round(trail, global_round):
    kin = trail[f"ks_global_{global_round}"].upper()
    kout = trail[f"ks_global_{global_round + 1}"].upper()
    branches = split_key_state(kin)
    out_branches = split_key_state(kout)
    k0 = branches["k0"]
    k1 = branches["k1"]
    rk = out_branches["k0"]

    # rk[j] = rotated_core[j] xor k1[j], constants have zero difference.
    core_rot = xor_hex(rk, k1, 8)
    # rotated_core[j] = core[(j+1) mod 8].
    core = core_rot[-1:] + core_rot[:-1]
    sbox_out = "".join(core[i] if i in (3, 7) else "0" for i in range(8))
    sbox_in = "".join(k0[i] if i in (3, 7) else "0" for i in range(8))

    by_pos = {}
    total_weight = 0
    for pos in (3, 7):
        a = int(k0[pos], 16)
        b = int(core[pos], 16)
        weight = ddt_weight(a, b)
        by_pos[str(pos)] = {
            "input": f"{a:X}",
            "output": f"{b:X}",
            "ddt_count": ddt_count(a, b),
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
        "rot_core": core_rot,
        "const_diff": "00000000",
        "new_k0": rk,
        "new_k1": out_branches["k1"],
        "new_k2": out_branches["k2"],
        "new_k3": out_branches["k3"],
        "ks_out": kout,
        "round_ks": rk,
        "sbox_details": by_pos,
        "kw": f"-{total_weight}",
    }


def available_key_rounds(trail):
    rounds = []
    index = 0
    while f"ks_global_{index}" in trail and f"ks_global_{index + 1}" in trail:
        rounds.append(index)
        index += 1
    return rounds


def build_key_schedule_details(label, trail):
    rows = [derive_key_round(trail, r) for r in available_key_rounds(trail)]
    return {
        "label": label,
        "round_offset": int(trail.get("round_offset", 0)),
        "nrounds": int(trail.get("nrounds", 0)),
        "master_key_diff": trail.get("master_key_diff"),
        "rows": rows,
    }


def format_rows(section):
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
    key_map = {
        "r": "round",
        "C": "const_diff",
        "new_k0/RK": "new_k0",
    }
    widths = {header: len(header) for header in headers}
    for row in section["rows"]:
        for header in headers:
            key = key_map.get(header, header)
            widths[header] = max(widths[header], len(str(row[key])))

    lines = [
        f"{section['label']} key schedule difference variables",
        f"round_offset = {section['round_offset']}, nrounds = {section['nrounds']}",
        f"master_key_diff = {section['master_key_diff']}",
        "",
        "  ".join(header.ljust(widths[header]) for header in headers),
        "-" * sum(widths.values()) + "-" * (2 * (len(headers) - 1)),
    ]
    for row in section["rows"]:
        cells = []
        for header in headers:
            key = key_map.get(header, header)
            cells.append(str(row[key]).ljust(widths[header]))
        lines.append("  ".join(cells))

    lines.extend([
        "",
        "S-box details:",
        "r      pos  input  output  ddt_count  weight",
        "----------------------------------------------",
    ])
    for row in section["rows"]:
        for pos in ("3", "7"):
            item = row["sbox_details"][pos]
            lines.append(
                f"{row['round']:<6} {pos:<4} {item['input']:<6} "
                f"{item['output']:<7} {item['ddt_count']:<10} {item['weight']}"
            )
    return lines


def append_or_replace_section(text, marker, section_text):
    start = text.find(marker)
    if start == -1:
        return text.rstrip() + "\n\n" + section_text.rstrip() + "\n"
    return text[:start].rstrip() + "\n\n" + section_text.rstrip() + "\n"


def main():
    result = json.loads(RESULT_JSON.read_text(encoding="utf-8"))
    upper = result["diff_upper_trail"]
    lower = result["diff_lower_trail"]
    details = {
        "upper": build_key_schedule_details("Upper differential trail", upper),
        "lower": build_key_schedule_details("Lower differential trail", lower),
    }

    JSON_DIR.mkdir(parents=True, exist_ok=True)
    (JSON_DIR / "key_schedule_variables_7-4-3.json").write_text(
        json.dumps(details, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    marker = "Detailed key schedule difference variables:"
    lines = [marker, ""]
    lines.extend(format_rows(details["upper"]))
    lines.extend(["", ""])
    lines.extend(format_rows(details["lower"]))
    text = "\n".join(lines) + "\n"
    (RESULT_DIR / "key_schedule_variables.txt").write_text(text, encoding="utf-8")

    main_txt = RESULT_DIR / "7-4-3.txt"
    existing = main_txt.read_text(encoding="utf-8")
    main_txt.write_text(append_or_replace_section(existing, marker, text), encoding="utf-8")
    print(RESULT_DIR / "key_schedule_variables.txt")
    print(JSON_DIR / "key_schedule_variables_7-4-3.json")


if __name__ == "__main__":
    main()
