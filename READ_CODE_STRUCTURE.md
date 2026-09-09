# Splight-H-RK 代码结构说明

本目录只保留相关密钥版本的搜索、概率测试和必要的 Splight 基础实现。单密钥版本的 `diff.py`、`truncdiff.py`、`truncboom.py`、旧概率测试和旧运行脚本已经删除。

## 主入口

- `rkboom.py`：Hadipour 方法版相关密钥 boomerang / sandwich 主入口。先搜索截断 sandwich，再实例化 `E0` 和 `E1` 的具体相关密钥差分路径；可用 `--probtest t` 启用概率实验。
- `rkboom_full.py`：长区间实例化入口。先搜索同一个截断 sandwich，再分别实例化 `E0+Em` 和 `Em+E1`，最后输出全局轮合并表。
- `tools/rkdiff_cli.py`：单独调用 `RKDiff` 搜索指定轮数相关密钥差分路径的 CLI。

## 模型文件

- `rktruncdiff.py`：nibble-level 相关密钥截断差分传播。
- `rktruncboom.py`：Hadipour 三段 sandwich 截断模型，包含 upper、lower、common active S-box 和 `rk-ladder` 约束。
- `rkdiff.py`：bit-wise 相关密钥具体差分 MILP，包含状态差分、128-bit key schedule 差分、round key 差分和 S-box DDT weight。
- `keydiff.py`：只针对 Splight key schedule 差分传播的 bit-wise MILP。`fixedVariables` 是可选输入；如果传入，例如 `{"ks_0": "...", "ks_2": "..."}` 或 `{"ks_0_3_2": 1}`，模型会固定对应变量；如果不传，则不额外固定 key state。

`rkdiff.py` 输出中：

- `master_key_diff` 是 `ks_0`，即 128-bit 主密钥差分。
- `ks_global_i` 是从该主密钥差分出发按 key schedule 推导到第 `i` 次 key update 前后的全局 key state 差分，用于检查和调试。
- `round_offset` 用于让 lower 路径使用全局轮号对应的 round key。

## 概率测试

- `probability/rk_probability_evaluator.py`：`rkboom.py --probtest t` 调用的 RK 概率测试模块。
- `probability/RK_EM_PROBABILITY_TEST_PRINCIPLE.md`：Em 相关密钥 boomerang switch 概率测试原理说明。

概率测试分三部分：

- upper：测试 `r0` 轮相关密钥差分概率。
- lower：测试 `r1` 轮相关密钥差分概率。
- Em：调用 `Splight_implement/implement_py/probability_tests/probability_test.py` 的 `mode=rkboomerang`，只测试中间 `rm` 轮 switch 概率。

Em 测试的 key diff 来源：

```text
delta_key_diff = keydiff.py 固定 upper master_key_diff 后正向求解 r0 轮得到的 ks_r0
nabla_key_diff = keydiff.py 固定 lower master_key_diff 后反向求解 rm 轮得到的 ks_0
```

`keydiff.py` 生成的 LP 文件写入：

```text
tmp/keydiff/
```

## Splight 基础实现

`splight/` 目录保留，因为 `rkdiff.py` 和测试依赖它：

- `splight/splight_spec.py`：S-box、线性层和 nibble/bit 工具。
- `splight/sbox_constraints.py`：S-box DDT 和 weight 约束。
- `splight/splight_cipher.py`：基础 reduced-round Splight 实现。

`output/plotdistinguisher.py` 保留，用于生成区分器 Markdown。

## 批量脚本

`run/` 目录只保留 RK 相关脚本：

- `run/run_rkdiff_rounds.py`：测试 2 到 11 轮相关密钥差分最小 weight。
- `run/run_em_only_sweep.py`：调用 `rkboom.py --probtest t` 扫描 `0-n-0` 的 RK Em-only 情况。
- `run/run_1_n_1_sweep.py`：调用 `rkboom.py --probtest t` 扫描 `1-n-1`。
- `run/run_total_10_11_sweep.py`：调用 `rkboom.py --probtest t` 汇总总轮数为 10、11 的组合。

## 输出目录

主结果默认写入：

```text
results/r0-rm-r1/
```

主要文件包括：

```text
r0-rm-r1.json
r0-rm-r1.txt
r0-rm-r1_distinguisher.md
upper_diff_trail.json
upper_diff_trail.txt
lower_diff_trail.json
lower_diff_trail.txt
rk_probability_tests.json
rk_probability_tests.txt
```

`rkboom_full.py` 额外输出：

```text
full_span_boomerang.json
full_span_boomerang.txt
full_span_boomerang.md
```

LP 文件写入：

```text
tmp/splight_h_rk_{r0}_{rm}_{r1}_{rk_mode}.lp
tmp/boomerang/*.lp
```
