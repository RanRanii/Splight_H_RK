# 任务：更新 Splight RK 16/17/18 轮 Boomerang 搜索结果 Markdown

你当前位于 `Splight-H-RK` 仓库根目录。

本任务只做：

> 读取已经完成的搜索结果，更新 16、17、18 轮结果 Markdown。

**禁止重新运行搜索。禁止修改搜索代码。**

---

## 1. 需要读取的运行脚本

先读取以下三个文件，明确每个脚本包含哪些 Case：

```text
run/run_16_636_recommended_queue.ps1
run/run_17_636_recommended_queue.ps1
run/run_18_636_recommended_queue.ps1
```

这三个脚本只用于确认：

* Case 列表；
* Case 命名方式；
* 队列运行规则；
* 输出目录关系。

不要修改这些 `.ps1` 文件。

---

## 2. 需要读取的运行日志

读取：

```text
run/run_16_636_recommended_queue.log
run/run_17_636_recommended_queue.log
run/run_18_636_recommended_queue.log
```

如果存在对应目录，也读取：

```text
run/logs/run_16_636_recommended_queue/
run/logs/run_17_636_recommended_queue/
run/logs/run_18_636_recommended_queue/
```

通过日志判断每个 Case 本次运行状态，例如：

```text
START
SKIP
RETRY
DONE
STOP
```

不要仅根据 `results/<case>/` 目录是否存在判断任务是否成功。

---

## 3. 最终数据源

最终实验数据必须以本地：

```text
results/
```

中的实际结果为准。

对于每个 Case，优先按以下顺序读取：

```text
results/<case>/exact_summary.json

results/<case>/.json/<r0>-<rm>-<r1>.json

results/<case>/terminal_print.txt
```

若某个文件不存在，再使用对应运行日志辅助判断。

禁止：

* 根据文件名猜测概率；
* 从旧 Markdown 直接复制结果；
* 因目录存在就判断为 SUCCESS。

---

# 4. 需要更新的三个文件

只更新：

```text
z-notes/boomerang-results/Splight-rk-16-boomerang.md

z-notes/boomerang-results/Splight-rk-17-boomerang.md

z-notes/boomerang-results/Splight-rk-18-boomerang.md
```

不要修改其他 Markdown。

---

# 5. Case 归属规则

对于 Case：

```text
r0-rm-r1_weight
```

按照：

```text
r0 + rm + r1
```

判断总轮数。

例如：

```text
8-2-6_636
```

属于：

```text
8 + 2 + 6 = 16轮
```

因此：

* `r0 + rm + r1 = 16` → 16轮 Markdown
* `r0 + rm + r1 = 17` → 17轮 Markdown
* `r0 + rm + r1 = 18` → 18轮 Markdown

三个 Markdown 应表示当前本地仓库中对应总轮数的**最新完整结果快照**。

不能只保留此次 queue 中出现的 Case。

---

# 6. 特别规则

## 6.1 16轮

`run_16_636_recommended_queue.ps1` 中没有：

```text
8-2-6_636
```

原因是该 Case 已经单独运行。

因此：

**不要从16轮 Markdown 中删除 `8-2-6_636`。**

读取：

```text
results/8-2-6_636/
```

中的最新本地结果。

---

## 6.2 17轮

17轮历史结果中可能存在：

```text
*_424
*_626
```

等非 `636` 权重结果。

只要：

```text
r0 + rm + r1 = 17
```

且结果真实存在，就保留。

不要因为本次 queue 是 `636` 就删除合法历史结果。

---

## 6.3 18轮

必须重新根据当前：

```text
run/run_18_636_recommended_queue.ps1
```

以及：

```text
run/run_18_636_recommended_queue.log
```

统计队列执行情况。

不要直接保留旧 Markdown 中类似：

```text
计划11
跳过1
新完成10
```

这样的历史数字。

必须重新计算。

另外重点检查：

```text
9-2-7_636
```

查看当前是否已经生成：

```text
results/9-2-7_636/exact_summary.json
```

如果已有最新结果，则更新旧状态。

如果仍然没有完整结果，则保持未完成状态，并引用最新日志。

---

# 7. SUCCESS 结果需要提取的数据

对于有完整 concrete / exact 结果的 Case，提取：

```text
Case
Wu
Wl
CAS
Exact状态
求解时间
```

如果结果中还有其他必要字段，可以保留。

不要凭旧 Markdown 猜测数值。

---

# 8. 统一计算预估概率

对每个 SUCCESS Case 重新计算：

```text
B_best = 2*Wu + 2*Wl + 2*CAS
```

```text
B_worst = 2*Wu + 2*Wl + 2.5*CAS
```

对应：

```text
2^(-B_worst) <= P_boom <= 2^(-B_best)
```

Markdown 中写成数学形式：

```markdown
$2^{-B_{\mathrm{worst}}} \le P_{\mathrm{boom}} \le 2^{-B_{\mathrm{best}}}$
```

如果：

```text
B_best = B_worst
```

可以直接写：

```markdown
$2^{-B_{\mathrm{best}}}$
```

---

# 9. 排序规则

16、17、18轮三个文件必须采用完全相同的排序规则。

SUCCESS Case 按：

```text
1. B_best 从小到大
2. B_worst 从小到大
3. Case 名称按字典序
```

排序。

