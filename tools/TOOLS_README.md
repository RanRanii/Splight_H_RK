# Tools 目录说明

`tools/` 放置 Splight-H-RK 项目的独立求解入口、Z3 真实可实现性验证器和一次性结果维护脚本。

以下命令均建议在项目根目录执行：

```powershell
cd Test\Splight-H-RK
```

## 目录结构

```text
tools/
|- TOOLS_README.md
|- rkdiff_cli.py
|- rk_exact_verify.py
|- rk_bm_exact_verify.py
|- maintenance/
|  |- refresh_result_round_ks.py
|  `- update_743_key_schedule_display.py
`- __pycache__/
```

## 快速对照

| 路径 | 作用 | 是否求解 MILP | 是否调用 Z3 | 是否改写已有结果 |
|---|---|---:|---:|---:|
| `TOOLS_README.md` | `tools/` 全部文件、目录和使用方法说明 | 否 | 否 | 否 |
| `rkdiff_cli.py` | 独立搜索 N 轮最小 weight 相关密钥差分路径 | 是 | 否 | 只写指定输出目录 |
| `rk_exact_verify.py` | 用两条真实 Splight 执行验证完整 concrete trail | 否 | 是 | 否 |
| `rk_bm_exact_verify.py` | 用四条真实 Splight 执行验证完整 related-key Boomerang 数据四元组 | 否 | 是 | 只写 `<case>/bm_exact_verify/` |
| `maintenance/refresh_result_round_ks.py` | 批量修复已有结果的 `KS` 列和十六进制大小写，可选迁移旧 case 目录 | 否 | 否 | 是，批量覆盖 |
| `maintenance/update_743_key_schedule_display.py` | 为已有 `7-4-3` 结果生成详细密钥调度差分表 | 否 | 否 | 是，仅 `7-4-3` |
| `__pycache__/` | Python 导入缓存 | 否 | 否 | 否 |

## `rkdiff_cli.py`

### 作用

这是单独调用 `rkdiff.RKDiff` 的命令行入口，用于搜索从全局第 0 轮开始的 N 轮相关密钥差分 characteristic。

它建立 bit-level MILP，同时包含：

- 64-bit 加密状态差分传播；
- 128-bit 主密钥差分及密钥调度传播；
- 每轮 round-key 差分；
- 状态 S 盒和密钥调度 S 盒的真实 DDT weight。

主目标是最小化状态 S 盒 weight 与密钥调度 S 盒 weight 之和。如果第一阶段得到最优解，`RKDiff` 会固定该 weight，再最小化主密钥差分的活跃 bit 数。

### 使用方法

```powershell
python tools/rkdiff_cli.py --rounds 6 --time-limit 1200 --output-dir .\diff\round-6
```

参数：

| 参数 | 必需 | 默认值 | 含义 |
|---|---:|---:|---|
| `--rounds` | 是 | 无 | 差分路径的加密轮数 |
| `--time-limit` | 否 | `120` | Gurobi 求解时间限制，秒 |
| `--output-dir` | 否 | `results/rkdiff_2_11` | JSON/TXT 结果目录 |

输出示例：

```text
diff/round-6/
|- rkdiff_6r.json
`- rkdiff_6r.txt
```

TXT 表格包含 `x`、`y`、`l`、`RK`、`ak`、`z`、`KS`、`pr`、`rw`、`kw`、主密钥差分和总 weight。建模生成的 LP 文件位于 `tmp/boomerang/`。

### 当前限制

- 只使用 `mode=0`；
- 默认 `rk_mode=rk-ladder`，CLI 没有提供覆盖参数；
- 固定 `round_offset=0`；
- 初始状态差分和初始主密钥差分都被约束为非零；
- CLI 未开放 `fixedVariables` 和 `nonzeroVariables`；
- 不执行 truncated boomerang、Z3 exact verification、no-good 重搜或概率实验。

## `rk_exact_verify.py`

### 作用

这是 Splight 相关密钥 concrete differential trail 的真实值 Z3 验证器。它同时建模两条真实执行：

```text
(X_A, K_A)
(X_B, K_B)
```

所有输入差分都作为 `V_A XOR V_B` 约束同时固定。因此：

- `SAT`：存在真实状态和真实主密钥 witness，可同时实现完整路径；
- `UNSAT`：不存在能同时实现所有固定差分的真实 witness；
- `UNKNOWN`：通常表示 Z3 timeout，不能当作 `UNSAT`。

SAT 后还会用普通 Python 实现重放密钥调度和加密轮，只有 `concrete_replay=PASS` 才表明 SMT 模型与密码实现一致。

`rkboom.py --exact-verify` 会自动调用本模块。本文件只负责 Z3 验证，不导入 Gurobi，不添加 MILP no-good；`UNSAT` 后的 full-trail no-good 由 `rkdiff.py` 处理。

### Python 接口

#### 验证标准 trail

```python
from tools.rk_exact_verify import verify_trail

