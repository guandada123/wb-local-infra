# GUI 自动化闸门：点之前先看屏幕上是什么

> 建立于 2026-11-24，起因是当天**差点把 274GB 数据抹掉**。脚本 `bin/wb-ui-guard.py`。

## 一、起因（不写清楚就会被人删掉）

那天要给时间机器加一块盘。因为 `tmutil setdestination` 在 macOS 26 上被 TCC 挡住（root 也不行），
于是改用界面操作——**用坐标点击在系统设置里连点了七八次**。

中途弹出一个对话框：要求**抹掉 ZHITAI** 才能用作备份磁盘。那是删掉全部数据的按钮。
当时是按 Esc 救回来的。

所以结论不是「下次小心点」，而是：**没出事靠的是临场反应，不是设计**。
同一天还有两处同类问题——恢复密钥出现在屏幕上被截屏读到；让用户执行 `pbpaste > key文件`，
结果命令自身覆盖了剪贴板，文件里存的是一条命令。

## 二、三道判据

| id | 判据 | 触发条件 | 动作 |
|---|---|---|---|
| D1 | 前台应用禁令 | 前台是 系统设置 / 磁盘工具 / 钥匙串访问 / SecurityAgent / 安装器 | 拒绝执行坐标点击，**不按键** |
| D2 | 危险关键词 | 模态框文本含 抹掉 / 抹除 / 格式化 / 初始化 / 删除卷 / erase / wipe / format… | **先按 Esc**，再拒绝 |
| D3 | 机密关键词 | 模态框文本含 恢复密钥 / recovery key | 拒绝，**绝不按 Esc** |
| — | fail-closed | 模态框存在但看不懂 / 屏幕读不到 / AX 超时 | 一律拒绝 |

两条容易写错的细节：

- **D2 与 D3 的动作相反。** 危险对话框要 Esc 取消；机密对话框按 Esc 会把密钥的唯一一次显示关掉，
  等于把用户的救命钥匙丢掉。这两件事共用一个「拦截」分支是错的。
- **英文词按词边界匹配**（`\bformat\b`），否则 `formatted` 会误命中，把正常流程打断；
  中文按子串（中文没有词边界问题）。

## 三、为什么它必须接线

PATH 实测顺序：`/opt/homebrew/bin`(第 13 位) 在 `~/.local/bin`(第 28 位) **之前**。
也就是说在 `~/.local/bin` 放同名脚本挡不住 `cliclick`；真能拦住的只有一个位置：

```
/opt/homebrew/bin/cliclick   ← 一条指向 Cellar 的软链（5.1）
```

`install-interlock` 把它换成 4 行 shim：先过闸门，再转发真身。原目标路径记在
`~/.local/etc/wb-ui-guard.json`，`remove-interlock` 一键还原。目录属 `guan:admin`，**不需要 sudo**。

接线后的自检**不能只看有没有输出**：`cliclick` 无参数时打的是
「You did not pass any commands…」（不含 `Usage` 字样），早期版本按 `Usage` 匹配会误判失败并自动回滚。
现在用 `cliclick p`（打印鼠标坐标）验证「真的转发到了真身」。

## 四、自身位断言

```bash
wb-ui-guard.py status      # rc=0 才算接线；rc=7 表示没接
```

它回答三件事：闸门文件在哪、`interlock: 已接线/未接线`、`PATH 解析` 指向谁。
没有这一条，闸门就只是「仓库里的一个文件」，和一段注释没有区别。

## 五、已知边界（诚实清单）

1. **只管 `cliclick`**。直接 `osascript -e '... click at {x,y}'`、或 AppleScript 的 `AXPress`
   不走这道闸门。它不是沙箱。
2. **只认前台应用与原生模态框**。网页里的 confirm 框不在 AX 树里，D1 只能靠前台应用兜。
3. **没做过实弹测试**。破坏性对话框刻意不制造——判据用 10 项故障注入 + 2 次变异测试反证，
   而不是拿真盘试。
4. **`brew upgrade cliclick` 会覆盖 shim**，状态退回「未接线」；`status` 会报 rc=7，重跑
   `install-interlock` 即可。这是设计上的可发现降级，不是静默失效。
5. **自检不写真实日志**。否则 `status` 的「历史拦截 N 次」会混进自检噪音，变成自己会涨的假计数。

## 六、维护

```bash
python3 bin/wb-ui-guard.py self-test        # 10 项，每项只注入一个条件
python3 bin/wb-ui-guard.py scan             # 只判定，不动屏幕（排障第一步）
python3 bin/wb-ui-guard.py install-interlock   # 接线
python3 bin/wb-ui-guard.py remove-interlock    # 还原 brew 软链
```

改词表就改 `bin/wb-ui-guard.py` 顶部的 `DENY_APPS` / `BLOCK_CN` / `BLOCK_EN` / `SECRET_CN` / `SECRET_EN`。

变异测试（改完判据必须做，否则不知道用例有没有强度）：

- 把「抹掉」从 `BLOCK_CN` 删掉 → `抹掉 ZHITAI 确认框` 那一项必须变红
- 让机密分支也调 `press_escape()` → `恢复密钥（不许按 Esc）` 那一项必须变红

两条都实测过：各让自检从 10/10 掉到 9/10，且**只有那一项**红。

拦截记录：`~/.local/log/wb-ui-guard.log`（内盘；写外置卷会 TCC EPERM）。
