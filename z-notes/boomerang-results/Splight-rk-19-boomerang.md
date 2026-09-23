---
title: Splight 19轮 RK-Boomerang 结果汇总
aliases:
  - Splight-rk-19-boomerang
tags:
  - Splight
  - related-key
  - boomerang
  - 19-round
  - experiment
date: 2026-09-23
data_source: results, run-logs
sort_key: estimated_probability_interval
---

# Splight 19轮 RK-Boomerang 结果汇总

本文汇总 `results/` 中全部总轮数为19轮的相关密钥 boomerang 搜索结果。截至2026-09-23，19轮队列计划的11组配置已全部生成结果目录：5组为 `Exact SUCCESS`，5组为 `GLOBAL_TIME_LIMIT`，1组为 `SEARCH_INCOMPLETE_TIMEOUT`。

队列 `run_19_636_recommended_queue.ps1`（原名 `run_19_636_concrete_then_rklb_queue.ps1`）分两段执行。2026-09-21 完成前9组后中断；2026-09-23 按“结果目录已存在即跳过”的规则补跑，跳过9组，`7-5-7_636` 超时，`8-5-6_636` 成功，至此11组全部有结果。

## 1. 指标与排序口径

设区分器轮数为 $(r_0,r_m,r_1)$，满足：

$$
r_0+r_m+r_1=19.
$$

$W_u$ 和 $W_l$ 分别是 upper、lower concrete RK differential characteristic 的 DDT weight，$CAS$ 是中间段共同活跃 S-box 数。模型给出的概率区间为：

$$
B_{best}=2W_u+2W_l+2CAS,
$$

$$
B_{worst}=2W_u+2W_l+\frac{5}{2}CAS,
$$

$$
2^{-B_{worst}}\le P_{boom}\le 2^{-B_{best}}.
$$

主表按预估概率从大到小排列：先按 $B_{best}$ 从小到大，再按 $B_{worst}$ 从小到大，最后按 Case 名称字典序。为与全轮数总表保持一致，同时给出辅助排序分数：

$$
S=2(W_u+W_l+2CAS).
$$

> $S$ 只作为总表中的排序分数，不等于模型概率指数。无完整 concrete 结果的配置不参加排名，放在 SUCCESS 表之后。

## 2. 全部19轮结果

| 排名 | Case | Exact状态 | $W_u$ | $W_l$ | $CAS$ | $S$ | 预估概率 | 求解时间（s） | 结果 |
|---:|---|---|---:|---:|---:|---:|---|---:|---|
| 1 | `8-2-9_636` | SUCCESS | 8 | 24 | 0 | 64 | $2^{-64}$ | 336.671421 | [结果](../../results/8-2-9_636/) · [区分器 md](../../results/8-2-9_636/8-2-9_distinguisher.md) |
| 2 | `8-3-8_636` | SUCCESS | 8 | 26 | 3 | 80 | $[2^{-75.5},2^{-74}]$ | 91.738219 | [结果](../../results/8-3-8_636/) · [区分器 md](../../results/8-3-8_636/8-3-8_distinguisher.md) |
| 3 | `8-4-7_636` | SUCCESS | 8 | 16 | 15 | 108 | $[2^{-85.5},2^{-78}]$ | 3181.890224 | [结果](../../results/8-4-7_636/) · [区分器 md](../../results/8-4-7_636/8-4-7_distinguisher.md) |
| 4 | `7-4-8_636` | SUCCESS | 12 | 26 | 4 | 92 | $[2^{-86},2^{-84}]$ | 87.260374 | [结果](../../results/7-4-8_636/) · [区分器 md](../../results/7-4-8_636/7-4-8_distinguisher.md) |
| 5 | `8-5-6_636` | SUCCESS | 16 | 18 | 11 | 112 | $[2^{-95.5},2^{-90}]$ | 21.445383 | [结果](../../results/8-5-6_636/) · [区分器 md](../../results/8-5-6_636/8-5-6_distinguisher.md) |

### 2.1 未完成配置

