"""飞书 post 富文本渲染（报告「一眼看清」的最后一公里）。

飞书 text 消息**不渲染 markdown 表格**：`| 事项 | 结论 |` 会原样显示成一堆管道符。
本模块把四段骨架报告转成 post 富文本：段标题加粗 + 分割线，②③ 表格拆成
「• 事项 → 状态结论」/「• 事项｜责任人｜截止｜验收」逐条列表，与 18:32 样本同形态。

被 autoloop-feishu-push.py 与 autoloop-feishu-hub.py 共用，避免两处各写一份。
"""

import json

BOLD_PREFIX = ("【盘面信息·", "一句话：")
SECTION_PREFIX = ("①", "②", "③", "④")


def render_post(text):
    """返回飞书 post 消息的 content 对象（zh_cn.content 为二维数组）。"""
    rows = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith(SECTION_PREFIX):
            rows.append([{"tag": "text", "text": "────────────"}])
            rows.append([{"tag": "text", "text": s, "style": ["bold"]}])
            continue
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not cells or all(set(c) <= set("-: ") for c in cells):
                continue  # 表格分隔行
            if cells[0] == "事项":
                continue  # 表头由段标题表达，不再重复
            if len(cells) == 2:
                s = f"• {cells[0]} → {cells[1]}"
            elif len(cells) == 4:
                s = f"• {cells[0]}｜责任人 {cells[1]}｜截止 {cells[2]}｜验收 {cells[3]}"
            else:
                s = "• " + "｜".join(cells)
        elif s.startswith("- "):
            s = "• " + s[2:]
        elem = {"tag": "text", "text": s}
        if s.startswith(BOLD_PREFIX):
            elem["style"] = ["bold"]
        rows.append([elem])
    return {"zh_cn": {"title": "", "content": rows}}


def post_content(text):
    return json.dumps(render_post(text), ensure_ascii=False)
