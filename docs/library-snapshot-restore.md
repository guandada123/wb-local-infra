# 资料库「00 对话成果档案」快照与恢复

> 建立 2026-11-25。起因：对账发现 47 份历史档案**只有云端一个完整副本**。

## 一、快照在哪、有什么

| 项 | 值 |
|---|---|
| 位置 | `/Volumes/ZHITAI/WorkBuddy/_snapshots/library-00-20261125/` |
| 内容 | 47 份 Markdown（对应当日资料库「00 对话成果档案」全部条目，含台账与总册） |
| 体量 | 384,192 B（375 KB） |
| 校验 | `_snapshot-manifest.json` 记每份 `sha256` 前 16 位 + 字节数 |
| 来源 | 资料库 space `YHKOkiUC0ilqsTpMOwxtYw` / folder `NO8kdWuj4SS5PizPfbZEjh` |

**这是一次性快照，不是自动同步。** 之后新增的档案不会自动进来。判断快照是否过期：

```bash
# 云端当前份数
/usr/bin/python3 "$API" space.workspace.list-nodes \
  --space-id YHKOkiUC0ilqsTpMOwxtYw --parent-node-id NO8kdWuj4SS5PizPfbZEjh --limit 200 \
  | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["data"]["nodes"]))'
# 快照份数
ls /Volumes/ZHITAI/WorkBuddy/_snapshots/library-00-20261125/*.md | wc -l
```

其中 `API=/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/plugins/workbuddy-builtin/skills/library/space_api.py`。

## 二、恢复（云端丢失/误删时用）

### 单份恢复 — 用 `create-doc`（推荐，不需要上传 COS）

```bash
python3 "$API" space.importer.create-doc --stdin <<'JSON'
{"space_id":"YHKOkiUC0ilqsTpMOwxtYw",
 "parent_id":"NO8kdWuj4SS5PizPfbZEjh",
 "title":"对话成果档案_20261108_马厩收尾触发词补齐",
 "markdown":"<快照文件正文，去掉首行 # 标题>"}
JSON
```

返回 `{"data":{"nodeBlockId":"...","url":"..."}}`。

### 两个必踩的格式坑（2026-11-25 演练实测）

1. **`title` 会被渲染成文档 H1**。若 `markdown` 里仍带首行 `# 标题`，结果就是两个 H1（标题重复）。
   正确做法：`title` 传档案标题，`markdown` 传**去掉首行 `# 标题`** 的正文。
2. **转义层级会多一层**：快照里的 `\_` 恢复后再导出会变成 `\\_`。
   不影响阅读，但**逐字节比对一定不等**，别据此判"恢复失败"。

### 验证恢复是否完整（用行级比对，别用逐字节）

```python
# 剥掉所有 H1 行 + 反转义后按行比对
def clean(s):
    s = s.replace("\\\\_", "_").replace("\\_", "_").replace("\\\\~", "~").replace("\\~", "~").replace("\\\\", "")
    return [l.rstrip() for l in s.splitlines() if l.strip() and not l.startswith("# ")]
```

2026-11-25 演练结果：25 行全部一致，`difflib` 相似度 **1.0000**，零缺失零多余。

### 批量恢复

串行 + **每份之间 sleep 3 秒**。实测无节流时第 11 份起全部返回
`code=50001 提交过于频繁`（10 成功 / 37 失败）；加 3 秒间隔 + 退避 10/25/45 秒后 37 份 0 失败。

**建议恢复到「99 临时与测试」（`ogcKsWpBNRdCxFfe5VSjlX`）而不是直接进 00** ——
恢复是批量破坏性操作，先落在隔离区核对，再逐份 `move-node` 回 00，出错可停。

## 二·五、怎么判断快照是否过期 / 云端是否被改

三级检查，成本递增。**日常只看 L1+L2**（一次 `list-nodes` 全拿到）。

| 级别 | 方法 | 成本 | 能发现 |
|---|---|---|---|
| **L1 份数** | `list-nodes` 条数 vs manifest 的 `count` | 1 次 API | 有档案被新增/删除 |
| **L2 updatedAt** | 每份的 `updatedAt` vs manifest 里存的值 | 同上（同一调用） | **哪一份被编辑过** |
| **L3 内容** | 导出该份 + 比 `sha256_16` | 每份 1 次导出 + 1 次下载 | 内容是否真的变了 |

L2 的判据很直接：manifest v2 里每份都存了 `node_id` / `node_version` / `updated_at`，
`list-nodes` 返回的 `updatedAt` 与存档值不一致 → 那份被改过，需要复查。

**sha 可直接作判据，不需要归一化**（2026-11-25 实测）：导出是确定性的 ——
同一 node 连续两次导出字节完全相同，抽检三份（3,519 / 6,761 / 37,368 B）全部逐字节一致。
所以 L3 比对不必像「恢复验证」那样剥 H1 层与转义 —— 那是 `create-doc` 回写路径才有的差异。

⚠️ 注意：`updatedAt` 在「移动节点」时也会变（内容没变）。所以 L2 报出来的是**疑似**，
要定性仍得走 L3。

## 三、导出快照的命令（重建时用）

```bash
# 1. 建导出任务（kind 必须是节点真实类型：doc→Markdown / database→CSV / web→HTML）
python3 "$API" space.manage.export-node --node-id <ID> --kind doc
#    → {"data":{"taskId":"se-..."}}

# 2. 轮询取下载链接
python3 "$API" space.manage.query-export-progress --task-id <taskId>
#    → {"data":{"status":"done","cosUrl":"https://..."}}

# 3. 下载（cosUrl 有时效，拿到就立刻下）
```

## 四、能力边界（实测，别再写错）

| 后端 | 删除 | 移动 | 上传 |
|---|---|---|---|
| WorkBuddy 资料库 | ❌ 无接口（`space_api.py` 54 个 API 里只有 database 的删记录/删字段） | ✅ `space.workspace.move-node` | ✅ `space.importer.create-doc` / `import-local-file` |
| 腾讯文档 | ✅ `manage.delete_file`（进回收站） | ✅ `move_file_to_space` | ✅ |

清理重复项用「移入 99 隔离」而不是删除；真删除只能由用户在库里点。
