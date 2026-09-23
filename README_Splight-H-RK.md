# Splight-H-RK

Splight-H-RK 是 Splight 分组密码的相关密钥差分、boomerang / sandwich 区分器自动搜索与实验分析目录。项目以 Gurobi MILP 为核心：先搜索 nibble 级截断结构，再把 upper / lower 路径实例化为 bit 级相关密钥差分 characteristic，并可调用参考实现进行 Monte Carlo 概率实验、密钥调度分析和结果可视化。

本 README 以 2026-08-30 的实际目录和源码为准，是当前目录的主说明文档。 `READ_CODE_STRUCTURE.md` 是较早的简版结构说明，其中提到的部分旧批处理脚本目前已不存在。

## 1. 项目范围

本目录研究的 Splight 参数与状态约定如下：

| 项目 | 约定 |
|---|---|
| 分组长度 | 64 bit，16 个 nibble |
| 分支长度 | 32 bit，8 个 nibble |
| 主密钥长度 | 128 bit，32 个 nibble |
| 状态顺序 | `L || R` |
| 默认完整轮数 | 32 |
| S 盒 | Splight S3：`A D C F 9 E 1 0 7 2 5 4 3 6 B 8` |
| bit 顺序 | nibble 内 MSB first |
| 求解器 | Gurobi MILP |

一轮加密差分模型对应：

```text
L --S--> y --M--> l --xor RK--> ak --S--> z --xor R--> SHI2 --> L'
\-----------------------------------------------------------------> R'=L
```

密钥调度状态写成 `K^i = k0^i || k1^i || k2^i || k3^i`，每个分支为 32 bit：

```text
new_k0 = SHI1(key_core(k0)) xor k1 xor C_i
new_k1 = k2
new_k2 = k3
new_k3 = k0
RK_i   = new_k0
```

轮常数对 XOR 差分为 0。 `key_core` 的第 3、7 个 nibble 经过 S 盒，然后按 nibble 左循环移位 1 位。

## 2. 可以完成的任务

| 任务 | 入口 | 主要输出 |
|---|---|---|
| 搜索三段相关密钥 boomerang / sandwich 截断结构 | `rkboom.py` | `results/<r0-rm-r1_w0wmw1>/` |
| 将 E0、E1 分别实例化为具体相关密钥差分 characteristic | `rkboom.py` 内部调用 `RKDiff` | `upper_diff_trail.*`、`lower_diff_trail.*` |
| 实例化长区间 `E0+Em` 与 `Em+E1` | `rkboom_full.py` | `full_span_boomerang.*` |
| 搜索指定轮数的最小 weight 相关密钥差分 | `tools/rkdiff_cli.py` | 指定输出目录中的 JSON/TXT |
| 单独求解密钥调度差分 | `keydiff.py` | 终端 JSON 或 `--output` 文件 |
| 评估 upper / lower 外部差分概率与 Em switch 概率 | `rkboom.py --probtest t` | `rk_probability_tests.*` 等 |
| 直接统计某一轮 round-key 差分分布 | `probability/test_key_schedule_diff.py` | 终端统计结果 |
| 批量扫描截断活跃 S 盒数和具体差分 weight | `diff/*.py`、`run/run_rkdiff_rounds.py` | `diff/` 或 `results/rkdiff_2_11/` |
| 生成 Markdown、ASCII 和 TeX 区分器表示 | `output/plotdistinguisher.py` | `*_distinguisher.md`、`bmd.tex` |
| 检查 S 盒 DDT、线性层、移位和加解密互逆性 | `pytest` | 测试报告 |

## 3. 模型与验证边界

### 3.1 截断 MILP

`rktruncdiff.py` 和 `rktruncboom.py` 中每个 nibble 只记录“零差分 / 非零差分”，用于快速搜索活跃 S 盒结构、upper / lower 传播和 Em 中的 common active S-box。

### 3.2 bit 级差分 MILP

`rkdiff.py` 和 `keydiff.py` 将每个差分 nibble 展开为 4 个二进制变量，使用 S 盒 DDT 支撑与概率 weight 不等式，能够输出完整的差分 characteristic、密钥状态差分、round-key 差分和局部概率权重。

这里的“bit 级”仍然表示差分 bit，而不是两条真实执行路径的具体值。模型保证每个局部 S 盒转换在 DDT 中非零，但不保证存在同一对明文和主密钥，使所有轮的局部 S 盒见证值同时成立。因此：

