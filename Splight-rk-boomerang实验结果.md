---
title: Splight RK-Boomerang 实验结果
aliases:
  - Splight-rk-boomerang实验结果
tags:
  - Splight
  - related-key
  - boomerang
  - MILP
  - Z3
  - experiment
date: 2026-09-02
data_source: results, probability_results
---

# Splight RK-Boomerang 实验结果

> [!summary] 数据口径
> 本文按当前 `results/` 中的 41 个 case 重新整理。对于尚无同名概率结果的可恢复 case，已逐一执行 `python run/probtest_from_results.py --result-dir .\results\<case>`。概率程序没有重新运行 truncated MILP、RKDiff characteristic 搜索或 Z3 exact refinement。

关联文档：[[Splight-rk-boomerang搜索模型]]、[[README_Splight-H-RK]]、[[tools/TOOLS_README|工具说明]]。

| 2026-09-02 快照 | 数量 |
|---|---:|
| `results/` case 目录 | 41 |
| Exact `SUCCESS` | 26 |
| Exact `SEARCH_INCOMPLETE_TIMEOUT` | 1 |
| Exact OFF | 14 |
| 离线概率程序执行成功 | 38 |
| 得到完整实验值 $\hat p^2\hat r\hat q^2$ | 16 |
| 概率程序成功但至少一项达到阈值而跳过 | 22 |
| 因结果信息不足而无法执行概率测试 | 3 |

## 1. 指标定义

设区分器为 $E_1\circ E_m\circ E_0$，轮数配置为 $(r_0,r_m,r_1)$。

| 指标 | 含义 |
|---|---|
| $CAS$ | $E_m$ 中 upper/lower 共同活跃 S-box 数 |
| $W_u$ | upper concrete RKDiff characteristic 的 DDT weight |
| $W_l$ | lower concrete RKDiff characteristic 的 DDT weight |
| $B$ | 采用 $r_{ub}=2^{-2CAS}$ 时整个 boomerang 概率的负二进制指数 |

本文将用户给出的总和指标统一解释为：

$$
B=2W_u+2W_l+2CAS,
\qquad
p^2r_{ub}q^2=2^{-B}.
$$

其中 `理论 $2^{-B}$` 是由 characteristic weight 和 Hadipour common-active 上界得到的估计；`实验总概率` 使用实际采样结果：

$$
P_{boom}^{exp}=\hat p^2\cdot\hat r\cdot\hat q^2.
$$

两列数值不要求相等。采样未覆盖全部 differential、switch 事件，或命中数较小时，实验值会有明显波动。

## 2. 全量结果表

| Case | Exact 状态 | $CAS$ | $W_u$ | $W_l$ | $B=2W_u+2W_l+2CAS$ | 理论 $2^{-B}$ | 实验总概率 | 概率测试 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `0-1-0_636` | OFF | 0 | - | - | - | - | - | 无法测试 |
| `0-2-0` | OFF | - | - | - | - | - | - | 无法测试 |
| `1-1-1` | SUCCESS | 0 | 4 | 4 | 16 | $2^{-16}$ | $2^{-8.000000}$ | 完整 |
| `1-1-1_424` | OFF | 0 | 0 | 0 | 0 | $2^0$ | $2^0$ | 完整 |
| `1-1-1_636` | OFF | 0 | 0 | 0 | 0 | $2^0$ | $2^0$ | 完整 |
| `1-1-2_636` | SUCCESS | 0 | 4 | 2 | 12 | $2^{-12}$ | $2^{-14.000000}$ | 完整 |
| `1-4-1_636` | SUCCESS | 2 | 4 | 0 | 12 | $2^{-12}$ | $2^{-11.052363}$ | 完整 |
| `1-5-1_636` | SUCCESS | 2 | 4 | 4 | 20 | $2^{-20}$ | $2^{-19.103857}$ | 完整 |
| `1-6-1_636` | SUCCESS | 8 | 6 | 4 | 36 | $2^{-36}$ | - | $r$ 跳过 |
| `1-7-1_636` | SUCCESS | 26 | 4 | 6 | 72 | $2^{-72}$ | - | $r$ 跳过 |
| `1-8-1_636` | SUCCESS | 38 | 6 | 6 | 100 | $2^{-100}$ | - | $r$ 跳过 |
| `2-2-2_636` | OFF | 0 | 2 | 4 | 12 | $2^{-12}$ | $2^{-6.712288}$ | 完整 |
| `2-2-7_636` | SUCCESS | 0 | 2 | 14 | 32 | $2^{-32}$ | - | $q$ 跳过 |
| `2-3-2_636` | SUCCESS | 0 | 4 | 8 | 24 | $2^{-24}$ | $2^{-15.782951}$ | 完整 |
| `2-4-2_636` | OFF | 3 | 2 | 8 | 26 | $2^{-26}$ | $2^{-21.826469}$ | 完整 |
| `2-6-2_666` | OFF | 8 | 10 | 12 | 60 | $2^{-60}$ | - | $r$ 跳过 |
| `3-3-3_636` | OFF | 1 | 2 | 6 | 18 | $2^{-18}$ | $2^{-15.356144}$ | 完整 |
| `3-4-3_636` | OFF | 3 | 4 | 12 | 38 | $2^{-38}$ | $2^{-30.315022}$ | 完整 |
| `3-5-2_636` | OFF | 5 | 6 | 8 | 38 | $2^{-38}$ | $2^{-37.014158}$ | 完整 |
| `3-6-2_636` | OFF | 14 | 6 | 8 | 56 | $2^{-56}$ | - | $r$ 跳过 |
| `4-4-4_636` | SUCCESS | 3 | 4 | 16 | 46 | $2^{-46}$ | - | $q$ 跳过 |
| `5-4-3_636` | OFF | 4 | 6 | 8 | 36 | $2^{-36}$ | $2^{-30.186219}$ | 完整 |
| `6-4-3_636` | OFF | 5 | 10 | 8 | 46 | $2^{-46}$ | $2^{-32.416611}$ | 完整 |
| `6-4-4_628` | OFF | 7 | 10 | 12 | 58 | $2^{-58}$ | - | $r$ 跳过 |
| `7-2-2_636` | SUCCESS | 0 | 12 | 2 | 28 | $2^{-28}$ | $2^{-24.186219}$ | 完整 |
| `7-3-6_636` | SUCCESS | 0 | 14 | 16 | 60 | $2^{-60}$ | - | $p$ 跳过 |
| `7-3-7_424` | SUCCESS | 0 | 14 | 18 | 64 | $2^{-64}$ | - | $p$ 跳过 |
| `7-3-7_636` | SUCCESS | 0 | 14 | 19 | 66 | $2^{-66}$ | - | $p$ 跳过 |
| `7-4-3_636` | SUCCESS | 4 | 12 | 10 | 52 | $2^{-52}$ | $2^{-48.993674}$ | 完整 |
| `7-4-4_636` | SUCCESS | 7 | 14 | 8 | 58 | $2^{-58}$ | - | $p$ 跳过 |
| `7-4-5_636` | SUCCESS | 4 | 12 | 18 | 68 | $2^{-68}$ | - | $q$ 跳过 |
| `7-4-6_636` | SUCCESS | 6 | 14 | 18 | 76 | $2^{-76}$ | - | $p$ 跳过 |
| `7-5-4_636` | SUCCESS | 12 | 14 | 12 | 76 | $2^{-76}$ | - | $p$ 跳过 |
| `8-3-4_636` | SUCCESS | 0 | 16 | 8 | 48 | $2^{-48}$ | - | $p$ 跳过 |
| `8-3-5_636` | SUCCESS | 0 | 16 | 12 | 56 | $2^{-56}$ | - | $p$ 跳过 |
| `8-3-6_424` | SUCCESS | 0 | 16 | 16 | 64 | $2^{-64}$ | - | $p$ 跳过 |
| `8-3-6_626` | SUCCESS | 0 | 16 | 16 | 64 | $2^{-64}$ | - | $p$ 跳过 |
| `8-3-6_636` | SUCCESS | 0 | 16 | 16 | 64 | $2^{-64}$ | - | $p$ 跳过 |
| `8-4-3_636` | SUCCESS | 5 | 16 | 10 | 62 | $2^{-62}$ | - | $p$ 跳过 |
| `8-4-4_636` | SUCCESS | 11 | 8 | 12 | 62 | $2^{-62}$ | - | $r$ 跳过 |
| `9-3-5` | SEARCH_INCOMPLETE_TIMEOUT | - | - | - | - | - | - | 无法测试 |

