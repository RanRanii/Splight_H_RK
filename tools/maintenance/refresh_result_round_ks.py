#!/usr/bin/env python3
"""Refresh existing result files so KS columns show round-key states.

This does not solve any MILP. It only rewrites existing result artifacts.
"""

from argparse import ArgumentParser
import json
from pathlib import Path
import re
import sys


BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))
from rkboom import diff_trail_to_lines, truncated_trail_to_lines
from output.plotdistinguisher import save_markdown_distinguisher


RESULTS_DIR = BASE_DIR / "results"


def split_case_dir_name(result_dir):
    match = re.fullmatch(r"(\d+)-(\d+)-(\d+)(?:_(\d+))?", Path(result_dir).name)
    if match is None:
        return None, None
    return "-".join(match.groups()[:3]), match.group(4)


def find_main_result_path(result_dir):
    result_dir = Path(result_dir)
    artifact_name, _ = split_case_dir_name(result_dir)
    if artifact_name is None:
        return None, None
    names = list(dict.fromkeys((artifact_name, result_dir.name)))
    for name in names:
        for candidate in (
            result_dir / ".json" / f"{name}.json",
            result_dir / f"{name}.json",
        ):
            if candidate.is_file():
                return candidate, artifact_name
    return None, artifact_name


def result_case_dir_name(parameters):
    required = ("r0", "rm", "r1", "w0", "wm", "w1")
    missing = [name for name in required if name not in parameters]
    if missing:
        raise ValueError("missing result parameters: " + ", ".join(missing))
    rounds = f"{parameters['r0']}-{parameters['rm']}-{parameters['r1']}"
    weights = f"{parameters['w0']}{parameters['wm']}{parameters['w1']}"
    return f"{rounds}_{weights}"


def rename_result_directory(result_dir):
    """Rename one legacy case directory without overwriting an existing case."""
    result_dir = Path(result_dir)
    artifact_name, weight_suffix = split_case_dir_name(result_dir)
    if artifact_name is None:
        return result_dir, "invalid-directory-name", []
    if weight_suffix is not None:
        return result_dir, "already-weighted", []

    result_path, _ = find_main_result_path(result_dir)
    if result_path is None:
        return result_dir, "missing-main-json", []
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        target_name = result_case_dir_name(result.get("parameters") or {})
    except (json.JSONDecodeError, ValueError) as exc:
        return result_dir, "invalid-main-json", [str(exc)]

    expected_rounds = target_name.split("_", 1)[0]
    if expected_rounds != artifact_name:
        return result_dir, "round-parameter-mismatch", [
            f"directory={artifact_name}, parameters={expected_rounds}"
        ]

    target_dir = result_dir.with_name(target_name)
    if target_dir.exists():
        return result_dir, "target-exists", [str(target_dir)]
    result_dir.rename(target_dir)
    return target_dir, "renamed", []


def update_saved_result_paths(result, old_case_name, new_case_name):
    files = result.get("diff_trail_files")
    if not isinstance(files, dict) or old_case_name == new_case_name:
        return
    for name, value in files.items():
        if not isinstance(value, str):
            continue
        value = value.replace(
            f"results\\{old_case_name}\\",
            f"results\\{new_case_name}\\",
        )
        value = value.replace(
            f"results/{old_case_name}/",
            f"results/{new_case_name}/",
        )
        files[name] = value