- MILP 的 `OPTIMAL` 表示差分模型中的最优解，不等价于已经找到一对真实数据；
- `total_weight` 是局部 DDT weight 的求和；
- `rkboom.py --exact-verify` 只接受通过完整具体值 SAT/SMT/Z3 验证且 replay 通过的多轮 characteristic；未开启该开关时保持原有首个 MILP concrete trail 流程；
- `--probtest t` 检查的是外部输入/输出差分命中率，不要求命中 MILP 给出的每一个内部差分分支。

项目中的 7-4-3 分析记录已经展示过“每个单轮局部可行，但多轮具体值集合不相交”的情况，详见 `diff/log/rkdiff_7_4_3_round6_zero_analysis.md`。开启 `--exact-verify` 后，UNSAT 候选只在当前 `RKDiff` 中按完整 concrete bit assignment 排除；当前 concrete 空间耗尽或超时时，再在同一个截断模型中排除完整 activity pattern 并搜索下一条截断路径。UNKNOWN 不作为 UNSAT，也不会对该 concrete candidate 添加 no-good。

### 3.3 求解状态

- `OPTIMAL`：已证明当前目标最优。
- `TIME_LIMIT`：仅表示限时内存在 incumbent；不能把它当作已证明的最小 weight。
- `INFEASIBLE`：在当前固定条件下无 MILP 差分解。
- `INTERRUPTED`：求解被中断；只有存在 `SolCount` 时才可能保留可行解。

## 4. 主工作流

```text
命令行 / YAML 参数
        |
        v
RKTruncatedBoomerang
  |- upper: E0 + Em 截断传播
  |- lower: Em + E1 截断传播
  `- common state/key active S-box 与 rk-ladder
        |
        v
--exact-verify 未开启
  `- 分别输出 E0、E1 的首个 RKDiff concrete trail

--exact-verify 已开启
  |- 外层：同一截断模型先枚举 raw truncated candidates
  |- raw 预检：upper/lower RKDiff 都有 MILP 解后才编号并写入 results
  |- raw 任一侧 INFEASIBLE：不编号、不建目录，直接加 truncated no-good
  |- 有效截断路径：编号为 T1、T2、...
  |- 内层：每个 Ti 建立一个 RKDiff，并枚举 Ci,1、Ci,2、...
  |- concrete UNSAT：full concrete-trail no-good，复用当前 RKDiff
  |- concrete exhausted / path timeout：full activity no-good，复用截断模型
  |- SAT + replay PASS：接受当前 upper/lower 并输出正式 trail
  `- replay error：标记 MODEL_INCONSISTENCY，不添加任何 no-good
  `- rkboom_full.py: 实例化 E0+Em 与 Em+E1
        |
        +--> JSON / TXT / Markdown / TeX
        |
        `--> 可选 probability evaluator
              |- upper RK differential
              |- lower RK differential
              |- key schedule forward/backward alignment
              `- Em related-key boomerang switch
```

三段参数含义：

| 参数 | 含义 |
|---|---|
| `r0` | upper 外部段 E0 的轮数 |
| `rm` | 中间 boomerang / sandwich 段 Em 的轮数，必须大于 0 |
| `r1` | lower 外部段 E1 的轮数 |
| `w0` | E0 活跃 S 盒的目标系数 |
| `wm` | Em common active S 盒的目标系数 |
| `w1` | E1 活跃 S 盒的目标系数 |
| `timelimit` | 每一次 Gurobi MILP `optimize()` 的时间限制，秒；命令行为 `--tl` |
| `global_timelimit` | 一次 `rkboom.py` 搜索的全局墙钟时间限制，秒；命令行为 `--global-tl`，默认不限制 |
| `numofsols` | 当前主入口保留参数；`rkboom.py` 中多解功能尚未启用 |
| `rk_mode` | 相关密钥建模模式 |
| `probtest` | 是否在搜索完成后运行概率实验 |
| `exact_verify` | 是否启用 Z3 双层 exact refinement；命令行开关为 `--exact-verify`，默认关闭 |
| `exact_verify_timeout_ms` | 每个 RKDiff concrete candidate 的 Z3 timeout，默认 300000 ms |
| `exact_path_timeout_sec` | 单条截断路径的 upper/lower concrete refinement 总时间限制；默认 `None`，即不设置总限制 |