result = verify_trail(
    {
        "rounds": 2,
        "round_offset": 0,
        "fixed_diffs": {
            "dK": "00000000000000000000000000000002",
            "dX0": "0000000000000002",
            "dX1": "0000000200000000",
            "dX2": "0000000000000002",
        },
    },
    timeout_ms=300000,
    return_witness=True,
)

print(result["status"])
```

#### 直接验证固定差分

```python
from tools.rk_exact_verify import verify_fixed_differences

result = verify_fixed_differences(
    rounds=2,
    round_offset=0,
    fixed_diffs={
        "dK": "00000000000000000000000000000002",
        "dX0": "0000000000000002",
        "dX2": "0000000000000002",
    },
    timeout_ms=300000,
    return_witness=True,
    return_all_diffs=False,
)
```

#### 查询可固定的差分变量

```python
from tools.rk_exact_verify import list_diff_variables

variables = list_diff_variables(rounds=2, round_offset=0)
for name, hex_width in variables.items():
    print(name, hex_width)
```

主要变量名包括：

- 主密钥和全局密钥状态：`dK`、`dKSGg`、`dKSGINg`、`dKSGOUTg`、`dKSGCOREg`；
- 局部状态：`dXr`、`dXLr`、`dXRr`；
- 轮内差分：`dRKr`、`dYr`、`dLINr`/`dLr`、`dAKr`、`dZr`、`dFXORr`、`dSHIr`；
- 局部密钥状态：`dKSr`、`dROUNDKSr`、`dKSINr`、`dKSOUTr`、`dKCOREr`。

`round_offset=s` 表示局部第 0 轮对应 Splight 全局第 `s` 轮。验证器仍会从真实主密钥 `KS_global_0` 开始正向生成全部密钥状态和轮密钥。

### 依赖和输出

依赖：

```powershell
python -m pip install z3-solver
```

该文件没有命令行 `main()`，直接执行不会进行验证。应通过 Python 导入调用，或由 `rkboom.py --exact-verify` 调用。验证结果以字典返回，本模块不主动写入结果文件。

## `rk_bm_exact_verify.py`

### 作用

这是完整 related-key Boomerang 的精确四元组验证器，独立于 `rk_exact_verify.py`。它建立四条真实完整加密执行：

```text
00: (P00, K00)
10: (P10, K00 XOR DeltaK)
01: (P01, K00 XOR NablaK)
11: (P11, K00 XOR DeltaK XOR NablaK)
```

模型同时固定两条 upper 差分路径 `00/10`、`01/11`，两条 lower 差分路径 `00/01`、`10/11`，并检查输入 Delta 与输出 Nabla 的闭合关系。若结果目录中存在 `truncated_XXXX/truncated_path.json`，还会固定 upper/lower 在 middle 的完整零/非零活动模式，并检查 `middle_part` 是否与这两个活动模式一致。

- `SAT` 且 `concrete_replay=PASS`：存在一个真实的四密钥/四数据 quartet，满足已编码的完整区分器；
- `UNSAT`：当前这组 upper concrete trail、middle 截断路径和 lower concrete trail 不能共同组成一个真实 quartet；
- `UNKNOWN`：超时或资源限制，不能作为 `UNSAT` 使用。

该结论只证明可实现性，不计算、估计或证明 Boomerang 概率。

### 使用方法

在一个已经完成 `--exact-verify` 的结果目录上执行：

```powershell
python tools/rk_bm_exact_verify.py --result-dir .\results\2-3-2_636 --timeout-ms 600000
```

默认读取：

```text
exact_summary.json
truncated_XXXX/truncated_path.json
truncated_XXXX/upper/accepted.json
truncated_XXXX/lower/accepted.json
```

默认输出：

```text
results/<case>/bm_exact_verify/
|- summary.json
|- witness.json                 # 仅 SAT 时生成
|- witness.md
`- terminal_print.txt
```

可用 `--truncated-id` 选择具体的已接受路径，使用 `--output-dir` 改写输出位置；`--return-all-diffs` 会将四组 pair registry 的所有实际差分写入 witness。

## `maintenance/refresh_result_round_ks.py`

### 作用

这是一次性批量结果维护脚本，不会重新建立或求解 MILP。它遍历 `results/` 下的所有子目录，并执行：

