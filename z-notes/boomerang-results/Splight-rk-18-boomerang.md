---
title: Splight 18轮 RK-Boomerang 结果汇总
aliases:
  - Splight-rk-18-boomerang
tags:
  - Splight
  - related-key
  - boomerang
  - 18-round
  - experiment
date: 2026-09-23
data_source: results, run-logs
sort_key: estimated_probability_interval
---

# Splight 18轮 RK-Boomerang 结果汇总

本文汇总 `results/` 中全部总轮数为18轮的相关密钥 boomerang 搜索结果。截至2026-09-23，共有12组配置：7组为 `Exact SUCCESS`，5组为 `GLOBAL_TIME_LIMIT`。

18轮完整重跑队列于2026-09-22执行，12个任务全部启动，7组写出 `SUCCESS`，5组在1200秒全局上限处超时。原计划中跳过的 `8-2-8_636` 在本轮已按修正后的目标重新搜索。

## 1. 指标与排序口径

设区分器轮数为 $(r_0,r_m,r_1)$，满足：

$$
r_0+r_m+r_1=18.
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

主表按预估概率从大到小排列：先按 $B_{best}$ 从小到大，再按 $B_{worst}$ 从小到大，最后按 Case 名称字典序。为与全轮数总表保持一致，同时给出：

$$
S=2(W_u+W_l+2CAS).
$$

> $S$ 只作为总表中的排序分数，不等于模型概率指数。无完整 concrete 结果的配置不参加排名，放在 SUCCESS 表之后。

## 2. 全部18轮结果

| 排名 | Case | Exact状态 | $W_u$ | $W_l$ | $CAS$ | $S$ | 预估概率 | 求解时间（s） | 结果 |
|---:|---|---|---:|---:|---:|---:|---|---:|---|
| 1 | `8-2-8_636` | SUCCESS | 8 | 18 | 2 | 60 | $[2^{-57},2^{-56}]$ | 53.481957 | [结果](../../results/8-2-8_636/) · [区分器 md](../../results/8-2-8_636/8-2-8_distinguisher.md) |
| 2 | `7-2-9_636` | SUCCESS | 12 | 18 | 0 | 60 | $2^{-60}$ | 306.950626 | [结果](../../results/7-2-9_636/) · [区分器 md](../../results/7-2-9_636/7-2-9_distinguisher.md) |
| 3 | `8-3-7_636` | SUCCESS | 8 | 22 | 3 | 72 | $[2^{-67.5},2^{-66}]$ | 10.753160 | [结果](../../results/8-3-7_636/) · [区分器 md](../../results/8-3-7_636/8-3-7_distinguisher.md) |
| 4 | `8-4-6_636` | SUCCESS | 8 | 18 | 10 | 92 | $[2^{-77},2^{-72}]$ | 7.613572 | [结果](../../results/8-4-6_636/) · [区分器 md](../../results/8-4-6_636/8-4-6_distinguisher.md) |
| 5 | `7-4-7_636` | SUCCESS | 12 | 22 | 4 | 84 | $[2^{-78},2^{-76}]$ | 14.854537 | [结果](../../results/7-4-7_636/) · [区分器 md](../../results/7-4-7_636/7-4-7_distinguisher.md) |
| 6 | `7-5-6_636` | SUCCESS | 12 | 18 | 12 | 108 | $[2^{-90},2^{-84}]$ | 18.826716 | [结果](../../results/7-5-6_636/) · [区分器 md](../../results/7-5-6_636/7-5-6_distinguisher.md) |
| 7 | `6-5-7_636` | SUCCESS | 12 | 16 | 14 | 112 | $[2^{-91},2^{-84}]$ | 218.003049 | [结果](../../results/6-5-7_636/) · [区分器 md](../../results/6-5-7_636/6-5-7_distinguisher.md) |

### 2.1 未完成配置