| Case | Exact状态 | 求解时间（s） | 结果 |
|---|---|---:|---|
| `6-5-8_636` | GLOBAL_TIME_LIMIT | 3600.180721 | [结果](../../results/6-5-8_636/) |
| `7-2-10_636` | GLOBAL_TIME_LIMIT | 3600.196494 | [结果](../../results/7-2-10_636/) |
| `7-5-7_636` | GLOBAL_TIME_LIMIT | 3600.181792 | [结果](../../results/7-5-7_636/) |
| `8-1-10_636` | SEARCH_INCOMPLETE_TIMEOUT | 3600.008546 | [结果](../../results/8-1-10_636/) |
| `9-1-9_636` | GLOBAL_TIME_LIMIT | 3600.206474 | [结果](../../results/9-1-9_636/) |
| `9-2-8_636` | GLOBAL_TIME_LIMIT | 3600.199201 | [结果](../../results/9-2-8_636/) |

这6组在3600秒全局上限内没有写出可接受的 concrete characteristic，不能用来断言不存在区分器。

## 3. 概率阈值分类

### 3.1 触及随机基线

- `8-2-9_636` 的概率恰为 $2^{-64}$，只达到随机基线而非严格超过。它的 $CAS=0$，是19轮中唯一没有中间段 switch 不确定性的 SUCCESS 结果。

### 3.2 低于随机基线

- `8-3-8_636`、`8-4-7_636`、`7-4-8_636`、`8-5-6_636` 的乐观界分别为 $2^{-74}$、$2^{-78}$、$2^{-84}$、$2^{-90}$，均低于 $2^{-64}$。

### 3.3 未完成配置

- 5组 `GLOBAL_TIME_LIMIT` 与 1组 `SEARCH_INCOMPLETE_TIMEOUT` 在3600秒全局上限处停止，没有可接受的 concrete characteristic。

## 4. 结构观察

1. 19轮目前没有预估概率严格高于 $2^{-64}$ 的配置；最好的 `8-2-9_636` 恰好等于 $2^{-64}$。
2. `8-2-9_636` 由第一阶段的“8轮 upper 权重8 + 9轮 lower 权重24”组合得到，其 $CAS=0$，说明增加一轮 lower 会把它从18轮 `8-2-8_636` 的 $[2^{-57},2^{-56}]$ 推低到 $2^{-64}$ 附近。
3. 补跑新增的 `8-5-6_636` 是第5个 SUCCESS 结果，$W_u=16$、$W_l=18$、$CAS=11$，概率为 $[2^{-95.5},2^{-90}]$，外部权重与中间代价同时偏大。
4. $r_m\ge3$ 的 SUCCESS 结果 $CAS$ 明显增大（`8-3-8_636` 为3，`8-5-6_636` 为11，`8-4-7_636` 为15），中间段代价成为主要限制。
5. 方向不对称仍然存在：`8-2-9_636` 成功且为 $2^{-64}$，而其反向检查 `9-2-8_636` 在3600秒内超时。
6. 两个 $r_m=1$ 配置 `8-1-10_636` 与 `9-1-9_636` 都没有成功，$r_m=1$ 的低 $CAS$ 优势没有转化为可搜索到的 concrete 路径。
7. 表中“预估概率”均为 characteristic 与 switch 上下界口径的估计，尚未用独立采样实验替换。

## 5. 队列执行摘要

统计来自 `run_19_636_recommended_queue.log`，运行参数为 `tl=300`、`globalTl=3600`、`verifyMs=600000`、`pathSec=7200`、`rk-ladder`、`probtest=false`。

| 项目 | 数量 |
|---|---:|
| 队列中计划项目 | 11 |
| 因结果目录已存在跳过 | 9 |
| 本次新完成且 Exact SUCCESS | 1 |
| 本次超时 | 1 |
| 2026-09-21 前9个任务累计运行时间 | 约6小时1分42秒 |
| 2026-09-23 补跑累计运行时间 | 约1小时0分23秒 |

2026-09-23 的补跑于00:43:12启动，01:43:35结束，最终记录为 `QUEUE COMPLETE completed=1 skipped=9 failed=1`。

## 6. 数据入口

- 正式结果：`results/<case>/.json/<r0>-<rm>-<r1>.json`
- Exact 总结：`results/<case>/exact_summary.json`
- 搜索终端日志：`results/<case>/terminal_print.txt`
- 19轮队列日志：[`run_19_636_recommended_queue.log`](../../run/run_19_636_recommended_queue.log)
- 队列独立案例日志：[`run/logs/run_19_636_recommended_queue/`](../../run/logs/run_19_636_recommended_queue/)
- 全轮数汇总：[[Splight-rk-boomerang实验结果]]
