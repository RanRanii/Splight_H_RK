# Em 相关密钥 boomerang switch 概率测试原理

本文说明 `Test/Splight-H-RK` 中 `rkboom.py --probtest t` 的 Em 中间相关密钥 boomerang switch 概率测试方式。对应实现文件为 `probability/rk_probability_evaluator.py`，底层随机实验调用 `Splight_implement/implement_py/probability_tests/probability_test.py` 的 `mode=rkboomerang`。

Key schedule 差分状态由独立文件 `keydiff.py` 建模和求解。该模型是 bit-level MILP，LP 文件统一写入：

```text
tmp/keydiff/
```

## 测试对象

区分器按三段划分：

```text
E = E1 o Em o E0
rounds = r0 + rm + r1
```

`rkboom.py` 先实例化两条具体相关密钥差分路径：

```text
upper: E0，轮数 r0
lower: E1，轮数 r1
```

Em 概率测试只测试中间 `rm` 轮，不测试完整 `r0+rm+r1` 轮。测试使用：

```text
Delta = upper 路径输出差分 = diff_upper_trail[x_r0]
nabla = lower 路径输入差分 = diff_lower_trail[x_0]
```

## 相关密钥 boomerang 四密钥结构

`mode=rkboomerang` 使用四个相关密钥状态：

```text
Ka = random 128-bit key state
Kb = Ka xor delta_key_diff
Kc = Ka xor nabla_key_diff
Kd = Kb xor nabla_key_diff
   = Ka xor delta_key_diff xor nabla_key_diff
```

对每个随机样本，实验流程为：

```text
P0 = random 64-bit state
P1 = P0 xor Delta

C0 = Em(P0, Ka)
C1 = Em(P1, Kb)

C2 = C0 xor nabla
C3 = C1 xor nabla

Q0 = Em^{-1}(C2, Kc)
Q1 = Em^{-1}(C3, Kd)

若 Q0 xor Q1 == Delta，则该 quartet 返回成功。
```

估计概率为：

```text
r = returned_count / data_size
```

## delta_key_diff 如何得到

`delta_key_diff` 表示 upper 方向进入 Em 起点时的 128-bit key state 差分。它不是直接使用 upper 的 `master_key_diff`，而是将 upper 具体路径的主密钥差分按 Splight key schedule 差分正向推导 `r0` 轮：

```text
delta_key_diff = KeyScheduleMILPForward(diff_upper_trail[master_key_diff], r0)
```

以 `2-2-2` 为例，`r0=2`，因此：

```text
固定 ks_0 = upper_master_key_diff
调用 keydiff.py 建立 2 轮 bit-level key schedule MILP
最小化 key-core S-box DDT weight
求解后取 ks_2 作为 delta_key_diff
```

这样得到的是 E0 结束、Em 开始处的 128-bit key schedule 状态差分。

## nabla_key_diff 如何得到

`nabla_key_diff` 表示 lower 方向在 Em 起点需要使用的 128-bit key state 差分。对于已经实例化出的 lower 具体路径，不能直接把 `master_key_diff` 当成 Em 末端状态；`master_key_diff` 是全局 `ks_0`。实际需要固定的是 lower 路径在 E1 起点、也就是 Em 末端的 key state：

```text
nabla_key_diff = KeyScheduleMILPBackward(diff_lower_trail[ks_global_{r0+rm}], rm)
```

以 `2-2-2` 为例，`r0=2, rm=2`，因此：

```text
固定 ks_2 = diff_lower_trail[ks_global_4]
调用 keydiff.py 建立 2 轮 bit-level key schedule MILP
最小化 key-core S-box DDT weight
求解后取 ks_0 作为 nabla_key_diff
```

它用于 `mode=rkboomerang` 中的 `Kc = Ka xor nabla_key_diff` 和 `Kd = Kb xor nabla_key_diff`。

## Splight key schedule 差分传播

Splight 的 128-bit key state 写成四个 32-bit 分支：

```text
K^i = k0^i || k1^i || k2^i || k3^i
```

真实 key schedule 为：