`rk_mode`：

| 模式 | 行为 |
|---|---|
| `rk-basic` | 建模 128-bit key schedule 与每轮 round-key 差分 |
| `rk-ladder` | 默认；在 `rk-basic` 上为 Em 对齐轮的 upper/lower key S-box 加 `u+v<=1` ladder 约束 |
| `rk-debug-independent` | round key 不通过 key schedule 传播，只用于定位问题，不能作为正式相关密钥结果 |

## 5. 环境与依赖

必需环境：

- Python 3；当前目录已在 Python 3.12 下通过基础测试；
- `gurobipy` 与可用的 Gurobi License；
- `PyYAML`，供 `rkboom.py` 和 `rkboom_full.py` 读取 YAML；
- `z3-solver`，供主入口强制执行 concrete trail 真实性验证；
- 同一 `Test/` 下的 `Splight_implement/implement_py/`，概率实验会导入其中的 `enc.py` 和 `probability_tests/probability_test.py`。

开发 / 可选依赖：

- `pytest`：运行测试；
- SageMath：仅在调用 `splight/sbox_constraints.py::generate_convex_hull_inequalities()` 重新生成凸包不等式时需要；没有 Sage 时会返回空凸包列表，DDT 与测试仍可使用。

本目录目前没有 `requirements.txt` 或锁文件，Gurobi 授权也需要单独配置。

## 6. 快速开始

所有命令建议在本目录执行：

```powershell
cd Test/Splight-H-RK
```

### 6.1 运行基础测试

```powershell
python -m pytest tests -q
```

当前结果：15 项测试全部通过（含 raw truncated 预检、exact verification、两层 no-good、timeout 分支、模型复用与非零 offset 回归）。

### 6.2 默认相关密钥 sandwich 搜索

```powershell
python rkboom.py
```

默认等价于：

```powershell
python rkboom.py -r0 2 -rm 3 -r1 2 -w0 6 -wm 3 -w1 6 -tl 1200 --rk_mode rk-ladder
```

指定 7-4-3：

```powershell
python rkboom.py -r0 7 -rm 4 -r1 3 -w0 6 -wm 3 -w1 6 -tl 1200 --rk_mode rk-ladder
```

例如，将每个 MILP 限制为 1200 秒，并将整个搜索限制为 3600 秒：

```powershell
python rkboom.py -r0 7 -rm 4 -r1 3 -tl 1200 --global-tl 3600
```

`--global-tl` 覆盖 truncated、upper/lower RKDiff 实例化和 exact refinement；`--probtest t` 的实验时间不计入该限制，会单独输出 `Probability test time`。

为 7-4-3 启用双层 exact refinement：

```powershell
python rkboom.py -r0 7 -rm 4 -r1 3 -w0 6 -wm 3 -w1 6 -tl 1200 --rk_mode rk-ladder --exact-verify --exact-verify-timeout-ms 300000 --exact-path-timeout-sec 1800
```

启用概率实验：

```powershell
python rkboom.py -r0 2 -rm 3 -r1 2 --probtest t
```

从已有搜索结果单独重跑概率实验：

```powershell
python tools/probtest_from_results.py --result-dir .\results\4-4-4_636
```

可选的 `--seed` 复用现有 evaluator 的随机种子覆盖能力，`-tl/--timelimit` 覆盖保存参数中的 key schedule MILP 时限。样本数继续按现有 weight/CAS 自动规则决定，不会重新运行 truncated MILP、RKDiff 或 Z3。exact 结果优先读取 `exact_summary.json` 指向的 `truncated_XXXX/{upper,lower}/accepted.json`；若该链不完整，只回退到正式结果 JSON，绝不读取 rejected/unknown candidate。旧目录 `<r0-rm-r1>` 和新目录 `<r0-rm-r1_w0wmw1>` 都可读取，输出保存为 `probability_results/<case>/`。日志末尾使用实验值输出 `p^2 * r * q^2 = 2^(-n)`；若某项测试被跳过或零命中，则明确说明无法得到有限实验指数。

### 6.3 长区间实例化

```powershell
python rkboom_full.py -r0 2 -rm 3 -r1 2 -w0 6 -wm 3 -w1 6 -tl 1200
```

它分别搜索 upper `E0+Em` 和 lower `Em+E1`，不是 `rkboom.py` 的替代入口，也不运行概率实验。

