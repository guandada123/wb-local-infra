#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聚合各项目最近 CI 结果（只读 gh CLI），输出人读文本。
- 仓库名从各项目 git remote 取，不写死
- 单仓约 1.8s，4 仓约 8s，故只作为「按需动作」，不进 /api/hub/overview 主接口
- 无 gh / 未认证 / 无 workflow / 超时 → 该仓标注原因，不中断其它仓
用法：
  python3 hub-ci-status.py                     # 人读文本
  python3 hub-ci-status.py --json              # JSON 到 stdout（供服务端缓存）
  python3 hub-ci-status.py --json --out PATH   # JSON 写文件（后台刷新用）
"""
import argparse, json, os, re, shutil, subprocess, sys

QUEUE = "/Volumes/ZHITAI/WorkBuddy/Claw/.autopilot/QUEUE.md"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(QUEUE)))  # <base>/Claw/.autopilot/QUEUE.md
PROJECTS = ["Claw", "StockInsight", "project-monitor-fusion", "engineering-audit-kit"]
GH = shutil.which("gh") or "/opt/homebrew/bin/gh"
ICON = {"success": "✅", "failure": "❌", "cancelled": "⚪️", "skipped": "⏭", None: "⏳"}

def run(argv, timeout=20):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return -1, "", "调用超时"
    except Exception as e:
        return -1, "", f"{type(e).__name__}: {e}"

def repo_of(path):
    rc, out, _ = run(["git", "-C", path, "remote", "get-url", "origin"], timeout=6)
    if rc != 0 or not out:
        return None
    m = re.search(r"github\.com[:/]+([^/]+/[^/\s]+?)(?:\.git)?$", out)
    return m.group(1) if m else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="输出 JSON（供服务端缓存读）")
    ap.add_argument("--out", help="JSON 写入该文件（后台刷新用）")
    args = ap.parse_args()

    if not os.path.exists(GH):
        msg = "CI 状态：未找到 gh CLI，无法查询（只读动作，不影响工作台其它功能）"
        if args.json:
            print(json.dumps({"ok": False, "error": "gh not found", "repos": {}}, ensure_ascii=False))
        else:
            print(msg)
        return 0

    lines = [f"CI 状态（{len(PROJECTS)} 仓 · 各取最近 3 次）"]
    repos = {}
    for name in PROJECTS:
        path = os.path.join(BASE_DIR, name)
        if not os.path.isdir(os.path.join(path, ".git")):
            lines.append(f"  ⚪️ {name}: 本地无 git 仓库，跳过")
            repos[name] = {"conclusion": None, "reason": "no-git"}
            continue
        repo = repo_of(path)
        if not repo:
            lines.append(f"  ⚪️ {name}: 无 GitHub remote")
            repos[name] = {"conclusion": None, "reason": "no-remote"}
            continue
        rc, out, err = run([GH, "run", "list", "--repo", repo, "--limit", "3",
                            "--json", "status,conclusion,workflowName,displayTitle,createdAt"])
        if rc != 0:
            reason = (err or "未知错误").splitlines()[0][:80]
            lines.append(f"  ⚪️ {name} ({repo}): 查询失败 · {reason}")
            repos[name] = {"conclusion": None, "reason": reason}
            continue
        try:
            runs = json.loads(out or "[]")
        except Exception:
            lines.append(f"  ⚪️ {name} ({repo}): 返回非 JSON")
            repos[name] = {"conclusion": None, "reason": "bad-json"}
            continue
        if not runs:
            lines.append(f"  ⚪️ {name} ({repo}): 无 CI 记录")
            repos[name] = {"conclusion": None, "reason": "no-runs", "repo": repo}
            continue
        head = runs[0]
        state = head.get("conclusion") or head.get("status")
        seq = "/".join((r.get("conclusion") or r.get("status") or "?") for r in runs)
        when = (head.get("createdAt") or "").replace("T", " ")[5:16]
        wf = (head.get("workflowName") or "")[:26]
        repos[name] = {"repo": repo, "conclusion": state, "seq": seq,
                       "at": when, "workflow": wf, "title": (head.get("displayTitle") or "")[:52]}
        lines.append(f"  {ICON.get(state, '❓')} {name} ({repo})")
        lines.append(f"     最近: {state} · {wf} · {when}")
        lines.append(f"     近 3 次: {seq}")
        if head.get("displayTitle"):
            lines.append(f"     提交: {head['displayTitle'][:52]}")

    if args.json or args.out:
        payload = {"ok": True, "generated_at": subprocess.run(
            ["date", "+%Y-%m-%dT%H:%M:%S%z"], capture_output=True, text=True).stdout.strip(),
            "repos": repos}
        blob = json.dumps(payload, ensure_ascii=False, indent=1)
        if args.out:
            try:
                os.makedirs(os.path.dirname(args.out), exist_ok=True)
                with open(args.out, "w", encoding="utf-8") as f:
                    f.write(blob)
            except Exception as e:
                print(f"写缓存失败：{e}", file=sys.stderr)
                return 1
        if args.json:
            print(blob)
        return 0

    print("\n".join(lines))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