def uppercase_hex_strings(value):
    if isinstance(value, dict):
        return {key: uppercase_hex_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [uppercase_hex_strings(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if text and all(ch in "0123456789abcdefABCDEF" for ch in text):
            return text.upper()
    return value


def add_round_ks(trail):
    if not trail:
        return trail
    nrounds = int(trail.get("nrounds", 0))
    round_offset = int(trail.get("round_offset", 0))
    for r in range(nrounds + 1):
        if r < nrounds:
            index = round_offset + r + 1
            value = trail.get(f"ks_global_{index}", "none")
            if isinstance(value, str) and value != "none":
                value = value.upper()
            trail[f"round_ks_{r}"] = value
            trail[f"round_ks_global_index_{r}"] = index
        else:
            trail[f"round_ks_{r}"] = "none"
            trail[f"round_ks_global_index_{r}"] = "none"
    return trail


def verify_round_ks(trail):
    errors = []
    if not trail:
        return errors
    nrounds = int(trail.get("nrounds", 0))
    round_offset = int(trail.get("round_offset", 0))
    for r in range(nrounds):
        index = round_offset + r + 1
        expected = trail.get(f"ks_global_{index}")
        actual = trail.get(f"round_ks_{r}")
        rk = trail.get(f"rk_{r}")
        if expected is None:
            errors.append(f"round {r}: missing ks_global_{index}")
            continue
        expected_cmp = expected.upper() if isinstance(expected, str) else expected
        actual_cmp = actual.upper() if isinstance(actual, str) else actual
        rk_cmp = rk.upper() if isinstance(rk, str) else rk
        if actual_cmp != expected_cmp:
            errors.append(f"round {r}: round_ks_{r} != ks_global_{index}")
        if rk not in (None, "none") and expected_cmp[:8] != rk_cmp:
            errors.append(f"round {r}: RK {rk} != prefix(round_ks) {expected_cmp[:8]}")
    if trail.get(f"round_ks_{nrounds}") != "none":
        errors.append(f"round {nrounds}: terminal round_ks should be none")
    return errors


def preserve_probability_log(txt_path):
    if not txt_path.exists():
        return ""
    text = txt_path.read_text(encoding="utf-8")
    markers = [
        "========================================================================\n搜索后的相关密钥概率实验",
        "========================================================================\n鎼滅储鍚庣殑鐩稿叧瀵嗛挜姒傜巼瀹為獙",
    ]
    for marker in markers:
        if marker in text:
            return text[text.index(marker):]
    return ""


def rewrite_txt(result_dir, result_name, result):
    params = result["parameters"]
    r0, rm, r1 = int(params["r0"]), int(params["rm"]), int(params["r1"])
    upper_trail = result.get("upper_trail") or {}
    lower_trail = result.get("lower_trail") or {}
    middle = result.get("middle_part") or {}
    upper_diff = result.get("diff_upper_trail")
    lower_diff = result.get("diff_lower_trail")
    upper_log2 = float(result.get("diff_effect_upper_log2", 0))
    lower_log2 = float(result.get("diff_effect_lower_log2", 0))

    txt_path = result_dir / f"{result_name}.txt"
    probability_log = preserve_probability_log(txt_path)
    lines = [
        "Summary of the results:",
        "Upper Truncated Trail:",
        *truncated_trail_to_lines(upper_trail, r0 + rm),
        "Lower Truncated Trail:",
        *truncated_trail_to_lines(lower_trail, rm + r1),
        "Upper differential trail:",
        *diff_trail_to_lines(upper_diff),
        "Lower differential trail:",
        *diff_trail_to_lines(lower_diff),
        f"Sandwich {rm} rounds in the middle with {middle.get('as', 0)} active S-boxes",
        "Total probability = p^2*q^2*r = 2^({:.2f}) x 2^({:.2f}) x r".format(
            upper_log2 * 2, lower_log2 * 2
        ),
    ]
    text = "\n".join(lines) + "\n"
    if probability_log:
        text += probability_log
    txt_path.write_text(text, encoding="utf-8")


def refresh_result(result_dir, previous_case_name=None):
    result_dir = Path(result_dir)
    result_path, result_name = find_main_result_path(result_dir)
    if result_name is None:
        return {"name": result_dir.name, "status": "invalid-directory-name", "errors": []}
    if result_path is None:
        return {"name": result_dir.name, "status": "missing-main-json", "errors": []}
    json_dir = result_dir / ".json"

    result = uppercase_hex_strings(json.loads(result_path.read_text(encoding="utf-8")))
    update_saved_result_paths(
        result,
        previous_case_name or result_dir.name,
        result_dir.name,
    )
    result["diff_upper_trail"] = add_round_ks(result.get("diff_upper_trail"))
    result["diff_lower_trail"] = add_round_ks(result.get("diff_lower_trail"))

    errors = []
    errors.extend(f"upper: {item}" for item in verify_round_ks(result.get("diff_upper_trail")))
    errors.extend(f"lower: {item}" for item in verify_round_ks(result.get("diff_lower_trail")))

    json_dir.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    (json_dir / "upper_diff_trail.json").write_text(
        json.dumps(result.get("diff_upper_trail"), indent=2), encoding="utf-8"
    )
    (json_dir / "lower_diff_trail.json").write_text(
        json.dumps(result.get("diff_lower_trail"), indent=2), encoding="utf-8"
    )
    (result_dir / "upper_diff_trail.txt").write_text(
        "\n".join(diff_trail_to_lines(result.get("diff_upper_trail"))) + "\n",
        encoding="utf-8",
    )
    (result_dir / "lower_diff_trail.txt").write_text(
        "\n".join(diff_trail_to_lines(result.get("diff_lower_trail"))) + "\n",
        encoding="utf-8",
    )
    rewrite_txt(result_dir, result_name, result)
    save_markdown_distinguisher(str(result_path), str(result_dir / f"{result_name}_distinguisher.md"))
    return {
        "name": result_dir.name,
        "artifact_name": result_name,
        "status": "updated",
        "errors": errors,
    }


def main(argv=None):
    parser = ArgumentParser()
    parser.add_argument(
        "--rename-case-dirs",
        action="store_true",
        help="rename legacy r0-rm-r1 directories to r0-rm-r1_w0wmw1",
    )
    parser.add_argument(
        "--rename-only",
        action="store_true",
        help=(
            "rename legacy r0-rm-r1 directories without rewriting any "
            "historical result artifacts"
        ),
    )
    args = parser.parse_args(argv)
    summaries = []
    for result_dir in sorted(path for path in RESULTS_DIR.iterdir() if path.is_dir()):
        original_name = result_dir.name
        rename_status = "not-requested"
        rename_errors = []
        if args.rename_case_dirs or args.rename_only:
            result_dir, rename_status, rename_errors = rename_result_directory(result_dir)
        if args.rename_only:
            summary = {
                "name": result_dir.name,
                "status": "artifacts-unchanged",
                "errors": [],
            }
        else:
            summary = refresh_result(result_dir, previous_case_name=original_name)
        summary["rename_status"] = rename_status
        summary["errors"] = rename_errors + summary["errors"]
        summaries.append(summary)

    log_dir = BASE_DIR / "diff" / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    if args.rename_only:
        log_path = log_dir / "result_directory_rename.md"
        lines = [
            "# 已有结果目录重命名记录",
            "",
            "本次只迁移目录名称，没有重写目录内任何历史结果文件。",
            "",
            "| 配置 | 目录迁移 | 状态 | 问题 |",
            "|---|---|---|---|",
        ]
    else:
        log_path = log_dir / "round_ks_result_refresh.md"
        lines = [
            "# 已有结果 KS 列与十六进制大小写整理记录",
            "",
            "本次没有重新求解 MILP，只重写已有结果文件中的密钥状态展示和十六进制大小写。",
            "",
            "规则：",
            "",
            "- `ks_global_0` 是主密钥输入差分状态，不是第 0 轮加密使用的轮密钥状态。",
            "- 第 `r` 轮加密使用更新后的 `ks_global_{round_offset+r+1}`。",
            "- `KS` 列显示 `round_ks_r = ks_global_{round_offset+r+1}`。",
            "- 终止状态行没有加密轮，`KS` 显示为 `none`。",
            "- 所有纯十六进制字符串统一写为大写。",
            "",
            "| 配置 | 目录迁移 | 状态 | 校验问题 |",
            "|---|---|---|---|",
        ]
    for item in summaries:
        issue = "<br>".join(item["errors"]) if item["errors"] else ""
        lines.append(
            f"| {item['name']} | {item['rename_status']} | "
            f"{item['status']} | {issue} |"
        )
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    action = "processed" if args.rename_only else "refreshed"
    print(f"{action} {len(summaries)} result directories")
    print(log_path)


if __name__ == "__main__":
    main()
