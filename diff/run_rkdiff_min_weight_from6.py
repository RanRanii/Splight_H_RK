"""Direct bit-level RKDiff minimum-weight search for rounds 6..15."""

import contextlib
import io
import json
import shutil
import sys
import time
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIFF_DIR = ROOT / "diff"
LEGACY_DIR = DIFF_DIR / "rkdiff_min_weight_from6"
START_ROUND = 6
MAX_ROUND = 15
START_WEIGHT = 6
TIME_LIMIT_SECONDS = 120
RERUN_ROUNDS = set()

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rkdiff import RKDiff  # noqa: E402


STATUS_NAMES = {
    2: "OPTIMAL",
    3: "INFEASIBLE",
    9: "TIME_LIMIT",
    11: "INTERRUPTED",
}


def status_name(status):
    if status is None:
        return "NONE"
    return STATUS_NAMES.get(int(status), str(status))


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def round_dir(rounds):
    return DIFF_DIR / f"round-{rounds}"


def target_json(rounds):
    return round_dir(rounds) / "min_weight_rkdiff.json"


def target_txt(rounds):
    return round_dir(rounds) / "min_weight_rkdiff.txt"


def legacy_json(rounds):
    return LEGACY_DIR / f"round_{rounds:02d}.json"


def legacy_txt(rounds):
    return LEGACY_DIR / f"round_{rounds:02d}.txt"


def migrate_legacy(rounds):
    src_json = legacy_json(rounds)
    if not src_json.exists():
        return False
    round_dir(rounds).mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_json, target_json(rounds))
    if legacy_txt(rounds).exists():
        shutil.copy2(legacy_txt(rounds), target_txt(rounds))
    return True


def run_round(rounds):
    params = {
        "nrounds": rounds,
        "rk_mode": "rk-ladder",
        "mode": 0,
        "startweight": START_WEIGHT,
        "timelimit": TIME_LIMIT_SECONDS,
    }
    model = RKDiff(params)
    stream = io.StringIO()
    start = time.time()
    with contextlib.redirect_stdout(stream):
        trail = model.solve()
    elapsed = time.time() - start
    status = int(model.milp_model.Status) if model.milp_model is not None else None
    result = {
        "rounds": rounds,
        "mode": "direct_bit_level_rkdiff_min_weight",
        "start_weight": START_WEIGHT,
        "time_limit_seconds": TIME_LIMIT_SECONDS,
        "status": status,
        "status_name": status_name(status),
        "weight": float(trail.get("total_weight", 0)) if trail else None,
        "time_seconds": elapsed,
        "lp_file": model.lp_file_name,
        "trail": trail,
    }
    return result, stream.getvalue()


def row_from_result(result):
    status = result.get("status_name")
    weight = result.get("weight")
    return {
        "rounds": result.get("rounds"),
        "status_name": status,
        "proven_weight": weight if status == "OPTIMAL" else None,
        "time_limit_incumbent": weight if status == "TIME_LIMIT" else None,
        "time_seconds": result.get("time_seconds", 0),
        "start_weight": result.get("start_weight", START_WEIGHT),
        "time_limit_seconds": result.get("time_limit_seconds", TIME_LIMIT_SECONDS),
        "lp_file": result.get("lp_file"),
        "error": result.get("error"),
    }


def write_summary(rows):
    write_json(DIFF_DIR / "min_weight_6_15.json", rows)
    lines = [
        "# RKDiff 直接 bit-level 最小 weight 搜索（6-15 轮）",
        "",
        f"- 轮数范围：{START_ROUND}-{MAX_ROUND}",
        f"- 起始 weight 下界：{START_WEIGHT}",
        f"- 单轮求解时间限制：{TIME_LIMIT_SECONDS} 秒",
        "- 搜索方式：直接使用 `rkdiff.py` 的 bit-level MILP，以 S-box 概率 weight 为目标函数最小化。",
        "- 说明：只有 `OPTIMAL` 的 `已证明 weight` 是已证明最小值；`TIME_LIMIT incumbent` 只是限时内找到的可行解。",
        "",
        "| 轮数 | 状态 | 已证明 weight | TIME_LIMIT incumbent | 耗时(s) | 结果目录 |",
        "|---:|---|---:|---:|---:|---|",
    ]
    for row in rows:
        rounds = row["rounds"]
        lines.append(
            "| {rounds} | {status_name} | {proven_weight} | {incumbent} | {time_seconds:.2f} | {result_dir} |".format(
                rounds=rounds,
                status_name=row["status_name"],
                proven_weight="" if row["proven_weight"] is None else f"{row['proven_weight']:.2f}",
                incumbent="" if row["time_limit_incumbent"] is None else f"{row['time_limit_incumbent']:.2f}",
                time_seconds=row["time_seconds"],
                result_dir=f"diff/round-{rounds}",
            )
        )
    errors = [row for row in rows if row.get("error")]
    if errors:
        lines.extend(["", "## 异常", ""])
        for row in errors:
            lines.append(f"- {row['rounds']} 轮：`{row['error']}`")
    with open(DIFF_DIR / "min_weight_6_15.md", "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main():
    DIFF_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for rounds in range(START_ROUND, MAX_ROUND + 1):
        round_dir(rounds).mkdir(parents=True, exist_ok=True)
        json_path = target_json(rounds)
        txt_path = target_txt(rounds)
        if json_path.exists():
            result = read_json(json_path)
            print(f"[{rounds}] reuse {result.get('status_name')}")
        elif migrate_legacy(rounds):
            result = read_json(json_path)
            print(f"[{rounds}] migrated {result.get('status_name')}")
        else:
            print(f"[{rounds}] direct RKDiff min-weight search")
            try:
                result, stdout = run_round(rounds)
            except Exception as exc:
                result = {
                    "rounds": rounds,
                    "mode": "direct_bit_level_rkdiff_min_weight",
                    "start_weight": START_WEIGHT,
                    "time_limit_seconds": TIME_LIMIT_SECONDS,
                    "status": None,
                    "status_name": "ERROR",
                    "weight": None,
                    "time_seconds": 0,
                    "lp_file": None,
                    "trail": None,
                    "error": repr(exc),
                }
                stdout = traceback.format_exc()
            write_json(json_path, result)
            with open(txt_path, "w", encoding="utf-8") as handle:
                handle.write(stdout)
        rows.append(row_from_result(result))
        write_summary(rows)


if __name__ == "__main__":
    main()