### 6.4 单独搜索 N 轮具体相关密钥差分

```powershell
python tools/rkdiff_cli.py --rounds 7 --time-limit 120 --output-dir results/rkdiff_manual
```

### 6.5 单独求解 key schedule 差分

固定完整 128-bit key state：

```powershell
python keydiff.py --rounds 4 --fix ks_0=00000000000000000000000000000001 --time-limit 60
```

固定单个 bit：

```powershell
python keydiff.py --rounds 4 --fix ks_0_3_2=1 --output keydiff_result.json
```

### 6.6 批量搜索

```powershell
python run/run_rkdiff_rounds.py
python diff/run_rkdiff_round_sweep.py
python diff/run_rkdiff_min_weight_from6.py
```

`diff/rerun_min_weight_6_10_1200s.py` 会无条件重跑 6–10 轮，每轮上限 1200 秒，并覆盖对应 `diff/round-N/min_weight_rkdiff.*`，运行前应确认确实需要更新历史结果。

### 6.7 YAML 输入

两个主入口都支持 `-i/--inputfile`。示例：

```yaml
r0: 7
rm: 4
r1: 3
w0: 6
wm: 3
w1: 6
timelimit: 1200
global_timelimit: 3600
numofsols: 1
rk_mode: rk-ladder
probtest: false
```

命令行显式参数会覆盖 YAML 中的同名值。 `rkboom_full.py` 不使用 `probtest`。

## 7. 变量和输出字段

状态差分变量：

| 变量 | 含义 |
|---|---|
| `x_r_i` | 第 `r` 轮输入状态第 `i` 个 nibble；`x[0..7]=L`、`x[8..15]=R` |
| `y_r_i` | 第一层状态 S 盒输出差分 |
| `l_r_i` | 线性层输出差分 |
| `rk_r_i` | 本轮 32-bit round-key 差分 |
| `ak_r_i` | `l xor rk` 的差分，即第二层 S 盒输入 |
| `z_r_i` | 第二层状态 S 盒输出差分 |

密钥差分变量：

| 变量 | 含义 |
|---|---|
| `ks_r_i` | 第 `r` 个 128-bit key schedule state 的第 `i` 个 nibble |
| `kc_r_i` | key core 中间输出；具体模型只为第 3、7 个 key S-box 分配独立输出变量 |
| `ks_global_r` | 从全局主密钥差分传播得到的第 `r` 个 key state |
| `round_ks_r` | 当前局部轮使用的完整 128-bit key state，即 `ks_global_{round_offset+r+1}` |
| `round_ks_global_index_r` | `round_ks_r` 对应的全局 key-state 编号 |
| `master_key_diff` | `ks_global_0` / `ks_0` |

权重字段：

| 字段 | 含义 |
|---|---|
| `rw_r` | 本轮状态两层 S 盒的 weight |
| `kw_r` | 本轮 key schedule S 盒的 weight |
| `pr_r` | `rw_r + kw_r` |
| `total_weight` | 所有状态与密钥 S 盒局部 DDT weight 之和 |

终止状态行没有对应加密轮，因此 `y/l/rk/ak/z/round_ks/pr/rw/kw` 均为 `none`。

## 8. 目录总览

