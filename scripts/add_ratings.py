"""一次性脚本：给 catalog.yaml 每个 account 插入 rating 块。

评分口径（三项各 1-5，档位由 gen_rating_table.py 统一算）：
  value      额度价值：日均可用额度 × 有效期折算
  capability 能力覆盖：模型数量/质量与场景覆盖
  automation 领取可靠性：当前路线能否稳定入账（5=external 直签，1=纯手签/未开通）

已存在的 rating 块会被覆盖，可反复运行。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog.yaml"

# id -> (value, capability, automation, review, best_for)
DATA: dict[str, tuple[int, int, int, str, str]] = {
    "workbuddy": (
        4, 4, 5,
        "额度不算最高但最省心：external 直签零交互，30 天有效期够攒，7 天连签再加 1000。混元/DeepSeek/GLM/Kimi/MiniMax 多模型可选，办公文档链路完整。",
        "日常编码主力 + 腾讯文档/办公场景",
    ),
    "minimax": (
        5, 4, 5,
        "可累积额度里的天花板：400/天，第 4、7 天当日 1000，30 天有效期。external 直签无 GUI 无 UAC，不受客户端活动推广干扰，是当前唯一完全无感的路线。模型限于 MiniMax 自家（M3/M2.7/H3），多模态是加分项。",
        "高频重度使用、多模态任务",
    ),
    "traework": (
        3, 4, 3,
        "额度中等（150/天）但 31 天有效期 + 每月登录赠 500，16+ 模型与 MCP 支持是优势。领取靠提权 UI + OCR 点击，窗口改版即失效，是五家里最脆的一环。与 TraeCode 共用同一积分账户，别重复计数。",
        "需要多模型切换、MCP 工具链的编码任务",
    ),
    "autoclaw": (
        4, 2, 2,
        "200/天可累积，本地执行能力全，有思考过程。但模型只有智谱 GLM 一家（旧记的五模型池是错的），场景覆盖窄；签到藏在灵感中心任务卡里靠 OCR 定位，首页横幅还受服务端开关控制，随时可能定位不到；实测资源时常紧张。有效期由服务端下发、台账无法确定。",
        "只用 GLM 就够、需要本地执行能力的场景；资源紧张时段别指望它",
    ),
    "lobsterai": (
        2, 4, 1,
        "纸面 100/天、10+ 模型（GPT-4o/Claude/Gemini/DeepSeek）看着香，但服务端当前根本没下发签到活动（slot 返回 empty），external 脚本只能报 no-activity。UI 路线已打通，冷启动 20s + 广告遮罩，实测收益仅 +100。属于占着坑不产粮。",
        "活动下发后再评估；当前只作备用",
    ),
    "dumate": (
        4, 3, 1,
        "500/天是全场第二高，但领取上限（cap）始终没测出来，一期不敢自动领。百度系搜索/办公/文档能力，适合资料型任务。只要把 cap 摸清就能进自动盘。",
        "搜索资料、文档处理；待摸清上限后启用",
    ),
    "todesk": (
        2, 2, 1,
        "100/天 + 7 天连签 600，额度一般且同样卡在 cap 未测出。能力集中在远控，和编码/办公场景几乎不重叠。优先级低。",
        "远程协助场景，顺手领",
    ),
    "qclaw": (
        2, 2, 1,
        "每月登录领 500，腾讯电脑管家系，远控/本地能力为主。不自动启动客户端，纯月度事项，错过要等下月。",
        "月度顺手领，非主力",
    ),
    "joycode": (
        4, 3, 1,
        "一次性 10000 积分，量很大但 10-16 到期，属于有死期的存量。京东云系，编码能力。当前策略是永不自动、用时再开。",
        "到期前集中消耗，别放着烂掉",
    ),
    "kimi": (
        3, 4, 1,
        "周期制额度（下次重置 10-14），Kimi K3 + 100 万上下文是长文档场景的独门优势。不自动领，按周期重置。",
        "超长文档阅读、办公写作",
    ),
    "catpaw": (
        2, 3, 1,
        "新用户 1000 一次性，365 天有效期，美团系编码产品。没有每日签到，领完就没有后续产出。",
        "一次性消耗完即可",
    ),
    "mavis": (
        4, 4, 1,
        "每天登录领 1000 万 Token，量级碾压所有按积分计的产品，能力覆盖也全。致命伤是当日清零——不开就是零。所以它永远排在用时再开那一档，不进自动签到。",
        "当天有重活要烧量时才开",
    ),
    "monkeycode_token": (
        4, 3, 1,
        "同样是 10M Token/天当日清零，长亭百川系，编码向。逻辑同 Mavis：额度巨大但必须当天用掉。",
        "当天集中编码任务",
    ),
    "monkeycode_credit": (
        1, 3, 1,
        "100/天的积分档，但主人 2026-09-28 已确认 MonkeyCode 不用签到，故移出待办。台账保留仅为记录额度规则，不代表可领取。",
        "无（不再出现在待办）",
    ),
    "loomy": (
        3, 3, 1,
        "5000/天当日清零，另有永久 6500 托底，讯飞系办公/搜索/文档。清零额度里算厚道的，但同样要当天开。",
        "办公文档批处理当天做",
    ),
    "coze": (
        2, 3, 1,
        "1500/天当日清零，字节系多模态 + 搜索。额度中等，清零机制决定它只能当临时补充。",
        "多模态/搜索类临时任务",
    ),
    "xiaohuanxiong": (
        1, 2, 1,
        "300/天当日清零，商汤系办公文档向。额度在这个量级已经很难支撑一次像样的任务。",
        "低频办公辅助",
    ),
    "qwenwork": (
        1, 2, 1,
        "100/天当日过期，阿里系办公文档。额度太小，属于聊胜于无。",
        "几乎不值得专门启动",
    ),
    "accio": (
        1, 2, 1,
        "200/天当日清零，阿里国际电商向。场景窄 + 额度小，优先级垫底。",
        "跨境电商相关任务才考虑",
    ),
    "stepfun": (
        1, 2, 1,
        "20/天当日过期，阶跃星辰编码向。全场最低额度，基本可以忽略。",
        "基本忽略",
    ),
}


def render(acc_id: str, item: tuple[int, int, int, str, str]) -> list[str]:
    v, c, a, review, best = item
    return [
        f"    rating:",
        f"      value: {v}",
        f"      capability: {c}",
        f"      automation: {a}",
        f'      review: "{review}"',
        f'      best_for: "{best}"',
        f'      owner_note: ""',
    ]


def main() -> int:
    lines = CATALOG.read_text(encoding="utf-8").split("\n")
    # 定位每个 account 块的起止行（块内缩进行为 4，- id: 缩进行为 2）
    blocks: list[tuple[str, int, int]] = []
    start: int | None = None
    cur_id = ""
    for idx, line in enumerate(lines):
        if line.startswith("  - id:"):
            if start is not None:
                blocks.append((cur_id, start, idx))
            start = idx
            cur_id = line.split(":", 1)[1].strip()
    if start is not None:
        blocks.append((cur_id, start, len(lines)))

    # 从后往前改，避免行号漂移
    for acc_id, s, e in reversed(blocks):
        if acc_id not in DATA:
            continue
        # 去掉块尾空行，确定真实末行
        end = e
        while end > s and not lines[end - 1].strip():
            end -= 1
        # 剥掉已有 rating 块
        inner = lines[s + 1 : end]
        cleaned: list[str] = []
        skipping = False
        for ln in inner:
            if ln.strip() == "rating:":
                skipping = True
                continue
            if skipping:
                if ln.startswith("      ") or not ln.strip():
                    continue
                skipping = False
            cleaned.append(ln)
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()
        lines[s + 1 : end] = cleaned + render(acc_id, DATA[acc_id]) + [""]

    CATALOG.write_text("\n".join(lines), encoding="utf-8")
    print(f"已写入 rating 字段：{len(DATA)} 个账户 -> {CATALOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