## 3. 概率测试执行结果

### 3.1 完整实验值

共有 16 个 case 同时获得 $\hat p$、$\hat q$ 和 $\hat r$，因此可以计算有限的 $\hat p^2\hat r\hat q^2$。实验值已经列入上表。

### 3.2 部分跳过

共有 22 个 case 的离线概率程序正常完成，但至少一项所需数据量满足：

$$
N\ge 2^{16},
$$

因此按当前项目规则跳过该项实验，不能计算完整实验总概率。差分实验采用 $2^{\lceil W\rceil+2}$ 数据；Em 实验采用 $\max(2^{12},2^{2CAS+2})$ 数据。

### 3.3 无法测试

| Case | 原因 |
|---|---|
| `0-1-0_636` | 只有 Em，upper/lower concrete trail 均为空；当前完整 boomerang 概率入口要求读取两侧路径 |
| `0-2-0` | 缺少正式结果 JSON，无法恢复密钥状态对齐所需字段 |
| `9-3-5` | Exact 搜索结果为 `SEARCH_INCOMPLETE_TIMEOUT`，没有最终 accepted upper/lower characteristic，也没有可回退的正式结果 JSON |

以上三个目录均已实际调用离线入口，并在对应 `probability_results/<case>/summary.json` 中保存 `FAILURE` 和异常原因。

## 4. 结果解读

1. `Exact SUCCESS` 表示 upper/lower concrete characteristic 已通过各自的 Z3 SAT 和 ordinary-Python replay；`Exact OFF` 不代表 characteristic 已被证明真实可实现。
2. 理论指标 $B$ 使用 $r_{ub}=2^{-2CAS}$。它是 Hadipour common-active 口径下的概率指数，不是随机实验直接测得的指数。
3. `1-1-1` 的理论值为 $2^{-16}$，本次实验值为 $2^{-8}$；这种差异说明采样测量的是输入输出 differential effect，而非只包含单条 MILP characteristic 的概率。
4. 实验命中数较少时方差较大。表格中的实验值只代表本次以种子 `20260902` 得到的观测值。
5. `CAS=0` 只表示当前模型中没有 upper/lower 共同活跃 S-box，不单独构成一般性的 $r=1$ 证明。

## 5. 数据入口

- 搜索主结果：`results/<r0>-<rm>-<r1>_<w0><wm><w1>/.json/<r0>-<rm>-<r1>.json`
- Exact 总结：`results/<case>/exact_summary.json`
- Accepted trail：`results/<case>/truncated_XXXX/{upper,lower}/accepted.json`
- 概率实验总结：`probability_results/<case>/summary.json`
- 概率实验完整终端输出：`probability_results/<case>/terminal_print.txt`
- 离线运行命令：`python run/probtest_from_results.py --result-dir .\results\<case>`
