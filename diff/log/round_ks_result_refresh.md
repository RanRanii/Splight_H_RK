# 已有结果 KS 列与十六进制大小写整理记录

本次没有重新求解 MILP，只重写已有结果文件中的密钥状态展示和十六进制大小写。

规则：

- `ks_global_0` 是主密钥输入差分状态，不是第 0 轮加密使用的轮密钥状态。
- 第 `r` 轮加密使用更新后的 `ks_global_{round_offset+r+1}`。
- `KS` 列显示 `round_ks_r = ks_global_{round_offset+r+1}`。
- 终止状态行没有加密轮，`KS` 显示为 `none`。
- 所有纯十六进制字符串统一写为大写。

| 配置 | 状态 | 校验问题 |
|---|---|---|
| 2-2-2 | updated |  |
| 2-3-2 | updated |  |
| 2-4-2 | updated |  |
| 2-6-2 | updated |  |
| 3-3-3 | updated |  |
| 3-4-3 | updated |  |
| 3-5-2 | updated |  |
| 3-6-2 | updated |  |
| 4-4-4 | updated |  |
| 5-4-3 | updated |  |
| 6-4-3 | updated |  |
| 7-4-3 | updated |  |
| 8-4-3 | updated |  |
