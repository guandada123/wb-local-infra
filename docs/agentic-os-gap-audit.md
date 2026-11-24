# 对照：Agentic OS 那篇文章，我们落地了吗

> 审计日期 2026-11-24｜方法：逐条用命令取证，不引用旧结论
> 原文：公众号「Agent 紧箍咒」2026-11-17，讲开源项目 **Agentic OS**（modimihir07/agentic-os）
> `https://mp.weixin.qq.com/s/K9wxBqJXS8BIfndI8nQA5A`

## 一句话结论

文章的 6 个机制里，**4 个有等价或更强的实现**，1 个换了更稳的形态，**1 个判断后主动不做**。
文章自己承认的 3 条局限里，**2 条我们已经解决**，1 条（鉴权）半斤八两。

唯一真缺口是「本地 Markdown 经验资产没有全文检索」——已由 `~/.local/bin/mem-search.py` 补齐。
所以准确说法是：**该补的补了，不该照搬的没照搬**，不是「全文照做」。

## 一、六个机制逐条核对

| # | 文章机制 | 我们 | 取证命令 / 实测值 |
|---|---|---|---|
| 1 | 统一控制平面，状态可见 | ✅ 有，形态不同 | `lsof -nP -iTCP:3355 -sTCP:LISTEN` → 监听 `127.0.0.1:3355`；`curl` → **HTTP 200**；`hub-overview-server.py` 提供 `POST /api/hub/action` 白名单动作（confirm 模式 + 自定义头防 CSRF） |
| 2 | 关键词分派（`ROUTER_RULES`，高/中/低置信度） | ✅ 有，且是中文 | `autoloop-feishu-hub.py` 的 `COMMANDS` **11 条**：重试、群总结、协同、重推日报、季报、月报、周报、状态、巡检、待办、日报 |
| 3 | 子进程同步超时 30/180/60 秒 | ⚠️ 换成更稳的形态 | 不用「同步等子进程」，走 **launchd 异步派发 + 状态落 hub.db**；`launchctl list \| grep -c 'com\.user\.'` → **34** 个任务；单次网页动作仍设 `timeout: 60`（`hub-overview-server.py:56`） |
| 4 | **78 个 HTTP 接口** | ❌ 主动不做 | `grep -cE 'path == \|startswith\(\|elif p == \|route'` → **6** 个分支。那 78 个是为三个 CLI 做前端调用通道，我们没有三个 CLI 要接 |
| 5 | SQLite FTS5 全文检索 | ✅ 做了，且更强 | `mem-search.py stats` → **963 文件 / 81,105 片段 / 43.7MB**；中文单字切分（文章的 `trigram` 对「止损」「仓位」这类 2 字词全部失效，实测返回空） |
| 6 | 共享记忆 / 文件层 | ✅ 有 | `rules.json` 共 **6** 条规则，其中「协同链-诊断」`emits: chain.review` → 串到「协同链-复核」 |

## 二、文章自认的三条局限，我们的位置

| 文章局限 | 我们 | 证据 |
|---|---|---|
| 做不到真正的多 Agent 串联，仍需人肉中转 | ✅ 已解决 | `~/.agent-autoloop/app/kernel/decide.ts:43` `MAX_HOPS = 8`；同文件 `:231` `tooDeep` 熔断，`:248` 输出「同一条处理链已超过 8 层」 |
| `server.py` 无鉴权，CORS 仅本地 | ⚠️ 同级 | 3355 也只绑 `127.0.0.1`；多了自定义头防 CSRF。飞书通道靠 bot 身份 + 白名单，非通用鉴权 |
| 同步模式撑不住长任务 | ✅ 已解决 | 全链路异步：launchd 派发 → 状态落 hub.db → 外部闸门核验 |

## 三、主动不做的两件事与理由

**① 78 个 HTTP 接口**
那 78 个的作用是让网页前端能查询/调用三个 CLI 的状态与命令。我们没有一个 Web 聊天框去驱动 CLI，
入口是飞书群指令 + 3355 只读看板，接口数量没有意义。**加接口=给没人用的入口修高速公路。**

**② 网页版聊天框驱动 CLI（FastAPI + 子进程）**
文章自己的第三条局限就是这条路的天花板：`subprocess.run` 同步等待，复杂任务必然超时。
我们已经用 launchd 异步 + 事件链绕过了这个问题，再补一个同步网页入口属于倒退。

**什么情况下要重新考虑**：如果要给非本机用户（或手机端）一个统一的自然语言入口，而不是只有飞书群，
那么「网页聊天 → 派活」就有价值。此时仍应复用现有事件链，而不是照搬 `subprocess.run`。

## 四、一处必须记下的记忆错误

旧记录（含 `USER.md`）写「`rules.json` 有 93 条规则」。2026-11-24 实测 **6 条**，
于是把 10 个历史备份全数了一遍：

```
rules.json                          6
rules.json.bak-20261111-pre-askfirst  3
rules.json.bak-20261111-pre-emits     3
rules.json.bak-20261112-pre-triage-work 5
rules.json.bak-20261113-pre-review-split 6
（其余备份均为 6）
```

**从未出现过 93 条**。属于记忆写错（大概率把「93 条铁律」串到这里），不是规则被静默丢弃。
`USER.md` 里那句仍待更正。

## 五、怎么复查这份表

```bash
# 1. 控制平面
lsof -nP -iTCP:3355 -sTCP:LISTEN; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3355/

# 2. 分派白名单
grep -A14 '^COMMANDS = \[' ~/.local/bin/autoloop-feishu-hub.py

# 3. 调度器规模
launchctl list | grep -c 'com\.user\.'

# 4. 事件链熔断
grep -n 'MAX_HOPS' ~/.agent-autoloop/app/kernel/decide.ts

# 5. 全文检索规模
~/.workbuddy/binaries/python/versions/3.13.12/bin/python3 ~/.local/bin/mem-search.py stats

# 6. 规则条数
python3 -c "import json,os;print(len(json.load(open(os.path.expanduser('~/.agent-autoloop/rules.json')))['rules']))"
```