```text
Splight-H-RK/
|- rkboom.py                     主 sandwich 搜索入口
|- rkboom_full.py                E0+Em / Em+E1 长区间实例化
|- rktruncboom.py                三段截断 boomerang MILP
|- rktruncdiff.py                单路径截断差分 MILP
|- rkdiff.py                     bit 级相关密钥差分 MILP
|- keydiff.py                    key schedule-only MILP
|- tools/                        exact verifier、单次搜索与历史结果维护工具
|- tools/rk_exact_verify.py      concrete trail Z3 验证与 witness replay
|- splight/                      轻量 Splight 规格、DDT 和加解密实现
|- probability/                  RK 差分与 Em 概率实验
|- output/                       Markdown / TeX / ASCII 输出
|- tests/                        基础单元测试
|- results/                      rkboom.py 按轮数组合保存的搜索结果
|- results_full/                 rkboom_full.py 按轮数组合保存的长区间结果
|- run/                          2–11 轮批处理入口
|- diff/                         轮数扫描脚本、结果与问题记录
|- results/                      boomerang 搜索结果
|- tmp/                          自动生成的 Gurobi LP 文件
`- __pycache__/                  Python 字节码缓存
```

## 9. 根目录文件说明

| 文件 | 作用 |
|---|---|
| `README.md` | 当前项目总说明、运行指南和完整文件索引 |
| `READ_CODE_STRUCTURE.md` | 早期简版代码结构说明；部分 `run/` 文件列表已过时，以本 README 为准 |
| `rkboom.py` | 默认主入口；搜索 Hadipour 风格三段截断 sandwich，分别实例化 E0 / E1，生成结果和可选概率实验 |
| `rkboom_full.py` | 长区间入口；在相同截断结构上分别实例化 `E0+Em` 与 `Em+E1`，输出两条 span 和全局合并表 |
| `rktruncdiff.py` | `RKTruncDiff`；nibble 级前向/后向截断传播、截断 XOR、状态与 key schedule 活跃性建模 |
| `rktruncboom.py` | `RKTruncatedBoomerang`；耦合 upper / lower 截断模型，构造 Em 无抵消 XOR、common active 变量、目标函数与 key ladder |
| `rkdiff.py` | `RKDiff`；完整 bit 级差分 MILP，包含两层状态 S 盒、线性层、Feistel 更新、key schedule、round key 与 DDT weight |
| `rkdiff_backup.py` | `rkdiff.py` 的历史备份快照；当前入口不导入它，不应作为正式求解版本 |
| `keydiff.py` | `KeyDiff`；只求解 128-bit key schedule 差分，支持正向/反向固定 key state，并提供 CLI |
| `tools/rkdiff_cli.py` | 单独调用 `RKDiff` 的轻量 CLI，保存一条 N 轮 characteristic 的 JSON/TXT |
| `tools/rk_exact_verify.py` | 主流程使用的真实值 Z3 verifier；验证完整差分量并在 SAT 时执行普通 Python replay |
| `tools/probtest_from_results.py` | 从已有 `results/<case>/` 恢复正式 upper/lower trail 并调用既有 RK 概率 evaluator；输出到 `probability_results/<case>/`，不重跑 truncated/RKDiff/Z3 搜索 |
| `tools/maintenance/refresh_result_round_ks.py` | 一次性维护工具：不重新求解；批量重写已有 `results/*`，补充 `round_ks`、统一十六进制大写、重建 TXT/Markdown；只有显式传入 `--rename-case-dirs` 才迁移旧目录 |
| `tools/maintenance/update_743_key_schedule_display.py` | 一次性维护工具：只针对 `results/7-4-3` 生成详细 key schedule 变量表；会修改 7-4-3 历史结果 |

## 10. `splight/`：基础规格与执行实现

| 文件 / 目录 | 作用 |
|---|---|
| `splight/__init__.py` | Python 包标记；当前无额外逻辑 |
| `splight/splight_spec.py` | Splight 常量、S3 S 盒、hex/nibble/bit 转换、线性层、SHI2 与 XOR 工具 |
| `splight/sbox_constraints.py` | 计算 DDT、支撑点、weight 表、排除无效转换；可选调用 SageMath 生成凸包不等式并读写 JSON |
| `splight/splight_cipher.py` | 轻量 reduced-round Splight 加解密；支持自定义 round keys，默认零轮密钥，主要用于基础一致性测试 |
| `splight/__pycache__/` | 自动生成的 `.pyc` 缓存，不是源码或实验结果 |

`splight/splight_cipher.py` 不是概率实验使用的完整密钥调度实现；相关密钥概率实验使用 sibling `Splight_implement/implement_py/enc.py`。

## 11. `probability/`：概率与密钥调度实验

| 文件 / 目录 | 作用 |
|---|---|
| `probability/__init__.py` | Python 包标记 |
| `probability/rk_probability_evaluator.py` | `rkboom.py --probtest t` 的实现；测试 upper/lower 外部 RK differential，求解 aligned key schedule，并调用参考实验程序测试 Em switch |
| `probability/test_key_schedule_diff.py` | 独立 Monte Carlo 工具；给定主密钥差分和轮号，统计真实 round-key 差分频数及目标值命中数 |
| `probability/RK_EM_PROBABILITY_TEST_PRINCIPLE.md` | Em 相关密钥四密钥实验、delta/nabla key diff 来源、CAS 与采样规则的详细说明 |
| `probability/__pycache__/` | 自动生成的 Python 字节码缓存 |

默认采样规则：

```text
upper/lower data size = 2^(ceil(total_weight)+2)
Em data size          = max(2^12, 2^(2*CAS+2))
exponent >= 16        = 跳过实验
seed                  = 当天日期 YYYYMMDD
```

概率实验会产生：

- `rk_probability_tests.*`：三部分实验总结果；
- `delta_keydiff_forward.*`：upper key state 的正向 KeyDiff 推导；
- `nabla_keydiff_backward.*`：lower key state 的反向 KeyDiff 推导；
- `aligned_key_schedule.*`：按全局轮对齐后的 upper/lower key schedule 表。

## 12. `output/`：结果表示

| 文件 / 目录 | 作用 |
|---|---|
| `output/__init__.py` | Python 包标记 |
| `output/plotdistinguisher.py` | 读取主 JSON，生成 ASCII、Markdown 表、Mermaid 内容和 TeX/TikZ 区分器；同时补充 key schedule 表与 S 盒 DDT 信息 |
| `output/__pycache__/` | 自动生成的 Python 字节码缓存 |

## 13. `tests/`：单元测试

| 文件 | 作用 |
|---|---|
| `tests/test_sbox_constraints.py` | 检查 S 盒是排列、DDT 每行和为 16、DDT 支撑点与 weight 表一致 |
| `tests/test_shift_and_linear_layer.py` | 检查 SHI2 / inverse SHI2 互逆和线性层公式 |
| `tests/test_splight_cipher.py` | 检查 hex/nibble 往返以及 1、2、5、32 轮零轮密钥加解密互逆 |

这些测试不运行 Gurobi 主搜索，也不验证多轮 MILP characteristic 的具体值可实例化性。

## 14. `run/`：简单批处理

| 文件 | 作用 |
|---|---|
| `run/__init__.py` | Python 包标记 |
| `run/run_rkdiff_rounds.py` | 依次调用 `tools/rkdiff_cli.py` 搜索 2–11 轮；保存每轮 JSON/TXT/terminal log，并生成汇总 Markdown。目标目录运行后为 `results/rkdiff_2_11/` |

## 15. `diff/`：轮数扫描、最小 weight 结果和问题记录

### 15.1 脚本与汇总文件

| 文件 | 作用 |
|---|---|
| `diff/run_rkdiff_round_sweep.py` | 从 0 轮开始扫描 `RKTruncDiff`；复用已有具体差分结果，达到 32 个截断活跃 S 盒或状态异常时停止 |
| `diff/run_rkdiff_min_weight_from6.py` | 直接运行 6–15 轮 `RKDiff`，默认每轮 120 秒；支持迁移旧目录结果并区分 OPTIMAL 与 TIME_LIMIT incumbent |
| `diff/rerun_min_weight_6_10_1200s.py` | 强制重跑 6–10 轮，每轮 1200 秒，然后重建 6–15 轮汇总 |
| `diff/rkdiff_round_sweep_summary.{json,csv,md}` | 0–27 轮截断 / 具体差分扫描的机器可读、表格和 Markdown 汇总 |
| `diff/min_weight_6_15.{json,md}` | 6–15 轮最小 weight 状态汇总 |

### 15.2 逐轮结果命名模式

| 路径模式 | 作用 |
|---|---|
| `diff/round_00_truncated.json` … `round_27_truncated.json` | 每轮 nibble 级截断搜索结果 |
| `diff/round_00_rkdiff.{json,txt}` … `round_26_rkdiff.{json,txt}` | 每轮 bit 级 RKDiff 元数据 / trail 与终端日志；当前 27 轮没有对应具体结果 |
| `diff/round-6/` … `diff/round-15/` | 新版按轮组织的最小 weight 结果目录 |
| `diff/round-N/min_weight_rkdiff.json` | 求解状态、时间、weight、LP 路径和 trail |
| `diff/round-N/min_weight_rkdiff.txt` | 对应求解终端输出 |
| `diff/rkdiff_min_weight_from6/round_06.*` … `round_11.*` | 旧版 6–11 轮结果，供迁移和历史对照 |
| `diff/rkdiff_min_weight_from6/summary.{json,csv,md}` | 旧版逐轮结果汇总 |

### 15.3 分析日志

| 文件 | 作用 |
|---|---|
| `diff/log/rkdiff_7_4_3_round6_zero_analysis.md` | 7-4-3 upper 的局部 characteristic、真实 hull 分支和轮密钥现象分析 |
| `diff/log/rkdiff_high_round_weight_issue.md` | 高轮数异常 weight 的来源、TIME_LIMIT 误读与修正说明 |
| `diff/log/round_ks_result_refresh.md` | 历史结果 `round_ks` 列、全局 key-state 索引和大写化的批量刷新记录 |

## 16. `results/`：boomerang 搜索结果

当前已有配置目录：

```text
2-2-2  2-3-2  2-4-2  2-6-2
3-3-3  3-4-3  3-5-2  3-6-2
4-4-4  5-4-3  6-4-3  6-4-4
7-4-3  8-4-3
```

新搜索的目录名统一表示 `<r0>-<rm>-<r1>_<w0><wm><w1>`，例如 `1-1-1_424`。目录内的正式文件名仍使用 `<r0-rm-r1>`。旧目录 `<r0-rm-r1>` 仍可由离线概率测试读取。每个标准结果目录包含下列同构文件：

| 文件 | 作用 |
|---|---|
| `<r0-rm-r1>.txt` | 人类可读总结果：截断路径、upper/lower concrete characteristic、概率摘要及可能追加的分析 |
| `terminal_print.txt` | 本次 `rkboom.py` 运行的完整终端输出；stdout/stderr 在终端正常显示的同时按原顺序写入，每次运行覆盖 |
| `<r0-rm-r1>_distinguisher.md` | Markdown 区分器报告，包括状态与 key schedule 表 |
| `bmd.tex` | TeX/TikZ 区分器片段 |
| `upper_diff_trail.txt` | upper 具体 RK 差分 characteristic |
| `lower_diff_trail.txt` | lower 具体 RK 差分 characteristic |
| `rk_probability_tests.txt` | upper/lower/Em 概率实验日志 |
| `delta_keydiff_forward.txt` | upper 密钥差分正向传播日志 |
| `nabla_keydiff_backward.txt` | lower 密钥差分反向传播日志 |
| `aligned_key_schedule.txt` | upper/lower 全局轮密钥状态对齐表 |
| `.json/` | 与上述文本对应的机器可读 JSON 子目录 |
| `.json/<r0-rm-r1>.json` | 主结果对象，含参数、截断路径、具体路径、weight、LP 路径和概率对象 |
| `.json/upper_diff_trail.json` | upper characteristic 完整字段 |
| `.json/lower_diff_trail.json` | lower characteristic 完整字段 |
| `truncated_XXXX/` | 开启 `--exact-verify` 后按联合 truncated boomerang path 保存的双层搜索结果；只有 upper/lower 首次 RKDiff MILP 都可行时才分配编号并创建目录 |
| `truncated_XXXX/truncated_path.{md,json}` | 当前联合 truncated path 的 upper、middle、lower activity、完整 activity signature 和截断模型信息 |
| `truncated_XXXX/summary.json` | 当前 truncated path 的联合结果，分别记录 upper/lower concrete refinement 状态、候选数、weight、timeout 和 replay 信息 |
| `truncated_XXXX/upper/`、`truncated_XXXX/lower/` | 同一联合 truncated path 下两侧的 exact refinement；分别包含 `accepted.*`、`rejected/` 和 `unknown/` |
| `truncated_XXXX/{upper,lower}/accepted.*` | 仅在对应侧 `SAT + replay PASS` 后生成的正式接受结果与真实 witness |
| `exact_summary.json` | upper/lower 联合双层搜索的最终状态；区分 `SUCCESS`、`NO_EXACT_REALIZABLE_TRAIL`、`SEARCH_INCOMPLETE_TIMEOUT` 和模型一致性错误 |
| `.json/rk_probability_tests.json` | 概率实验完整结构 |
| `.json/delta_keydiff_forward.json` | upper forward KeyDiff 结果 |
| `.json/nabla_keydiff_backward.json` | lower backward KeyDiff 结果 |
| `.json/aligned_key_schedule.json` | 按全局轮对齐的 key schedule JSON |

特殊文件：

| 路径 | 作用 |
|---|---|
| `results_full/<r0-rm-r1_w0wmw1>/full_span_boomerang.{txt,md,json}` | `rkboom_full.py` 生成的 E0+Em / Em+E1 长区间实例化结果 |
| `results_full/<r0-rm-r1_w0wmw1>/terminal_print.txt` | 本次 `rkboom_full.py` 的完整 stdout/stderr；终端正常显示的同时实时写入，每次运行覆盖 |
| `probability_results/<case>/` | `probtest_from_results.py` 的离线概率实验目录，case 保留输入结果目录的旧/新名称，包含既有 `rk_probability_tests.*`、密钥对齐文件、`summary.json` 和 `terminal_print.txt` |
| `results/2-3-2/EM_PROBABILITY_ISSUE_ANALYSIS.md` | 2-3-2 Em 概率异常的历史分析 |
| `results/2-3-2/EM_PROBABILITY_PROBLEM_AUDIT.md` | 2-3-2 Em 概率问题的审计记录 |
| `results/7-4-3/key_schedule_variables.txt` | 7-4-3 upper/lower 详细 key schedule 差分变量表 |
| `results/7-4-3/.json/key_schedule_variables_7-4-3.json` | 上述表的机器可读版本 |

结果目录属于实验产物。重新运行 `rkboom.py`、结果刷新工具或 7-4-3 专用工具可能覆盖同名文件。

## 17. `tmp/`：Gurobi 模型与临时检查

| 路径模式 | 作用 |
|---|---|
| `tmp/splight_h_rk_<r0>_<rm>_<r1>_<rk_mode>.lp` | 主 sandwich 截断 MILP；当前保留多组历史配置 |
| `tmp/splight_h_rk_truncdiff_<rounds>.lp` | 逐轮 `RKTruncDiff` 扫描模型 |
| `tmp/boomerang/splight_h_rkdiff_<pid>_<timestamp>.lp` | `RKDiff` 自动生成的具体差分模型；文件名用 PID 和时间戳避免冲突 |
| `tmp/keydiff/splight_h_keydiff_<rounds>_<pid>_<timestamp>.lp` | `KeyDiff` 自动生成的密钥调度模型 |
| `tmp/rkdiff_check/rkdiff_1r.{json,txt}` | 一轮 RKDiff 临时检查结果 |

`.lp` 是可直接交给 Gurobi 检查的模型快照，不是最终结论。该目录当前包含大量历史 LP；README 按命名模式说明，每个同模式文件的作用相同。

## 18. `__pycache__/` 与各子目录缓存

根目录以及 `splight/`、`output/`、`probability/` 下的 `__pycache__/` 保存 Python 自动生成的 `.pyc` 字节码，例如 `rkdiff.cpython-312.pyc`。它们不是手工维护源码，也不参与结果解释；Python 会在导入模块时按需重新生成。

## 19. 常见注意事项

1. 正式相关密钥结果使用 `rk-basic` 或 `rk-ladder`，不要使用 `rk-debug-independent`。
2. `TIME_LIMIT` 的 incumbent 是可行上界，不是已证明最小 weight。
3. 截断路径只约束活跃性，bit 级路径只约束差分；两者都不自动提供贯穿多轮的真实数据对。
4. 概率实验是 Monte Carlo 估计，返回 0 可能只是样本不足，也可能是固定 characteristic 与真实 differential hull 不一致，需要结合样本量和具体值验证判断。
5. `round_ks_r` 对应更新后的 `ks_global_{round_offset+r+1}`；`ks_global_0` 是主密钥输入差分，不是第 0 轮直接显示的 round-key state。
6. `tools/maintenance/` 下的历史结果整理脚本和批量重跑脚本会改写已有结果，运行前应确认目标范围。
7. `output/plotdistinguisher.py`、概率模块和主入口对 JSON 字段有约定；手工修改结果 JSON 后应同步检查派生 TXT/Markdown。
8. `rkboom.py` 默认不开启概率实验；以相同配置重跑且不传 `--probtest t` 时，会删除旧的 `rk_probability_tests.json/txt`。其他已有的 `delta_keydiff_forward`、`nabla_keydiff_backward`、`aligned_key_schedule` 文件不会在该分支同步删除，解释结果时应检查生成时间是否一致。

## 20. 当前核对状态

2026-08-30 已完成：

- 核对根目录、全部源码子目录、`diff/`、`results/`、`tmp/` 和缓存目录；
- 核对 `rkboom.py`、`rkboom_full.py`、`tools/rkdiff_cli.py`、`keydiff.py` 的实际 `--help`；
- 运行 `python -m pytest tests -q`，结果为 10 项全部通过；
- 按实际存在的文件归纳所有自动生成文件的命名模式与用途。