| Case | Exact状态 | 求解时间（s） | 结果 |
|---|---|---:|---|
| `5-5-8_636` | GLOBAL_TIME_LIMIT | 1200.159122 | [结果](../../results/5-5-8_636/) |
| `6-4-8_636` | GLOBAL_TIME_LIMIT | 1200.158384 | [结果](../../results/6-4-8_636/) |
| `7-3-8_636` | GLOBAL_TIME_LIMIT | 1200.172687 | [结果](../../results/7-3-8_636/) |
| `8-5-5_636` | GLOBAL_TIME_LIMIT | 1200.168954 | [结果](../../results/8-5-5_636/) |
| `9-2-7_636` | GLOBAL_TIME_LIMIT | 1200.176076 | [结果](../../results/9-2-7_636/) |

这五组在1200秒全局上限内没有写出通过的 concrete characteristic，不能用来断言不存在区分器。

## 3. 概率阈值分类

### 3.1 整个区间严格高于随机基线

| Case | 概率区间 | 相对 $2^{-64}$ 的保守余量 |
|---|---|---:|
| `8-2-8_636` | $[2^{-57},2^{-56}]$ | 7 bit |
| `7-2-9_636` | $2^{-60}$ | 4 bit |

这两组满足 $B_{worst}<64$，是当前18轮中值得继续执行精确 switch 概率或独立采样验证的候选。

### 3.2 已完成但低于随机基线

其余5组 SUCCESS 配置的乐观界已经低于 $2^{-64}$。其中 `8-3-7_636` 最接近阈值，但区间上界只有 $2^{-66}$，仍差2 bit。

### 3.3 未完成配置

5组 `GLOBAL_TIME_LIMIT` 配置均在1200秒上限处停止，没有最终 `exact_summary.json` 的成功结果。该状态只能解释为搜索未完成，不能作为不存在区分器的证明。`9-2-7_636` 与已成功的 `7-2-9_636` 构成方向对照。

## 4. 结构观察

1. 18轮已确认存在两个预估概率严格超过 $2^{-64}$ 的 RK-BD：`8-2-8_636` 与 `7-2-9_636`。
2. `7-2-9_636` 具有 $CAS=0$，概率为确定的 characteristic 估计 $2^{-60}$，没有 switch 区间不确定性。
3. `9-2-7_636` 与 `7-2-9_636` 呈现强烈方向不对称：前者在1200秒内未得到 accepted result，后者得到 $2^{-60}$。
4. $r_m=3$ 的最佳结果是 `8-3-7_636`，其 $CAS=3$ 且上界为 $2^{-66}$；增加中间轮数已经越过随机基线。
5. $r_m=4$ 和 $r_m=5$ 的已完成配置全部低于阈值，主要由 concrete outer weight 与 $CAS$ 同时增长造成。
6. `7-2-9_636` 不在原严格活跃 S-box 初筛集合内却获得有效结果，说明轮数—活跃数表适合作为测试排序锚点，不适合作为绝对排除条件。
7. 表中“预估概率”均为 characteristic 与 switch 上下界口径的估计，尚未用独立采样实验替换。

## 5. 队列执行摘要

统计来自2026-09-22的18轮队列运行记录，数字按当前日志重新计算。

| 项目 | 数量 |
|---|---:|
| 队列中计划项目 | 12 |
| 因已有 Exact SUCCESS 跳过 | 0 |
| 新完成且 Exact SUCCESS | 7 |
| 队列超时或失败 | 5 |
| 队列累计运行时间 | 约1小时50分35秒 |

## 6. 数据入口

- 18轮结果目录：[`results/`](../../results/)
- Exact 总结：`../../results/<case>/exact_summary.json`
- 搜索终端日志：`../../results/<case>/terminal_print.txt`
- 18轮队列日志：[`run_18_636_recommended_queue.log`](../../run/run_18_636_recommended_queue.log)
- 队列独立案例日志：[`run/logs/run_18_636_recommended_queue/`](../../run/logs/run_18_636_recommended_queue/)
- 全轮数汇总：[[Splight-rk-boomerang实验结果]]