这等价于：

> 按预估 Boomerang 概率从高到低排序。

注意：

```text
B 越小 → 概率越高
```

不要按照概率字符串进行文本排序。

---

# 10. 16轮旧排序必须修改

当前16轮 Markdown 如果仍然使用：

```text
S = 2*(Wu + Wl + 2*CAS)
```

进行排名，必须修改。

`S` 可以保留作为辅助数据，但：

**不能再作为主排序依据。**

16/17/18轮全部统一使用：

```text
B_best
B_worst
```

进行概率排序。

---

# 11. Markdown 主表格式统一

三个文件的 SUCCESS 主表尽量统一成：

```markdown
| 排名 | Case | Exact状态 | Wu | Wl | CAS | S | 预估概率 | 求解时间 | 结果 |
|---:|---|---|---:|---:|---:|---:|---|---:|---|
```

其中：

```text
排名
```

表示按照预估概率计算得到的排名。

未完成、超时、无结果的 Case：

* 不参加 SUCCESS 概率排名；
* 放在 SUCCESS 表之后的单独表格中。

---

# 12. 添加可 Ctrl+点击 的结果链接

Markdown 文件位于：

```text
z-notes/boomerang-results/
```

结果位于：

```text
results/
```

因此固定相对路径前缀是：

```text
../../results/
```

对于 SUCCESS Case，优先链接 concrete JSON，例如：

```markdown
[结果](../../results/8-2-8_636/.json/8-2-8.json)
```

也可以同时加入：

```markdown
[Exact](../../results/8-2-8_636/exact_summary.json)
```

例如：

```markdown
[结果](../../results/8-2-8_636/.json/8-2-8.json) · [Exact](../../results/8-2-8_636/exact_summary.json)
```

对于未完成 Case：

如果没有正式 JSON，不允许创建不存在的链接。

只能链接真实存在的：

```text
terminal_print.txt
```

或者对应日志。

例如：

```markdown
[日志](../../results/9-2-7_636/terminal_print.txt)
```

---

# 13. 链接必须验证

生成链接前必须检查目标文件真实存在。

要求：

```text
每一个 Markdown 链接对应的文件必须存在。
```

不能生成死链接。

最终要求这些链接在 VS Code 中：

```text
Ctrl + 点击
```

可以直接打开。

---

# 14. 同步更新 Markdown 中其他依赖结果的数据

不能只修改主表。

如果最新结果发生变化，同时检查并更新：

```text
文档日期
SUCCESS数量
未完成数量
超时数量
队列执行摘要
概率阈值分类
结构观察
最优Case
新增结果说明
数据入口说明
```

如果原文字段依赖旧数据，则必须同步修改。

如果某段只是背景说明且仍然正确，则保留，不要无意义重写。

---

# 15. 不允许修改的内容

禁止修改：

```text
results/
run/*.ps1
Python代码
MILP模型
搜索算法
其他轮数Markdown
```

不要：

```text
重新运行搜索
删除实验结果
覆盖实验JSON
修改原始日志
```

本任务只做：

```text
读取 → 核验 → 排序 → 更新 Markdown
```

---

# 16. 更新完成后的验证

完成三个 Markdown 后检查：

### 16轮

所有 Case：

```text
r0 + rm + r1 = 16
```

### 17轮

所有 Case：

```text
r0 + rm + r1 = 17
```

### 18轮

所有 Case：

```text
r0 + rm + r1 = 18
```

然后检查：

```text
[ ] 所有 SUCCESS 数据来自本地 results
[ ] Wu/Wl/CAS 与原结果一致
[ ] B_best 计算正确
[ ] B_worst 计算正确
[ ] 排名按概率从高到低
[ ] 未完成项没有参与 SUCCESS 排名
[ ] 所有链接指向真实文件
[ ] 16/17/18使用统一概率定义
[ ] 16轮不再按 S 作为主排序
[ ] 18轮队列统计已重新计算
```

---

# 17. 最后检查 Git 修改范围

运行：

```powershell
git status --short
```

再运行：

```powershell
git diff -- `
  z-notes/boomerang-results/Splight-rk-16-boomerang.md `
  z-notes/boomerang-results/Splight-rk-17-boomerang.md `
  z-notes/boomerang-results/Splight-rk-18-boomerang.md
```

确认本任务最终只修改：

```text
Splight-rk-16-boomerang.md
Splight-rk-17-boomerang.md
Splight-rk-18-boomerang.md
```

如果发现其他文件被意外修改，不要提交这些额外修改。

---

# 18. 最终回复格式

任务完成后不要长篇解释。

只按照下面格式回复：

```text
已完成16/17/18轮结果汇总更新。

16轮
- 总Case：
- SUCCESS：
- 未完成：
- 概率排名第一：
- 概率区间：

17轮
- 总Case：
- SUCCESS：
- 未完成：
- 概率排名第一：
- 概率区间：

18轮
- 总Case：
- SUCCESS：
- 未完成：
- 概率排名第一：
- 概率区间：

检查
- 概率排序：通过/未通过
- 结果链接存在性：通过/未通过
- Ctrl+点击相对路径：通过/未通过
- git diff仅包含3个目标Markdown：是/否

发生变化的旧结论：
- ...
```

如果某项无法确认，明确写：

```text
无法确认：原因
```

禁止猜测。
