"""Search minimum-weight related-key differential trails for 2..11 rounds."""

import json
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
RESULTS_DIR = BASE / "results" / "rkdiff_2_11"


def run_round(rounds, time_limit):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "tools/rkdiff_cli.py",
        "--rounds",
        str(rounds),
        "--time-limit",
        str(time_limit),
    ]
    completed = subprocess.run(cmd, cwd=BASE, text=True, capture_output=True, check=False)
    log = completed.stdout
    if completed.stderr:
        log += "\n[stderr]\n" + completed.stderr
    (RESULTS_DIR / f"rkdiff_{rounds}r_terminal.txt").write_text(log, encoding="utf-8")
    json_path = RESULTS_DIR / f"rkdiff_{rounds}r.json"
    if completed.returncode != 0 or not json_path.exists():
        return {"rounds": rounds, "status": "failed", "returncode": completed.returncode}
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return {
        "rounds": rounds,
        "status": "ok",
        "weight": data.get("total_weight"),
        "master_key_diff": data.get("master_key_diff"),
        "input_diff": data.get("x_0"),
        "output_diff": data.get(f"x_{rounds}"),
        "json": str(json_path.relative_to(BASE)),
        "terminal": str((RESULTS_DIR / f"rkdiff_{rounds}r_terminal.txt").relative_to(BASE)),
    }


def make_summary(rows):
    lines = [
        "# Splight-H-RK 相关密钥差分 2 到 11 轮最小 weight 搜索",
        "",
        "该汇总由 `run/run_rkdiff_rounds.py` 生成。每个轮数调用 `rkdiff.py`，模型同时包含状态差分、128-bit 主密钥差分、Splight key schedule 差分和每轮 round key 差分。",
        "",
        "| rounds | status | weight | master key diff | input diff | output diff | json | terminal |",
        "|---:|:---:|---:|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['rounds']} | {row['status']} | {row.get('weight', 'n/a')} | "
            f"{row.get('master_key_diff', 'n/a')} | {row.get('input_diff', 'n/a')} | "
            f"{row.get('output_diff', 'n/a')} | `{row.get('json', 'n/a')}` | `{row.get('terminal', 'n/a')}` |"
        )
    return "\n".join(lines) + "\n"


def main():
    time_limit = 120
    rows = []
    for rounds in range(2, 12):
        print(f"running rkdiff {rounds} rounds", flush=True)
        rows.append(run_round(rounds, time_limit))
    (RESULTS_DIR / "rkdiff_2_11_raw.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (RESULTS_DIR / "RKDIFF_2_11_SUMMARY.md").write_text(make_summary(rows), encoding="utf-8")
    print(RESULTS_DIR / "RKDIFF_2_11_SUMMARY.md")


if __name__ == "__main__":
    main()
