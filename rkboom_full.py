#!/usr/bin/env python3

"""Instantiate E0+Em and Em+E1 related-key boomerang spans for Splight.

This entry keeps rkboom.py unchanged.  The truncated Hadipour sandwich search is
still performed first, but concrete RK differentials are instantiated over the
two long overlapping spans:

    upper span: E0 + Em, rounds 0 .. r0+rm
    lower span: Em + E1, rounds r0 .. r0+rm+r1
"""

from argparse import ArgumentParser, RawTextHelpFormatter
import json
import os
import traceback

import yaml

from rkboom import _tee_terminal_output, result_case_dir_name
from rkdiff import RKDiff
from rktruncboom import RKTruncatedBoomerang


def loadparameters(args):
    params = {
        "inputfile": "./input.yaml",
        "r0": 2,
        "rm": 2,
        "r1": 2,
        "w0": 6,
        "wm": 3,
        "w1": 6,
        "timelimit": 1200,
        "numofsols": 1,
        "rk_mode": "rk-ladder",
    }
    if args.inputfile:
        with open(args.inputfile, "r", encoding="utf-8") as input_file:
            doc = yaml.load(input_file, Loader=yaml.FullLoader)
            params.update(doc)
        params["inputfile"] = args.inputfile
    for key in ("r0", "rm", "r1", "w0", "wm", "w1", "timelimit", "numofsols", "rk_mode"):
        value = getattr(args, key, None)
        if value is not None:
            params[key] = value
    return params


def apply_truncated_state_mask(diff_params, local_round, mask):
    for nibble, flag in enumerate(mask):
        if flag == "0":
            for bit in range(4):
                diff_params["fixedVariables"][f"x_{local_round}_{nibble}_{bit}"] = "0"
        else:
            diff_params["nonzeroVariables"].append(f"x_{local_round}_{nibble}")


def make_diff_params(nrounds, round_offset, params):
    return {
        "nrounds": nrounds,
        "mode": 0,
        "startweight": 0,
        "endweight": 256,
        "timelimit": params.get("timelimit", 18000),
        "numberoftrails": 1,
        "round_offset": round_offset,
        "rk_mode": params.get("rk_mode", "rk-ladder"),
        "fixedVariables": {},
        "nonzeroVariables": [],
    }


def solve_span(name, diff_params):
    diff = RKDiff(diff_params)
    diff.make_model()
    trail = diff.solve()
    if trail is None:
        print(f"{name} span concrete RK differential was not found")
    return trail


def hx(value):
    if value in (None, "", "none"):
        return "none"
    return "0x" + str(value).upper()


def weight_value(value):
    if value in (None, "", "none"):
        return None
    return -float(str(value).lstrip("-"))


def fmt_weight(value):
    if value is None:
        return "none"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}"


def span_round(trail, local_round, nrounds):
    if trail is None or local_round < 0 or local_round > nrounds:
        return None
    if local_round < nrounds:
        row_ks = trail.get(
            f"round_ks_{local_round}",
            trail.get(f"ks_global_{local_round + trail.get('round_offset', 0) + 1}"),
        )
    else:
        row_ks = "none"
    row = {"x": trail.get(f"x_{local_round}"), "ks": row_ks}
    if local_round < nrounds:
        row.update({
            "p": trail.get(f"y_{local_round}"),
            "s": trail.get(f"l_{local_round}"),
            "y": trail.get(f"z_{local_round}"),
            "rk": trail.get(f"rk_{local_round}"),
            "w": weight_value(trail.get(f"pr_{local_round}")),
        })
    else:
        row.update({"p": None, "s": None, "y": None, "rk": None, "w": None})
    return row


def combined_weight(global_round, upper_row, lower_row, r0, rm):
    return None


def common_active_at(middle_part, em_round):
    value = middle_part.get(f"s_{em_round}", "")
    return sum(1 for ch in value if ch == "1")


