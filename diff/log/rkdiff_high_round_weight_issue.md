# RKDiff 高轮数真实 weight 异常问题记录

## 问题现象

在 `Test/Splight-H-RK/diff/rkdiff_round_sweep_summary.md` 中，早期汇总曾把 22 轮以后 `rkdiff.py` 的结果显示为：

```text
22 rounds: weight = 1147
23 rounds: weight = 1197
24 rounds: weight = 1240
25 rounds: weight = 1303
26 rounds: weight = 1363
```

这个数值明显不合理。Splight 的 4-bit S-box 单个差分 transition 的权重不可能产生几十甚至上百的贡献；按当前 S-box DDT，非零 transition 的权重只有 2 或 3。

## 核查 1：S-box 不等式本身

已用 `splight/splight_spec.py` 中的 `SBOX_SPLIGHT_S3` 枚举 DDT，并对 `rkdiff.py`/`keydiff.py` 当前固定不等式进行逐 transition 检查。

检查结果：

```text
DDT count = 16 -> true weight 0 -> encoded best sum(pr) = 0，共 1 个
DDT count = 4  -> true weight 2 -> encoded best sum(pr) = 2，共 24 个
DDT count = 2  -> true weight 3 -> encoded best sum(pr) = 3，共 72 个
bad transition count = 0
```

结论：

- 当前 Splight S-box 不等式没有发现单 S-box 权重编码错误。
- `sum(pr0, pr1, pr2)` 与 DDT 权重一致。
- 因此“1000+ weight”不是单个 S-box 约束生成了异常大权重。

## 核查 2：高轮数结果的来源

检查 `round_20_rkdiff.json` 到 `round_26_rkdiff.json` 后发现：

```text
20: status=TIME_LIMIT, obj=248
21: status=TIME_LIMIT, obj=260
22: status=TIME_LIMIT, obj=1147
23: status=TIME_LIMIT, obj=1197
24: status=TIME_LIMIT, obj=1240
25: status=TIME_LIMIT, obj=1303
26: status=TIME_LIMIT, obj=1363
```

这些结果全部是 `TIME_LIMIT`，不是 `OPTIMAL`。

进一步检查每轮贡献：

```text
22: total_rw=1015, total_kw=132
23: total_rw=1059, total_kw=138
24: total_rw=1096, total_kw=144
25: total_rw=1153, total_kw=150
26: total_rw=1207, total_kw=156
```

22 轮以后的 `pr` 每轮尾部接近：

```text
pr_tail ~= -53, -51, -52, -47, -44
```

这接近一轮中所有 S-box 的最大编码上限：

```text
每轮状态 S-box: 16 个
每轮密钥调度 S-box: 2 个
每个 S-box pr 有 3 个 binary bit
理论上限约为 18 * 3 = 54
```

也就是说，高轮数 `TIME_LIMIT` 下 Gurobi 只找到非常差的可行解，很多 S-box 的 `pr` 位接近全 1，因此目标值会突然升到 1000 以上。

## 根因

根因不是 S-box 权重建模错误，而是结果解释错误：

1. `rkdiff.py` 在 `TIME_LIMIT` 且 `SolCount > 0` 时，会返回当前 incumbent。
2. 当前 incumbent 只是限时内找到的可行解，不是最优差分路径。
3. 原汇总脚本把 `TIME_LIMIT` 下的 incumbent 也放进 `真实 weight` 一列，导致看起来像“真实最小 weight 超过 1000”。
4. 实际上这些数值不能作为真实最小 weight 使用。

## 已修正的展示方式

已修改 `diff/run_rkdiff_round_sweep.py` 的汇总表生成逻辑：

- 只有 `real_status == OPTIMAL` 的值才进入 `已证明真实 weight`。
- `real_status == TIME_LIMIT` 的值只放入 `TIME_LIMIT incumbent`。
- `NOT_RUN` 的轮数显示为未测试。

新的表头为：

```text
轮数 | 截断状态 | 截断活跃 S-box 数 | 真实差分状态 | 已证明真实 weight | TIME_LIMIT incumbent | 说明
```

这样可以避免把限时可行解误读为真实最优 weight。

## 当前结论

- 0 到 6 轮 `rkdiff.py` 为 `OPTIMAL`，这些真实 weight 可以采用。
- 7 轮及以后目前多为 `TIME_LIMIT`，不能作为真实最小 weight。
- 22 轮以后出现 1000+，是因为限时 incumbent 很差，不是 S-box 权重真的突增。
- 目前更高轮数只应继续统计 `rktruncdiff.py` 的活跃 S-box 个数；不应把未证明最优的 bit 级 `rkdiff` incumbent 当作真实 weight。

## 建议

后续若需要高轮数真实 weight，应采用以下方式之一：

1. 不使用固定 120 秒限时结果作为真实 weight，只保留 `OPTIMAL` 轮。
2. 对高轮数增加更强的截断差分约束或固定模式后再实例化 bit 级差分。
3. 在汇总中同时记录 `ObjBound` 和 `MIPGap`，明确区分 incumbent 与已证明最优。
4. 高轮数分析优先使用 `rktruncdiff.py` 的活跃 S-box 下界，不直接运行无约束 bit 级 `rkdiff.py`。