```text
k0^i = f(k0^{i-1}) xor k1^{i-1} xor C_{i-1}
k1^i = k2^{i-1}
k2^i = k3^{i-1}
k3^i = k0^{i-1}
RK_{i-1} = k0^i
```

轮常数 `C_i` 是固定常数，差分为 0，因此不进入差分传播。

key core `f` 中第 3、7 个 nibble 经过 S-box。当前概率测试不会把这些 S-box 的输出差分直接设为 0，而是为 key schedule 单独建立 bit-level MILP。

`keydiff.py` 的 `fixedVariables` 是可选输入。若传入固定项，模型会固定对应变量；若没有传入，则不额外固定 key state。支持的固定方式包括：

```text
ks_0 = 128-bit key state difference
ks_2 = 128-bit key state difference
ks_0_3 = one nibble difference
ks_0_3_2 = one bit difference
```

在 Em 概率测试中：

```text
delta_key_milp: fixedVariables = { "ks_0": upper_master_key_diff }
nabla_key_milp: fixedVariables = { "ks_rm": lower_E1_input_key_state_diff }
```

设输入 key 差分为：

```text
D = d0 || d1 || d2 || d3
```

其中每个 `d*` 是 32-bit。正向一轮 key schedule 差分结构为：

```text
d0' = key_core_diff(d0) xor d1
d1' = d2
d2' = d3
d3' = d0
```

反向一轮结构为：

```text
d0 = d3'
d1 = d0' xor key_core_diff(d0)
d2 = d1'
d3 = d2'
```

其中 `key_core_diff(d0)` 的第 3、7 个 nibble 不是固定值，而是通过 S-box DDT 约束求解。MILP 中每个 key-core S-box 使用 selector 变量选择一个合法 DDT 转移：

```text
sum selector(dx, dy) = 1
input_bits  = bits(dx)
output_bits = bits(dy)
weight     += -log2(DDT[dx][dy] / 16)
```

非 S-box nibble 使用等式传播。XOR 使用 bit-level XOR 线性约束。目标函数是所有 key-core S-box DDT weight 的和：

```text
minimize sum key_sbox_weight
```

求解器返回一个可行且在当前 MILP 目标下最小的 key schedule 差分路径。`rk_probability_evaluator.py` 会把求解得到的状态序列保存到：

```text
rk_probability_tests.json:
  rk_em_boomerang.delta_key_milp.states
  rk_em_boomerang.nabla_key_milp.states
  rk_em_boomerang.delta_key_milp.lp_file
  rk_em_boomerang.nabla_key_milp.lp_file
```

## 与截断模型中 CAS 的关系

截断 boomerang 模型会统计 Em 中 common active S-box 数量：

```text
CAS = sum(common_active_sbox)
```

Hadipour 风格估计通常给出：

```text
2^(-2.5 * CAS) <= r <= 2^(-2 * CAS)
```

该区间只用于搜索阶段的粗粒度估计。`--probtest t` 输出的 `estimated_r` 是在真实 Splight reduced-round 实现上，以固定 `Delta`、`nabla`、`delta_key_diff`、`nabla_key_diff` 做 Monte Carlo 得到的实验值。两者可能不同。

## 当前采样规则

Em 测试的 data size 由 common active S-box 数量决定：

```text
em_weight = 2 * CAS
data_size = max(2^12, 2^(ceil(em_weight) + 2))
```

若 `data_size >= 2^16`，则跳过实验，避免长时间随机测试。

随机种子默认为当天日期：

```text
YYYYMMDD
```

## 输出位置

运行：

```bash
python rkboom.py -r0 2 -rm 2 -r1 2 --probtest t
```

会在对应结果目录中写入：

```text
results/2-2-2/rk_probability_tests.json
results/2-2-2/rk_probability_tests.txt
```

Em 部分会明确打印：

```text
delta key diff: ... (key_schedule_milp_forward(diff_upper_trail[master_key_diff], r0=...))
nabla key diff: ... (key_schedule_milp_backward(diff_lower_trail[ks_global_{r0+rm}], rm=...))
```