1. 将结果中的纯十六进制字符串统一转为大写；
2. 为 upper/lower concrete trail 添加 `round_ks_r`；
3. 使 `round_ks_r = ks_global_{round_offset+r+1}`；
4. 检查 `rk_r` 是否等于当轮 `round_ks_r` 的前 8 个 nibble；
5. 重写主结果 JSON、upper/lower JSON/TXT、总结 TXT 和区分器 MD；
6. 尽量保留原总结 TXT 末尾的概率实验日志；
7. 生成批量处理记录 `diff/log/round_ks_result_refresh.md`。

### 使用方法

```powershell
python tools/maintenance/refresh_result_round_ks.py
```

默认只刷新结果内容，不修改目录名。如需将旧目录 `<r0-rm-r1>` 迁移为 `<r0-rm-r1_w0wmw1>`，必须显式执行：

```powershell
python tools/maintenance/refresh_result_round_ks.py --rename-case-dirs
```

上述模式会在迁移目录后继续刷新历史结果内容。如果只需要迁移目录名，不允许改写目录内文件，应执行：

```powershell
python tools/maintenance/refresh_result_round_ks.py --rename-only
```

`--rename-only` 只从正式 JSON 的 `parameters` 读取轮数和 weight、重命名目录，并写入 `diff/log/result_directory_rename.md`。若参数缺失、轮数不一致或目标目录已存在，会跳过迁移并记录，不会覆盖目标目录，也不会调用 `refresh_result()`。所有模式的处理范围都是整个 `results/`。

### 输入和覆盖范围

每个 case 从下列文件读取：

```text
results/<case>/.json/<r0-rm-r1>.json
```

可能被覆盖的文件包括：

```text
results/<case>/.json/<r0-rm-r1>.json
results/<case>/.json/upper_diff_trail.json
results/<case>/.json/lower_diff_trail.json
results/<case>/upper_diff_trail.txt
results/<case>/lower_diff_trail.txt
results/<case>/<case>.txt
results/<case>/<case>_distinguisher.md
```

**注意：**这是批量覆盖工具，不是日常搜索入口。它不会自动备份原文件，使用前应确认当前 `results/` 中的实验结果允许被重写。

## `maintenance/update_743_key_schedule_display.py`

### 作用

这是只针对已有 `results/7-4-3/` 的一次性分析脚本。它从 upper/lower trail 的 `ks_global_r` 推导并展示每轮密钥调度差分变量：

- `ks_in`；
- `k0`、`k1`、`k2`、`k3`；
- 密钥 S 盒的 `sbox_in` 和 `sbox_out`；
- `core` 和 `rot_core`；
- 轮常数差分 `C=00000000`；
- `new_k0/RK`、`new_k1`、`new_k2`、`new_k3`；
- `ks_out` 和当轮密钥 S 盒 weight；
- 位置 3、7 上每个密钥 S 盒转移的 DDT count 和 weight。

它不会重新求解 MILP，也不会调用 Z3。

### 使用方法

```powershell
python tools/maintenance/update_743_key_schedule_display.py
```

脚本固定读取：

```text
results/7-4-3/.json/7-4-3.json
```

生成或改写：

```text
results/7-4-3/.json/key_schedule_variables_7-4-3.json
results/7-4-3/key_schedule_variables.txt
results/7-4-3/7-4-3.txt
```

`7-4-3.txt` 中以 `Detailed key schedule difference variables:` 作为标记。如果标记已存在，脚本会保留标记之前的内容，并用新表替换从标记开始到文件末尾的全部内容；如果标记不存在，则将新表追加到文件末尾。

**注意：**输入路径和 case 名称都硬编码为 `7-4-3`，不适用于其他轮数组合。

## `maintenance/` 目录

`maintenance/` 放置已有结果的一次性迁移和展示修复脚本。这些脚本不是 `rkboom.py` 主搜索流程的依赖，新结果应由当前主程序直接生成，不需要例行执行这两个维护脚本。

## `__pycache__/` 目录

`__pycache__/` 由 Python 在导入模块时自动生成，其中的 `.pyc` 是字节码缓存。

- 不是源代码；
- 不需要手工执行；
- 删除后 Python 会在下次导入时自动重建；
- 不应作为实验结果或项目交付文件使用。

## 与主程序的关系

```text
rkboom.py --exact-verify
    |- RKDiff concrete candidate
    |- tools/rk_exact_verify.py
    |    `- SAT / UNSAT / UNKNOWN + concrete replay
    `- rkdiff.py
         `- UNSAT 时添加 full-trail no-good

tools/rk_bm_exact_verify.py --result-dir <case>
    |- loads accepted upper/lower witnesses + truncated middle path
    |- four real full-cipher executions and four related master keys
    `- SAT / UNSAT / UNKNOWN + concrete four-branch replay

tools/rkdiff_cli.py
    `- 直接调用 rkdiff.py，不经过 rkboom.py

tools/maintenance/*.py
    `- 只处理已有 results，不参与新搜索
```
