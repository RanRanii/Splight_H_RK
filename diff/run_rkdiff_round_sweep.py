"""Run related-key truncated/differential round sweep for Splight."""

import contextlib
import csv
import io
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "diff"
RKDIFF_TIME_LIMIT_SECONDS = 120
TRUNCDIFF_TIME_LIMIT_SECONDS = 120
STOP_ACTIVE_SBOXES = 32
MAX_ROUNDS = 64
RUN_REAL_DIFF_FOR_NEW_ROUNDS = False

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rkdiff import RKDiff  # noqa: E402
from rktruncdiff import RKTruncDiff  # noqa: E402


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


def run_truncated(rounds):
    lp_path = os.path.join("tmp", f"splight_h_rk_truncdiff_{rounds}.lp")
    model = RKTruncDiff(nrounds=rounds, lp_file_name=lp_path, time_limit=TRUNCDIFF_TIME_LIMIT_SECONDS)
    start = time.time()
    result = model.solve()
    elapsed = time.time() - start
    result["rounds"] = rounds
    result["active_sboxes"] = result.get("objective")
    result["time_seconds"] = elapsed
    result["status_name"] = status_name(result.get("status"))
    return result


def run_real_diff(rounds):
    params = {
        "nrounds": rounds,
        "rk_mode": "rk-ladder",
        "mode": 0,
        "timelimit": RKDIFF_TIME_LIMIT_SECONDS,
    }
    model = RKDiff(params)
    start = time.time()
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        trail = model.solve()
    elapsed = time.time() - start
    text = stream.getvalue()
    status = int(model.milp_model.Status) if model.milp_model is not None else None
    weight = None
    if trail:
        weight = float(trail.get("total_weight", 0))
    return {
        "rounds": rounds,
        "status": status,
        "status_name": status_name(status),
        "weight": weight,
        "time_limit_seconds": RKDIFF_TIME_LIMIT_SECONDS,
        "time_seconds": elapsed,
        "trail": trail,
        "stdout": text,
        "lp_file": model.lp_file_name,
    }


def markdown_table(rows):
    last_round = rows[-1]["rounds"] if rows else 0
    lines = [
        f"# Splight-RK 0-{last_round} 轮差分搜索汇总",
        "",
        "本表统计 `rktruncdiff.py` 的截断活跃 S-box 数，以及 `rkdiff.py` 的比特级真实差分 weight。",
        f"本轮续跑的 bit 级 `rkdiff.py` 单轮求解时间限制为 {RKDIFF_TIME_LIMIT_SECONDS} 秒。",
        f"截断活跃 S-box 数达到或超过 {STOP_ACTIVE_SBOXES} 后停止继续增加轮数。",
        "`OPTIMAL` 表示该值已证明最优；`TIME_LIMIT` 表示该值只是限时内找到的当前可行/当前最优上界，尚未证明最优。",
        "",
        "| 轮数 | 截断状态 | 截断活跃 S-box 数 | 真实差分状态 | 已证明真实 weight | TIME_LIMIT incumbent | 说明 | 截断耗时(s) | 真实搜索耗时(s) |",
        "|---:|---|---:|---|---:|---:|---|---:|---:|",
    ]
    for row in rows:
        active = row["truncated_active_sboxes"]
        weight = row["real_weight"]
        if row["real_status"] == "OPTIMAL":
            note = "已证明最优"
            proven_weight = "" if weight is None else f"{weight:.2f}"
            incumbent = ""
        elif row["real_status"] == "NOT_RUN":
            note = "未测试"
            proven_weight = ""
            incumbent = ""
        else:
            note = "未证明最优，不能作为真实 weight"
            proven_weight = ""
            incumbent = "" if weight is None else f"{weight:.2f}"
        lines.append(
            "| {rounds} | {trunc_status} | {active} | {real_status} | {proven_weight} | {incumbent} | {note} | {trunc_time:.2f} | {real_time:.2f} |".format(
                rounds=row["rounds"],
                trunc_status=row["truncated_status"],
                active="" if active is None else f"{active:.2f}",
                real_status=row["real_status"],
                proven_weight=proven_weight,
                incumbent=incumbent,
                note=note,
                trunc_time=row["truncated_time_seconds"],
                real_time=row["real_time_seconds"],
            )
        )
    lines.extend(
        [
            "",
            "说明：",
            "",
            "- 截断活跃 S-box 数来自 nibble 级 `RKTruncDiff` 目标值。",
            "- 已证明真实 weight 只填写 `RKDiff` 状态为 `OPTIMAL` 的轮数。",
            "- 若状态为 `TIME_LIMIT`，表中的 incumbent 只是限时内找到的当前可行值，不能作为真实最小 weight 使用。",
            "- 每轮的完整求解日志和 JSON 结果保存在同一目录下的 `round_XX_*` 文件中。",
        ]
    )
    return "\n".join(lines) + "\n"