def build_combined_rows(upper_span, lower_span, middle_part, r0, rm, r1):
    total_rounds = r0 + rm + r1
    upper_rounds = r0 + rm
    lower_rounds = rm + r1
    rows = []
    for r in range(total_rounds + 1):
        upper_row = span_round(upper_span, r, upper_rounds) if r <= upper_rounds else None
        lower_local = r - r0
        lower_row = span_round(lower_span, lower_local, lower_rounds) if 0 <= lower_local <= lower_rounds else None
        w = common_active_at(middle_part, r - r0) if r0 <= r < r0 + rm else None
        rows.append({
            "round": r,
            "Xu": hx(upper_row["x"] if upper_row else None),
            "Pu": hx(upper_row["p"] if upper_row else None),
            "Su": hx(upper_row["s"] if upper_row else None),
            "Yu": hx(upper_row["y"] if upper_row else None),
            "Xl": hx(lower_row["x"] if lower_row else None),
            "Pl": hx(lower_row["p"] if lower_row else None),
            "Sl": hx(lower_row["s"] if lower_row else None),
            "Yl": hx(lower_row["y"] if lower_row else None),
            "wu": fmt_weight(upper_row["w"] if upper_row else None),
            "wl": fmt_weight(lower_row["w"] if lower_row else None),
            "w": "none" if w is None else str(w),
        })
    return rows


def table_lines(rows):
    headers = [
        "Rounds", "Xu", "Pu", "Su", "Yu", "Xl", "Pl", "Sl", "Yl", "wu", "wl", "w",
    ]
    widths = {header: len(header) for header in headers}
    for row in rows:
        for header in headers:
            key = "round" if header == "Rounds" else header
            widths[header] = max(widths[header], len(str(row[key])))

    def cell(row, header):
        key = "round" if header == "Rounds" else header
        return str(row[key]).ljust(widths[header])

    header_line = "  ".join(header.ljust(widths[header]) for header in headers)
    sep_line = "-" * len(header_line)
    body = ["  ".join(cell(row, header) for header in headers) for row in rows]
    return [header_line, sep_line] + body


def span_table_lines(title, trail):
    headers = ["Rounds", "X", "P", "S", "Y", "RK", "KS", "w"]
    rows = []
    if trail is not None:
        nrounds = int(trail["nrounds"])
        for r in range(nrounds + 1):
            row = span_round(trail, r, nrounds)
            rows.append({
                "round": r,
                "X": hx(row["x"]),
                "P": hx(row["p"]),
                "S": hx(row["s"]),
                "Y": hx(row["y"]),
                "RK": hx(row["rk"]),
                "KS": hx(row["ks"]),
                "w": fmt_weight(row["w"]),
            })
    widths = {header: len(header) for header in headers}
    for row in rows:
        for header in headers:
            key = "round" if header == "Rounds" else header
            widths[header] = max(widths[header], len(str(row[key])))
    header_line = "  ".join(header.ljust(widths[header]) for header in headers)
    sep_line = "-" * len(header_line)
    body = []
    for row in rows:
        cells = []
        for header in headers:
            key = "round" if header == "Rounds" else header
            cells.append(str(row[key]).ljust(widths[header]))
        body.append("  ".join(cells))
    return [title, "", header_line, sep_line] + body


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def _build_argument_parser():
    parser = ArgumentParser(
        description="Instantiate Splight RK boomerang over E0+Em and Em+E1 spans\n"
                    "Example:\n"
                    "python rkboom_full.py -r0 2 -rm 2 -r1 2 -w0 6 -wm 3 -w1 6",
        formatter_class=RawTextHelpFormatter,
    )
    parser.add_argument("-i", "--inputfile", type=str, help="Use an input file in yaml format")
    parser.add_argument("-r0", "--r0", type=int, help="number of rounds covered by E0")
    parser.add_argument("-rm", "--rm", type=int, help="number of rounds covered by Em")
    parser.add_argument("-r1", "--r1", type=int, help="number of rounds covered by E1")
    parser.add_argument("-w0", "--w0", type=int, help="cost of active S-boxes in E0")
    parser.add_argument("-wm", "--wm", type=int, help="cost of active S-boxes in Em")
    parser.add_argument("-w1", "--w1", type=int, help="cost of active S-boxes in E1")
    parser.add_argument("-tl", "--timelimit", type=int, help="time limit in seconds")
    parser.add_argument("-ns", "--numofsols", type=int, help="number of solutions")
    parser.add_argument(
        "--rk_mode",
        "--rk-mode",
        dest="rk_mode",
        choices=("rk-basic", "rk-ladder", "rk-debug-independent"),
        default=None,
        help="related-key mode; default rk-ladder",
    )
    return parser


