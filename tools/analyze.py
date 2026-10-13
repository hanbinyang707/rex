#!/usr/bin/env python3
"""把校对好的转写稿交给 Claude 做分析，开一个之后能接着聊的会话。

    python3 tools/analyze.py 前缀 [--cwd 目录]

读 <前缀>.txt（和 <前缀>.校对.md 里拿不准的那几处），分析写进 <前缀>.分析.md，
文件头上写着怎么回到这个会话：

    cd ~/Recordings && claude --resume <会话号>

由 rex.sh 的 `rex go` 调用。

## 为什么是「开一个会话」，不只是写一份报告

分析报告是起点，真正有用的往往是看完报告之后的追问——「第 40 分钟那段他到底什么意思」
「把我说的那几个计划列出来」。所以分析用一个固定的会话号跑（`--session-id`），会话存在
`--cwd` 对应的项目下，之后 `claude --resume` 回到同一个上下文：稿子、校对报告、第一轮分析
都在里面，不用再粘一遍。

桌面 App 的会话列表里看不到命令行开的会话（实测），所以报告里给的是终端命令。

## 分析要什么，你说了算

默认提示词在下面（`DEFAULT`）；`~/.config/rex/analysis-prompt.md` 存在就用它——不同的录音
（会议、访谈、讲座）要的东西不一样，改那个文件就行，不用动代码。

## 隐私

和 proofread.py 一样：整份稿子会发给 Claude，走本机 `claude` 命令行自己的登录（终端里指向
别家接口的 ANTHROPIC_* 变量会被清掉，见 claude_cli.py）。只有 `rex go` 走这一步。

## 输出

进度写 stderr；stdout 只给 rex.sh 读的一行：`SESSION 会话号`，或者 `ACCOUNT 原因`（退出码 3）。
"""

import argparse
import datetime
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_cli  # noqa: E402
import proofread  # noqa: E402  load_state / read_entries / stamp

CUSTOM = os.path.expanduser("~/.config/rex/analysis-prompt.md")
TIMEOUT = 900

# 系统提示的开头，写死，不随 analysis-prompt.md 换。2026-10-12 第一次真跑：原来把校对报告「拿不准、
# 没改的（112）——请你确认」那一节原样附在稿子后面，连「对的话告诉分析那个会话」一起。Claude 把它当成了
# 任务，回了一句「我先找到稿子文件，逐条核对这 112 条建议、确认的直接改进稿子里」就结束了（工具是关的，
# 它什么也做不了），3.1 万个输出 token 全花在打算上。所以：要求放系统提示；材料用标签包起来、只给数据
# 不给带指令语气的话；任务那句放在用户消息最后
PREAMBLE = """你在帮用户整理一段录音。用户消息里有两块材料：<转写稿> 是 whisper 转写、已经校对过的稿子；\
<可能听错的地方> 是校对时没把握、没有改的位置，只是提醒你这些地方可能有识别错误。\
你的任务只有一个：按下面的要求写一份分析。不要核对或修改稿子，不要说你打算做什么，直接写。

"""

DEFAULT = """下面是一段录音的转写稿（whisper 转写，已经让 Claude 校对过识别错误）。\
「[时间] 名字：」开头的是对话稿，名字是按声纹或分轨推测的，可能有错。请用中文写一份分析：

1. 一段话说清楚这是一次什么样的谈话、谁在和谁说、大概说了什么。
2. 主要话题：按出现顺序列，每个话题写清要点，并标出大概的时间（用稿子里的时间戳）。
3. 值得记下来的原话：照抄原文，标时间和说话人，不要改写。
4. 提到了但没展开、值得之后追问或想一想的地方。
5. 如果有决定、计划、待办、约定，单独列出来；没有就写「没有」。

要求：只依据稿子，不要编造稿子里没有的内容；转写可能有错，碰到读不通或拿不准的地方直接说明，\
不要硬解释。"""


def unsure_list(prefix):
    """校对时没把握的那些，整理成一行一条的提醒。只给数据，不给「请你确认」这种话。"""
    entries = proofread.read_entries(prefix)
    state = proofread.load_state(prefix, entries) if entries else None
    rows = (state or {}).get("unsure") or []
    return ["- %s %s：「%s」可能是「%s」" % (proofread.stamp(r["t"]), r.get("who") or "", r["old"], r["new"])
            for r in rows]


