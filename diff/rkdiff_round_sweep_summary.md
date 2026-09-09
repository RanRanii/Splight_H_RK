# Splight-RK 0-27 轮差分搜索汇总

本表统计 `rktruncdiff.py` 的截断活跃 S-box 数，以及 `rkdiff.py` 的比特级真实差分 weight。
本轮续跑的 bit 级 `rkdiff.py` 单轮求解时间限制为 120 秒。
截断活跃 S-box 数达到或超过 32 后停止继续增加轮数。
`OPTIMAL` 表示该值已证明最优；`TIME_LIMIT` 表示该值只是限时内找到的当前可行/当前最优上界，尚未证明最优。

| 轮数 | 截断状态 | 截断活跃 S-box 数 | 真实差分状态 | 已证明真实 weight | TIME_LIMIT incumbent | 说明 | 截断耗时(s) | 真实搜索耗时(s) |
|---:|---|---:|---|---:|---:|---|---:|---:|
| 0 | OPTIMAL | 0.00 | OPTIMAL | 0.00 |  | 已证明最优 | 0.04 | 0.04 |
| 1 | OPTIMAL | 0.00 | OPTIMAL | 0.00 |  | 已证明最优 | 0.05 | 0.02 |
| 2 | OPTIMAL | 1.00 | OPTIMAL | 2.00 |  | 已证明最优 | 0.07 | 0.17 |
| 3 | OPTIMAL | 1.00 | OPTIMAL | 2.00 |  | 已证明最优 | 0.10 | 0.14 |
| 4 | OPTIMAL | 1.00 | OPTIMAL | 2.00 |  | 已证明最优 | 0.02 | 0.17 |
| 5 | OPTIMAL | 2.00 | OPTIMAL | 4.00 |  | 已证明最优 | 0.03 | 22.75 |
| 6 | OPTIMAL | 3.00 | TIME_LIMIT |  | 6.00 | 未证明最优，不能作为真实 weight | 0.05 | 145.28 |
| 7 | OPTIMAL | 3.00 | TIME_LIMIT |  | 6.00 | 未证明最优，不能作为真实 weight | 0.12 | 151.57 |
| 8 | OPTIMAL | 4.00 | TIME_LIMIT |  | 8.00 | 未证明最优，不能作为真实 weight | 0.16 | 228.32 |
| 9 | OPTIMAL | 6.00 | TIME_LIMIT |  | 16.00 | 未证明最优，不能作为真实 weight | 0.54 | 120.11 |
| 10 | OPTIMAL | 8.00 | TIME_LIMIT |  | 23.00 | 未证明最优，不能作为真实 weight | 0.73 | 120.21 |
| 11 | OPTIMAL | 10.00 | TIME_LIMIT |  | 34.00 | 未证明最优，不能作为真实 weight | 0.79 | 120.12 |
| 12 | OPTIMAL | 13.00 | TIME_LIMIT |  | 34.00 | 未证明最优，不能作为真实 weight | 1.51 | 120.20 |
| 13 | OPTIMAL | 14.00 | TIME_LIMIT |  | 40.00 | 未证明最优，不能作为真实 weight | 2.33 | 120.15 |
| 14 | OPTIMAL | 15.00 | TIME_LIMIT |  | 145.00 | 未证明最优，不能作为真实 weight | 3.22 | 120.14 |
| 15 | OPTIMAL | 16.00 | TIME_LIMIT |  | 50.00 | 未证明最优，不能作为真实 weight | 3.71 | 120.20 |
| 16 | OPTIMAL | 18.00 | TIME_LIMIT |  | 176.00 | 未证明最优，不能作为真实 weight | 7.56 | 120.18 |
| 17 | OPTIMAL | 20.00 | TIME_LIMIT |  | 192.00 | 未证明最优，不能作为真实 weight | 15.36 | 120.29 |
| 18 | OPTIMAL | 21.00 | TIME_LIMIT |  | 216.00 | 未证明最优，不能作为真实 weight | 14.90 | 120.18 |
| 19 | OPTIMAL | 22.00 | TIME_LIMIT |  | 228.00 | 未证明最优，不能作为真实 weight | 20.21 | 120.17 |
| 20 | OPTIMAL | 24.00 | TIME_LIMIT |  | 248.00 | 未证明最优，不能作为真实 weight | 40.64 | 120.21 |
| 21 | OPTIMAL | 25.00 | TIME_LIMIT |  | 260.00 | 未证明最优，不能作为真实 weight | 39.68 | 120.18 |
| 22 | OPTIMAL | 27.00 | TIME_LIMIT |  | 1147.00 | 未证明最优，不能作为真实 weight | 199.33 | 120.21 |
| 23 | OPTIMAL | 27.00 | TIME_LIMIT |  | 1197.00 | 未证明最优，不能作为真实 weight | 110.45 | 120.21 |
| 24 | OPTIMAL | 29.00 | TIME_LIMIT |  | 1240.00 | 未证明最优，不能作为真实 weight | 154.71 | 120.26 |
| 25 | OPTIMAL | 30.00 | TIME_LIMIT |  | 1303.00 | 未证明最优，不能作为真实 weight | 359.53 | 120.23 |
| 26 | OPTIMAL | 31.00 | TIME_LIMIT |  | 1363.00 | 未证明最优，不能作为真实 weight | 423.61 | 120.25 |
| 27 | TIME_LIMIT | 32.00 | NOT_RUN |  |  | 未测试 | 120.06 | 0.00 |

说明：

- 截断活跃 S-box 数来自 nibble 级 `RKTruncDiff` 目标值。
- 已证明真实 weight 只填写 `RKDiff` 状态为 `OPTIMAL` 的轮数。
- 若状态为 `TIME_LIMIT`，表中的 incumbent 只是限时内找到的当前可行值，不能作为真实最小 weight 使用。
- 每轮的完整求解日志和 JSON 结果保存在同一目录下的 `round_XX_*` 文件中。