def should_rerun_real(real_path):
    if not RUN_REAL_DIFF_FOR_NEW_ROUNDS:
        return False
    if not real_path.exists():
        return True
    data = read_json(real_path)
    return (
        data.get("status_name") == "TIME_LIMIT"
        or int(data.get("time_limit_seconds", 0)) < RKDIFF_TIME_LIMIT_SECONDS
    )


def load_real_summary(real_path):
    if not real_path.exists():
        return {
            "status_name": "NOT_RUN",
            "weight": None,
            "time_limit_seconds": RKDIFF_TIME_LIMIT_SECONDS,
            "time_seconds": 0,
            "lp_file": None,
        }
    data = read_json(real_path)
    return {
        "status_name": data.get("status_name"),
        "weight": data.get("weight"),
        "time_limit_seconds": data.get("time_limit_seconds", RKDIFF_TIME_LIMIT_SECONDS),
        "time_seconds": data.get("time_seconds", 0),
        "lp_file": data.get("lp_file"),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    rounds = 0
    while rounds <= MAX_ROUNDS:
        trunc_path = OUT_DIR / f"round_{rounds:02d}_truncated.json"
        real_path = OUT_DIR / f"round_{rounds:02d}_rkdiff.json"
        real_txt_path = OUT_DIR / f"round_{rounds:02d}_rkdiff.txt"

        if trunc_path.exists():
            print(f"[{rounds}] truncated search: reuse")
            trunc = read_json(trunc_path)
        else:
            print(f"[{rounds}] truncated search")
            trunc = run_truncated(rounds)
            write_json(trunc_path, trunc)

        if should_rerun_real(real_path):
            suffix = "rerun with 120s" if real_path.exists() else "run"
            print(f"[{rounds}] bit-wise RK differential search: {suffix}")
            real = run_real_diff(rounds)
            real_json = {k: v for k, v in real.items() if k != "stdout"}
            write_json(real_path, real_json)
            with open(real_txt_path, "w", encoding="utf-8") as handle:
                handle.write(real["stdout"])
        else:
            action = "reuse" if real_path.exists() else "skip"
            print(f"[{rounds}] bit-wise RK differential search: {action}")
            real = load_real_summary(real_path)

        rows.append(
            {
                "rounds": rounds,
                "truncated_status": trunc["status_name"],
                "truncated_active_sboxes": trunc.get("active_sboxes"),
                "real_status": real["status_name"],
                "real_weight": real.get("weight"),
                "truncated_time_seconds": trunc["time_seconds"],
                "real_time_seconds": real["time_seconds"],
                "real_time_limit_seconds": real.get("time_limit_seconds", RKDIFF_TIME_LIMIT_SECONDS),
                "truncated_lp_file": trunc.get("lp_file"),
                "real_lp_file": real.get("lp_file"),
            }
        )

        active = trunc.get("active_sboxes")
        if active is not None and float(active) >= STOP_ACTIVE_SBOXES:
            print(f"Stop at round {rounds}: truncated active S-boxes = {active}")
            break
        if active is None or trunc.get("status_name") != "OPTIMAL":
            print(f"Stop at round {rounds}: truncated status = {trunc.get('status_name')}, active = {active}")
            break
        rounds += 1

    write_json(OUT_DIR / "rkdiff_round_sweep_summary.json", rows)
    with open(OUT_DIR / "rkdiff_round_sweep_summary.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with open(OUT_DIR / "rkdiff_round_sweep_summary.md", "w", encoding="utf-8") as handle:
        handle.write(markdown_table(rows))
    print(f"Saved results to {OUT_DIR}")


if __name__ == "__main__":
    main()