def failed_lines(prefix):
    """校对没成功的行号范围，「1~120、361~480」这样的一句；没有就空串。分析要知道哪几段还是原稿。"""
    try:
        state = json.load(open(prefix + ".校对.json", encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return "、".join("%d~%d" % (a, b) for a, b in (state.get("failed") or []))


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def main():
    ap = argparse.ArgumentParser(description="用 Claude 分析转写稿")
    ap.add_argument("prefix")
    ap.add_argument("--cwd", default=os.path.expanduser("~/Recordings"),
                    help="会话存在哪个目录下（claude --resume 要在这个目录里跑）")
    a = ap.parse_args()
    txt = a.prefix + ".txt"
    if not os.path.exists(txt) or not open(txt, encoding="utf-8").read().strip():
        log("  没有可分析的稿子：%s" % txt)
        return 2
    prompt = DEFAULT
    if os.path.exists(CUSTOM):
        prompt = open(CUSTOM, encoding="utf-8").read().strip() or DEFAULT

    text = open(txt, encoding="utf-8").read()
    msg = "<转写稿 name=\"%s\">\n%s\n</转写稿>\n" % (os.path.basename(a.prefix), text.strip())
    hints = unsure_list(a.prefix)
    if hints:
        msg += "\n<可能听错的地方>\n%s\n</可能听错的地方>\n" % "\n".join(hints)
    unproofed = failed_lines(a.prefix)
    if unproofed:
        msg += "\n<没校对的部分>稿子第 %s 行校对没成功，那几段还是 whisper 原稿，识别错误可能更多。</没校对的部分>\n" % unproofed
    msg += "\n请按系统提示的要求，直接写这段录音的分析。"

    sid = str(uuid.uuid4())
    # 整条消息走命令行参数、不走标准输入：参数和标准输入谁先谁后由命令行决定，任务那句必须在最后
    args = ["--session-id", sid, "--tools", "", "--disable-slash-commands",
            "--system-prompt", PREAMBLE + prompt]
    if os.environ.get("REX_CLAUDE_MODEL"):
        args += ["--model", os.environ["REX_CLAUDE_MODEL"]]
    log("  Claude 分析中…（一次写完，长录音要几分钟）")
    os.makedirs(a.cwd, exist_ok=True)
    try:
        obj = claude_cli.run(args + [msg], "", TIMEOUT, cwd=a.cwd)
    except claude_cli.AccountError as e:
        log("  Claude 用不了：%s" % e.args[0])
        print("ACCOUNT %s" % e.args[0])
        return 3
    except (RuntimeError, OSError, ValueError) as e:   # 找不到 claude、参数太长（E2BIG）、输出解析不了
        log("  分析失败：%s" % e)
        return 4
    res = (obj.get("result") or "").strip()
    # 短得不像一份分析就不写报告：第一次真跑就回了一句「我先……然后……」，写进 .分析.md，rex go 下次
    # 认「有报告 = 分析过了」就再也不分析了
    if len(res) < min(400, len(text) // 4) or res.count("\n") < 3:
        log("  分析结果不像一份分析（%d 字）：%s" % (len(res), res[:80].replace("\n", " ")))
        log("  没写报告；再跑一次 rex go 会重新分析")
        return 4
    sid = obj.get("session_id") or sid

    used = claude_cli.usage_note()
    audio = next((a.prefix + e for e in (".m4a", ".wav", ".qta") if os.path.exists(a.prefix + e)),
                 a.prefix + ".txt")
    head = ["# 分析：%s" % os.path.basename(a.prefix), "",
            "- Claude 分析（%s），%s。稿子：`%s`" % (claude_cli.models(),
                                               datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                                               os.path.basename(txt))]
    if used:
        head.append("- 用量：%s（Max 订阅不按这个价收钱，只是衡量用了多少额度）" % used)
    if unproofed:
        head.append("- **注意**：第 %s 行校对没成功，那几段是 whisper 原稿；补校完（再跑一次 rex go）后这份分析不会自动重做，"
                    "要重做就删掉这个文件再 rex go" % unproofed)
    # 给 rex chat，不给能直接复制运行的 claude --resume：终端里的 claude 可能指向别家接口（见 claude_cli.py），
    # 带着那些设置 resume，整个会话（含全文稿子）就发到那边去了。会话号单独写，rex.sh / rex_app 按 UUID 认。
    # 路径写全：引号里的 ~ 不会展开
    head += ["- **接着聊**（稿子和这份分析都在那个会话里）：",
             "", "  ```bash", '  rex chat "%s"' % audio, "  ```", "",
             "  会话号 `%s`，存在 %s 下。别直接在终端里 `claude --resume`：那个 claude 可能指向别家接口，rex chat 会先清掉那些设置"
             % (sid, a.cwd.replace(os.path.expanduser("~"), "~")),
             "", "---", ""]
    proofread.atomic_write(a.prefix + ".分析.md", "\n".join(head) + res + "\n")
    log("  分析写好了 → %s.分析.md" % os.path.basename(a.prefix))
    if used:
        log("  用量：%s" % used)
    print("SESSION %s" % sid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