def _run_search(params, results_dir):
    r0, rm, r1 = int(params["r0"]), int(params["rm"]), int(params["r1"])
    assert rm > 0

    bm = RKTruncatedBoomerang(
        r0=r0,
        r1=r1,
        rm=rm,
        w0=params["w0"],
        w1=params["w1"],
        wm=params["wm"],
        rk_mode=params.get("rk_mode", "rk-ladder"),
        time_limit=params.get("timelimit"),
    )
    bm.find_truncated_boomerang_trail()
    upper_trail, middle_part, lower_trail = bm.parse_solver_output()

    upper_rounds = r0 + rm
    lower_rounds = rm + r1
    upper_params = make_diff_params(upper_rounds, 0, params)
    apply_truncated_state_mask(upper_params, 0, upper_trail["x_0"])
    apply_truncated_state_mask(upper_params, upper_rounds, upper_trail[f"x_{upper_rounds}"])
    upper_span = solve_span("upper E0+Em", upper_params)

    lower_params = make_diff_params(lower_rounds, r0, params)
    apply_truncated_state_mask(lower_params, 0, lower_trail["x_0"])
    apply_truncated_state_mask(lower_params, lower_rounds, lower_trail[f"x_{lower_rounds}"])
    lower_span = solve_span("lower Em+E1", lower_params)

    upper_span_lines = span_table_lines("Upper span E0+Em concrete RK trail", upper_span)
    lower_span_lines = span_table_lines("Lower span Em+E1 concrete RK trail", lower_span)
    combined_rows = build_combined_rows(upper_span, lower_span, middle_part, r0, rm, r1)
    lines = table_lines(combined_rows)
    print("\n" + "=" * 72)
    print("\n".join(upper_span_lines))
    print("\n")
    print("\n".join(lower_span_lines))
    print("\n")
    print("Combined concrete E0+Em / Em+E1 boomerang summary table\n")
    print("\n".join(lines))

    result = {
        "parameters": params,
        "upper_truncated_trail": upper_trail,
        "middle_part": middle_part,
        "lower_truncated_trail": lower_trail,
        "upper_e0_em_trail": upper_span,
        "lower_em_e1_trail": lower_span,
        "combined_rows": combined_rows,
        "combined_note": "Final summary omits RK columns. wu/wl are upper/lower round weights; w is per-middle-round common active S-box count.",
        "lp_file": bm.lp_file_name,
    }
    json_path = os.path.join(results_dir, "full_span_boomerang.json")
    txt_path = os.path.join(results_dir, "full_span_boomerang.txt")
    md_path = os.path.join(results_dir, "full_span_boomerang.md")
    write_json(json_path, result)
    with open(txt_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(upper_span_lines) + "\n\n")
        handle.write("\n".join(lower_span_lines) + "\n\n")
        handle.write("\n".join(lines) + "\n")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write("# E0+Em / Em+E1 具体相关密钥 boomerang 表\n\n")
        handle.write(f"参数：`r0={r0}, rm={rm}, r1={r1}, rk_mode={params.get('rk_mode')}`。\n\n")
        handle.write("前两张表保留 `RK` 和 `KS`；最后汇总表不输出 `RK`。`wu` 和 `wl` 分别是 upper/lower 权重，`w` 在中间轮表示 common active S-box 数量。\n\n")
        handle.write("## Upper span\n\n")
        handle.write("```text\n")
        handle.write("\n".join(upper_span_lines))
        handle.write("\n```\n\n")
        handle.write("## Lower span\n\n")
        handle.write("```text\n")
        handle.write("\n".join(lower_span_lines))
        handle.write("\n```\n\n")
        handle.write("## 汇总表\n\n")
        handle.write("```text\n")
        handle.write("\n".join(lines))
        handle.write("\n```\n")
    print(f"\nSaved: {txt_path}")
    print(f"Saved: {json_path}")
    print(f"Saved: {md_path}")


def main(argv=None):
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    args = _build_argument_parser().parse_args(argv)
    params = loadparameters(args)
    case_dir_name = result_case_dir_name(params)
    results_dir = os.path.join("results_full", case_dir_name)
    os.makedirs(results_dir, exist_ok=True)
    terminal_log_path = os.path.join(results_dir, "terminal_print.txt")

    with _tee_terminal_output(terminal_log_path):
        try:
            return _run_search(params, results_dir)
        except BaseException:
            traceback.print_exc()
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
