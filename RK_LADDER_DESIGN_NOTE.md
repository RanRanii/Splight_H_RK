# RK-ladder 中间密钥侧互斥约束设计说明

- 日期：2026-10-15
- 范围：仅说明 `rk-ladder` 模式在中间段（$E_m$）密钥侧公共 activity 上的互斥约束设计意图与其解释边界。
- 性质：设计意图说明。本轮不修改任何约束、求解模型、模式定义、目标函数或历史结果。
- 相关审计：`paper_write/draft/planning/g4_risk_review/g4_r2_t10_constraints.md`（保留原始记录）；本说明是对该项判断口径的补充确认。

## 1. 设计意图

`rk-ladder` 在中间段对 upper / lower 两条路径的 key-core 非线性位置施加互斥约束

$$
u + v \le 1,
$$

其目的是排除“上下路径在同一个 key-core S-box 位置同时活跃”的配置。该约束是**有意设计**，用于刻画相关密钥 boomerang 在中间段的对齐要求，而不是实现遗漏。

因此本说明明确：**不把 ladder 的互斥约束本身判为错误**，也不修改 `rk-basic` / `rk-ladder` 模式划分。

## 2. 约束的代码位置

文件：`rktruncboom.py`

- `generate_common_active_constraints()`：为中间每一轮生成状态侧公共 activity 变量 $s_{r,j}$（每轮 16 个）与密钥侧公共 activity 变量 $ks\_common_{r,j}$（每轮 2 个，对应 key core 的第 3、7 个 nibble）。三类等式约束把公共 activity 定义为两侧 activity 的合取：

$$
s = u \land v \iff u - s \ge 0,\; v - s \ge 0,\; -u - v + s \ge -1 .
$$

- 同一函数内对密钥侧变量追加互斥不等式 $u + v \le 1$。
- `generate_key_ladder_constraints()`：在 `rk_mode == "rk-ladder"` 时对同一变量对再次追加同一个不等式。
- `make_model()`：依次调用上述两个生成函数，再调用 `exclude_trivial_solution()`。

代码事实（可独立核对）：该互斥不等式已无条件写入公共生成函数，ladder 函数重复追加同一不等式。因此在本仓库当前代码下，`rk-basic` 与 `rk-ladder` 的约束集合只差重复行，投影到模型变量后的可行域相同。该事实作为代码观察保留；按第 1 节的确认，它属于设计意图下的实现形态，不构成本轮认定的缺陷，不做修改。

## 3. 逻辑后果：密钥侧公共 activity 恒为零

密钥侧公共 activity 由合取约束定义，即 $c^{K} = u \land v$。与互斥约束 $u+v \le 1$ 联立后，$u$ 与 $v$ 不可能同时取 1，于是任一可行解中

$$
c^{K} \equiv 0 .
$$

局部可行赋值只剩 $(u,v,c^{K}) \in \{(0,0,0),\,(1,0,0),\,(0,1,0)\}$。

## 4. CAS 的口径

`middle_part.common_active_sboxes` 在定义上是状态侧计数与密钥侧计数之和：

$$
\mathrm{CAS} = \sum_{r} s_{r} + \sum_{r} c^{K}_{r},
$$

并按 $\mathrm{CAS}$、`common_active_state_sboxes`、`common_active_key_sboxes` 三个字段分别保存。

在当前 `rk-ladder` 设定下，密钥侧分项恒为零，因此

$$
\mathrm{CAS} = \text{状态侧公共活跃 S 盒数}.
$$

已报告记录的实测行为与之一致：本仓库 `results/*/exact_summary.json` 中保存的 `common_active_key_sboxes` 均为 0。

## 5. 解释边界

需要与下述陈述保持区分，避免过度外推：

1. 互斥约束只作用于**中间段对齐轮**的 key-core 公共活跃计数，它**不**表示密钥编排的差分传播影响消失。
2. 密钥编排的差分传播仍由 key schedule 约束与 key-core 的 DDT 权重刻画；具体差分模型中密钥编排 S 盒的 DDT 权重仍计入两侧具体权重，lower 侧为构造全局密钥状态而产生的前置密钥编排步骤受约束但不计入目标。
3. 因此本说明不声明“全部密钥差分传播影响均消失”，也不声明密钥编排差分在中间段“没有代价”。
4. 该约束是当前模型的建模选择；它是关于本模型的性质，不是关于 Splight 密钥编排本身的普适定理。
5. 由于互斥约束确实排除了一类配置，相对不含该约束的模型而言当前可行域更紧；本说明不据此推断被排除配置在真实密码意义上不可行。

## 6. 本轮未执行的操作

- 未修改 `rktruncboom.py`、`rktruncdiff.py`、`rkdiff.py`、`keydiff.py`、`rkboom.py` 及任何概率评估器。
- 未修改 `rk-basic` / `rk-ladder` 模式定义。
- 未重新运行 MILP、SAT/SMT 或 RK 搜索。
- 未改写任何历史结果文件或历史审计记录。
