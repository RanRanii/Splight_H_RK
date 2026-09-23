# Splight-H-RK：RK-Boomerang 结果汇总更新任务

## 0. 参数

用户只设置：

```yaml
TOTAL_ROUNDS: 16
WEIGHT: 636
```

记：

```text
R = TOTAL_ROUNDS
W = WEIGHT
```

本任务只整理已有实验结果，**禁止重新运行搜索、Gurobi、概率实验或 PowerShell 队列**。

---

# 1. 自动定位文件

根据 `R`、`W` 定位：

```text
队列脚本：
run/run_<R>_<W>_recommended_queue.ps1

主日志：
run/run_<R>_<W>_recommended_queue.log

Case 日志：
run/logs/run_<R>_<W>_recommended_queue/

结果目录：
results/

目标 Markdown：
z-notes/boomerang-results/Splight-rk-<R>-boomerang.md
```

如果标准脚本不存在，只搜索：

```text
run/run_<R>_<W>*.ps1
```

规则：

* 唯一匹配 → 使用；
* 多个候选无法确定 → 停止并报告；
* 无匹配 → 停止并报告；
* 禁止猜测。

Case 日志目录不存在时允许继续，但最终需要说明。

---

# 2. 读取队列脚本和日志

先完整读取队列脚本，确定：

* campaign Case；
* 搜索参数和权重；
* `SKIP / RETRY` 规则；
* 输出关系；
* 特殊 Case；
* 注释中说明的单独运行或排除 Case。

再读取主日志和 Case 日志，识别：

```text
START
SKIP
RETRY
DONE
STOP
```

注意：

```text
结果目录存在 ≠ Exact SUCCESS
```

状态判断必须结合脚本实际逻辑和结果文件。

---

# 3. Case 与扫描范围

标准 Case：

```text
r0-rm-r1_weight
```

仅收录满足：

$$
r_0+r_m+r_1=R
$$

的 Case。

扫描 `results/` 中所有属于总轮数 `R` 的合法结果。

其中：

* `weight = W`：当前 campaign，重点重新核验；
* `weight != W`：合法历史结果，只要结果仍存在且有效，也应保留。

因此：

> `WEIGHT` 决定本次 campaign，不限制结果 Markdown 只能出现该权重。

脚本中注明“已单独运行”而未进入当前队列的 Case，也必须检查 `results/<case>/`，不能直接删除。

---

# 4. 单个 Case 的读取顺序

对：

```text
results/<case>/
```

按以下顺序读取：

```text
1. results/<case>/.json/ 中实际存在的正式结果 JSON
2. results/<case>/exact_summary.json
3. results/<case>/terminal_print.txt
4. 对应 Case 日志
5. 主日志
6. 旧 Markdown
```

主要用途：

* 正式 JSON：读取 $W_u$、$W_l$、CAS 等结果；
* `exact_summary.json`：确认 Exact 状态；
* `terminal_print.txt` / 日志：确认超时、终止原因和求解状态；
* 旧 Markdown：只作为历史索引和文档结构参考。

发生冲突时优先使用较新的实际结果文件。

**禁止从旧 Markdown、Case 名称或文件命名规律推测实验数据。**

---

# 5. 状态判定

只有存在实际结果证据时才能标记：

```text
SUCCESS
```

否则根据已有证据使用仓库现有状态，例如：

```text
GLOBAL_TIME_LIMIT
SEARCH_INCOMPLETE_TIMEOUT
INCOMPLETE_NO_SUMMARY
FAILED
UNKNOWN
```

无法确定时使用：

```text
UNKNOWN
```

禁止猜测。

---

# 6. 概率计算与排序

对具有完整 $W_u$、$W_l$、CAS 的 SUCCESS Case 重新计算：

$$
B_{\mathrm{best}}
=
2W_u+2W_l+2CAS
$$

$$
B_{\mathrm{worst}}
=
2W_u+2W_l+\frac{5}{2}CAS
$$

概率区间：

$$
2^{-B_{\mathrm{worst}}}
\le
P_{\mathrm{boom}}
\le
2^{-B_{\mathrm{best}}}.
$$

SUCCESS 统一按照预估概率从高到低排列：

```text
1. B_best 升序
2. B_worst 升序
3. Case 名字典序
```

未完成结果不参与 SUCCESS 排名。

如果文档中已有：

$$
S=2(W_u+W_l+2CAS),
$$

可以保留为辅助指标，但 **不得使用 $S$ 作为主概率排名依据**。

---

# 7. Markdown 数学格式

所有 Markdown：

* 行内公式：`$...$`
* 独立公式：`$$...$$`

禁止使用：

```text
\(...)
\[...\]
```

---

# 8. 更新目标 Markdown

更新：

```text
z-notes/boomerang-results/Splight-rk-<R>-boomerang.md
```

保留仍然正确的背景、方法和结构说明。

必须重新检查所有依赖实验结果的内容，包括：

