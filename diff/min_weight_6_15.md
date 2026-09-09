# RKDiff 直接 bit-level 最小 weight 搜索（6-15 轮）

- 轮数范围：6-15
- 起始 weight 下界：6
- 单轮求解时间限制：1200 秒
- 搜索方式：直接使用 `rkdiff.py` 的 bit-level MILP，以 S-box 概率 weight 为目标函数最小化。
- 说明：只有 `OPTIMAL` 的 `已证明 weight` 是已证明最小值；`TIME_LIMIT incumbent` 只是限时内找到的可行解。

| 轮数 | 状态 | 已证明 weight | TIME_LIMIT incumbent | 耗时(s) | 结果目录 |
|---:|---|---:|---:|---:|---|
| 6 | OPTIMAL | 6.00 |  | 175.22 | diff/round-6 |
| 7 | OPTIMAL | 6.00 |  | 460.41 | diff/round-7 |
| 8 | OPTIMAL | 8.00 |  | 844.00 | diff/round-8 |
| 9 | TIME_LIMIT |  | 16.00 | 1200.09 | diff/round-9 |
| 10 | TIME_LIMIT |  | 20.00 | 1200.10 | diff/round-10 |
| 11 | TIME_LIMIT |  | 28.00 | 120.18 | diff/round-11 |
| 12 | TIME_LIMIT |  | 34.00 | 120.12 | diff/round-12 |
| 13 | TIME_LIMIT |  | 57.00 | 120.19 | diff/round-13 |
| 14 | TIME_LIMIT |  | 146.00 | 120.20 | diff/round-14 |
| 15 | TIME_LIMIT |  | 152.00 | 120.14 | diff/round-15 |