* 更新时间；
* Case 总数；
* SUCCESS / 未完成 / 超时数量；
* 主结果表；
* 概率排名；
* 最优 Case；
* 概率阈值分类；
* campaign 执行摘要；
* 新增结果说明；
* 结构观察和历史结论；
* 结果索引链接。

旧结论若因新结果变化，必须同步修改。

---

# 9. 结果表规范

表格结构和说明优先参照：

```text
z-notes/boomerang-results/Splight-rk-16-boomerang.md
```

保持不同轮数文档风格一致。

SUCCESS 主表至少应清楚包含：

```markdown
| 排名 | Case | $W_u$ | $W_l$ | CAS | $S$ | 预估概率 | Exact 状态 | 结果 |
|---:|---|---:|---:|---:|---:|---|---|---|
```

已有文档存在其他有价值字段时可以保留。

Case 必须使用完整名称，例如：

```text
8-2-6_636
```

---

## 9.1 结果索引规则

目标 Markdown 位于：

```text
z-notes/boomerang-results/
```

因此结果基础相对路径为：

```text
../../results/
```

### 正式结果文件明确存在

优先链接实际正式结果，例如：

```markdown
[结果](../../results/8-2-6_636/.json/8-2-6.json)
```

存在 Exact summary 时可附：

```markdown
[Exact](../../results/8-2-6_636/exact_summary.json)
```

### 正式结果文件未知或结果不完整

不要猜测具体 JSON。

直接使用 Case 结果目录作为索引：

```markdown
[结果目录](../../results/9-2-7_636/)
```

若存在日志，可附：

```markdown
[结果目录](../../results/9-2-7_636/) · [日志](../../results/9-2-7_636/terminal_print.txt)
```

统一原则：

```text
具体结果明确
→ 链具体结果文件

具体结果未知/不完整
→ 链 results/<case>/ 目录
```

生成具体文件链接前必须确认文件实际存在。

---

## 9.2 未完成结果

未知字段统一填写：

```text
—
```

未完成结果不得虚构：

```text
Wu
Wl
CAS
S
预估概率
```

如果现有 Markdown 将未完成结果单独列出，则继续保持，例如：

```markdown
| Case | 当前状态 | 说明 | 结果 |
|---|---|---|---|
```

示例：

```markdown
| `9-2-7_636` | UNKNOWN | 当前无法确认正式 Exact 结果 | [结果目录](../../results/9-2-7_636/) |
```

表格前简要说明：

* SUCCESS 按预估概率排序；
* `—` 表示无法确认；
* `[结果]` 指向具体结果文件；
* `[结果目录]` 指向该 Case 的原始结果目录。

---

# 10. campaign 执行摘要

根据当前脚本和日志重新统计：

```text
计划 Case 数
START
SKIP
RETRY
DONE
STOP
新增 SUCCESS
仍未完成
```

具体字段根据日志实际情况调整。

**禁止复制旧 Markdown 中的历史统计。**

---

# 11. 禁止修改

本任务只允许修改：

```text
z-notes/boomerang-results/Splight-rk-<R>-boomerang.md
```

禁止修改：

```text
results/
run/*.ps1
运行日志
Python代码
MILP模型
其他轮数Markdown
```

禁止：

```text
git commit
git push
```

也禁止覆盖或还原用户原有未提交修改。

---

# 12. 最终检查

完成后确认：

```text
[ ] 所有 Case 满足 r0+rm+r1=R
[ ] 当前 campaign 脚本和日志已读取
[ ] 特殊/单独运行 Case 已检查
[ ] SUCCESS 有实际结果证据
[ ] Wu/Wl/CAS 来自实际结果
[ ] B_best、B_worst 已重新计算
[ ] SUCCESS 排序正确
[ ] 未完成项未参与排名
[ ] 表格风格参照 Splight-rk-16-boomerang.md
[ ] 结果明确时链接具体文件
[ ] 结果未知时链接 results/<case>/ 目录
[ ] 所有具体文件链接真实存在
[ ] 依赖旧数据的文字结论已重新检查
[ ] Markdown 公式格式正确
```

可执行：

```powershell
git status --short
git diff -- z-notes/boomerang-results/Splight-rk-<R>-boomerang.md
```

仅用于检查，不提交、不上传。

---

# 13. 最终回复格式

任务完成后简洁回复：

```text
已完成 RK-Boomerang 结果汇总更新。

参数
- 总轮数：<R>
- campaign 权重：<W>

结果 Markdown
- z-notes/boomerang-results/Splight-rk-<R>-boomerang.md

结果统计
- 总 Case：
- SUCCESS：
- 未完成/超时/UNKNOWN：
- campaign Case：
- campaign 新增/更新：

概率排名第一
- Case：
- Wu：
- Wl：
- CAS：
- B_best：
- B_worst：
- 预估概率：

检查
- 结果核验：通过/未通过
- 概率计算：通过/未通过
- 概率排序：通过/未通过
- 结果文件/目录索引：通过/未通过
- 链接存在性：通过/未通过
- Markdown 格式：通过/未通过

发生变化的旧结论
- ...

未解决问题
- 无
```

无法确认的内容必须写明原因，禁止猜测。
