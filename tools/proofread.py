#!/usr/bin/env python3
"""用 Claude 校对 whisper 的转写稿：只改识别错误，改了哪里全部列出来。

    python3 tools/proofread.py 前缀

读 <前缀>.srt，改好写回 <前缀>.srt 和 <前缀>.txt；校对前的原稿留在 <前缀>.whisper.srt；
改了什么写进 <前缀>.校对.md。由 rex.sh 的 `rex go` 调用。

## 为什么不让 Claude 直接重写全文

让模型「输出校对后的全文」，它改了哪些字你根本看不出来——同音字修对了，顺手把一句口语
「润色」成书面语、把一个它觉得不通的词换掉，也全混在里面。所以这里反过来：Claude 只回报
**一张修改清单**（哪一行、原文哪几个字、改成什么、有没有把握、为什么），由脚本在原文里
**逐字找到**那几个字再替换。找不到的不改、改动大得不像纠错的不改，全部记进报告。

## 拿不准的不改，留给人

`sure=false` 的建议不进稿子，单独列在报告里「请你确认」。宁可留一个错字，也不要静默地
把一句话改成另一个意思——这和 whisper-fix.txt 那条「错一个字比静默改错一个字轻」是同一个判断。

## 隐私

这一步会把整份转写稿发给 Claude（走本机 `claude` 命令行的登录，和你在 Claude 里粘贴
一样）。转写、分人仍然全在本地；只有 `rex go` 才走这一步，`rex text` / `rex who` 不会。

## 长稿子

按 `CHUNK` 行一份分开校对（2.5 小时的稿子三千多行），每份带上前面几行当上下文，最多
`PARALLEL` 份同时跑。清单里的行号必须落在本份范围内，越界的不认。

## 输出

进度写 stderr（终端里实时看得到，launchd 下进日志）；stdout 只给 rex.sh 读的一行：
`CHANGES 改了 拿不准`，或者 Claude 整体用不了时 `ACCOUNT 原因`（退出码 3）。
怎么调 claude 命令行、为什么要清掉 ANTHROPIC_* 环境变量，见 claude_cli.py。
"""

import argparse
import concurrent.futures
import datetime
import difflib
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_cli  # noqa: E402
import speakers  # noqa: E402  read_srt / write_srt / rebuild / NAME_OK
from i18n import L  # noqa: E402

TOOLS = os.path.dirname(os.path.abspath(__file__))
# 用户自己的词表在 ~/.config/rex/（不进仓库），没有才用仓库里的模板。rex.sh 的 WPROMPT 是同一个规矩
USER_GLOSSARY = os.path.expanduser("~/.config/rex/whisper-prompt.txt")
GLOSSARY = USER_GLOSSARY if os.path.exists(USER_GLOSSARY) else os.path.join(TOOLS, "whisper-prompt.txt")
CHUNK = 120          # 每次交给 Claude 的行数
CONTEXT = 6          # 每份前面附带的上文行数（只看不改）
PARALLEL = 3         # 同时跑几份
TIMEOUT = 600        # 单份最长等多久（秒）
# 思考强度。2026-10-12 同样 20 行实测（Fable）：默认强度 81 秒、折合 $0.31；low 24 秒、$0.09，
# 挑出来的反而更准——「真本→真格」「背头→被投」有把握且对，Sonnet 把它们猜成了「真北」「版图」
EFFORT = os.environ.get("REX_PROOF_EFFORT", "low")

SCHEMA = {
    "type": "object",
    "properties": {
        "fixes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                    "sure": {"type": "boolean"},
                    "why": {"type": "string"},
                },
                "required": ["id", "old", "new", "sure", "why"],
            },
        }
    },
    "required": ["fixes"],
}

PROMPT = L("""你在校对一份语音转写稿。它是 whisper 自动转写的，标准输入里每行是「[编号] 说话人｜文字」\
（没有说话人时只有「[编号] 文字」）。说话人是另外推测的，不归你管，不要改。

只找**语音识别错误**：同音字、近音字、专有名词/术语/人名/书名/地名听错、英文词被写成音译或
错词、明显缺字多字导致读不通。下面这些**一律不改**：说法和用词习惯、口头禅、重复、语序、
语气词、标点（除非错到影响理解）。不要润色，不要把口语改成书面语。

每一处错误给出：
- id：那一行的编号（只能是「要校对的部分」里的编号）
- old：该行原文里的一小段，必须和原文**一字不差**，尽量短，但要短到在这一行里不会重复
- new：改成什么
- sure：结合上下文能确定是 true；只是觉得可能是 false
- why：一句话理由（比如「持续学习的术语」「上下文是在说签学校」）

没有错误就返回空列表。宁可少改，不要乱改。{extra}""",
           # 英文版规则和上面一条不差；多的只有最后那句：why 用英文写，old / new 照稿子原样、不要翻译
           """You are proofreading a speech transcript. It was transcribed automatically by whisper. Each line on \
standard input is "[number] speaker｜text" (just "[number] text" when there is no speaker). The speakers were \
guessed separately; they are not your job, so don't change them.

Look only for **speech-recognition errors**: homophones and near-homophones; misheard proper nouns, terms, \
personal names, book titles or place names; English words written as a phonetic transliteration or as the wrong \
word; obviously missing or extra characters or words that make a sentence unreadable. **Never change** any of \
these: how people phrase things and their choice of words, verbal tics, repetition, word order, filler words, \
punctuation (unless it is wrong enough to hurt understanding). Don't polish, and don't turn spoken language into \
written language.

For each error, give:
- id: the number of that line (only numbers from the "Lines to proofread" part)
- old: a short piece of that line's original text. It must match the original **exactly, character for \
character**. Keep it as short as possible, but long enough that it doesn't occur twice in that line
- new: what it should be
- sure: true if the context makes you certain; false if you only think it might be wrong
- why: a one-sentence reason, written in English (e.g. "a term from continual learning", "the context is about \
signing with a school")

Only why is in English: don't translate old or new.

If there are no errors, return an empty list. Better to change too little than to change something wrongly.{extra}""")


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def atomic_write(path, text):
    """先写同目录的临时文件再改名：写一半崩了（磁盘满、被杀）不会留下半截稿子或半截报告。"""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class locked:
    """同一条录音的稿子和状态，同一时刻只让一个人改。录音台里连点「采纳」、终端里 --retry 正在收尾、
    收件箱又处理了一遍同一条——不排队的话各自读-改-写，后写的把先写的冲掉（2026-10-13 复核时实测：
    两个请求同时点，19 对里每对丢一个决定）。锁文件放缓存目录，不混进录音文件夹。"""

    def __init__(self, prefix):
        d = os.path.expanduser("~/.cache/rex/locks")
        os.makedirs(d, exist_ok=True)
        self.path = os.path.join(d, hashlib.sha1(os.path.abspath(prefix).encode("utf-8")).hexdigest()[:16] + ".lock")

    def __enter__(self):
        self.fh = open(self.path, "a")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def glossary():
    if not os.path.exists(GLOSSARY):
        return []
    words = []
    for line in open(GLOSSARY, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 「以下是普通话内容……。常见词：」是给 whisper 的引子，不是词：只要「常见词：」后面那截
        if "常见词：" in line:
            line = line.split("常见词：", 1)[1]
        elif line.startswith("以下是"):
            continue
        words.extend(w.strip("。") for w in re.split(r"[，,、\s]+", line) if w.strip("。"))
    return words[:200]


def claude_json(prompt, text, schema):
    """要结构化结果。Claude 整体用不了抛 claude_cli.AccountError，别的失败抛 RuntimeError。

    校对规则走 --system-prompt（换掉 Claude Code 默认那套写代码用的系统提示），在不带 CLAUDE.md 的
    空目录里跑——为什么见 claude_cli.py 头部「在空目录里跑」。"""
    args = ["--json-schema", json.dumps(schema), "--tools", "", "--no-session-persistence",
            "--system-prompt", prompt, "--disable-slash-commands"]
    if EFFORT:
        args += ["--effort", EFFORT]
    if os.environ.get("REX_CLAUDE_MODEL"):
        args += ["--model", os.environ["REX_CLAUDE_MODEL"]]
    obj = claude_cli.run(args + [L("按系统提示校对下面这份稿子，返回修改清单。",
                                   "Proofread the transcript below as the system prompt says, and return the list "
                                   "of changes.")], text, TIMEOUT,
                         cwd=claude_cli.neutral_dir())
    out = obj.get("structured_output")
    if out is None:
        # 不同版本放的地方不一样：没有 structured_output 就从 result 文本里解析
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", (obj.get("result") or "").strip())
        try:
            out = json.loads(s)
        except ValueError:
            raise RuntimeError(L("回的不是修改清单：%s", "The reply isn't a list of changes: %s") % s[:200])
    return out


# 这份稿子是不是对话稿（大多数行都是「名字：话」）。不是的话句首的「他说：」就是正文，不是说话人——
# 否则「他说：我们明天去签学校」会被拆成说话人「他说」，这一截不送校对、报告里说话人那列也是错的
LABELED = True


def has_labels(entries):
    texts = [e["text"] for e in entries if e.get("text", "").strip()]
    if not texts:
        return False
    n = sum(1 for t in texts if t.partition("：")[1] and speakers.NAME_OK.match(t.partition("：")[0]))
    return n >= 0.6 * len(texts)


def split_label(text, labeled=None):
    """labeled 不给就用模块级的 LABELED（命令行里一次只处理一份稿子）；录音台是多线程、同时看好几份，
    必须自己算 has_labels 传进来，不能靠全局。"""
    if labeled is None:
        labeled = LABELED
    who, sep, rest = text.partition("：")
    if labeled and sep and speakers.NAME_OK.match(who):
        return who, rest
    return None, text


def chunks(entries):
    for i in range(0, len(entries), CHUNK):
        yield entries[max(0, i - CONTEXT):i], entries[i:i + CHUNK]


def render(ctx, body):
    def line(e):
        who, t = split_label(e["text"])
        return "[%d] %s｜%s" % (e["id"], who, t) if who else "[%d] %s" % (e["id"], t)
    parts = []
    if ctx:
        parts.append(L("【上文，只供参考，不要改】", "【Preceding lines, for reference only: don't change】"))
        parts.extend(line(e) for e in ctx)
    parts.append(L("【要校对的部分】", "【Lines to proofread】"))      # 名字和 PROMPT 里 id 那条说的对得上
    parts.extend(line(e) for e in body)
    return "\n".join(parts) + "\n"


def looks_like_rewrite(old, new):
    """纠错改的是一两个字。改动大到这种程度的，不管它说有多确定都不收：长度差太多、原文太长，
    或者改掉的字数超过一半（同样长的「期中考试→期末考察」光比长度是拦不住的）。"""
    if len(new) > 3 * len(old) + 6 or len(old) > 30:
        return True
    matched = sum(b.size for b in difflib.SequenceMatcher(None, old, new).get_matching_blocks())
    return max(len(old), len(new)) - matched > max(2, len(old) // 2)


def to_ranges(lines):
    """行号集合 → 合并后的 [[a, b], …]。"""
    out = []
    for i in sorted(set(lines)):
        if out and i == out[-1][1] + 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return out


def spans(ranges):
    """[[1, 120], [361, 480]] → 「1~120、361~480」（英文是「1-120, 361-480」），日志和报告里写行号范围都用它。"""
    return L("、", ", ").join(L("%d~%d", "%d-%d") % (a, b) for a, b in ranges)


def plural(n, word):
    """英文的单复数：1 line / 2 lines。只给英文那一半用。"""
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def valid_fixes(out):
    """Claude 回的东西是不是一张修改清单。不是（键名不对、少字段、类型不对）就回 None，这一份算失败、
    下次能补——不能当成「这一块没有错误」悄悄过掉。"""
    if not isinstance(out, dict) or not isinstance(out.get("fixes"), list):
        return None
    for f in out["fixes"]:
        if not isinstance(f, dict) or not isinstance(f.get("id"), int) or isinstance(f.get("id"), bool) \
                or not isinstance(f.get("old"), str) or not isinstance(f.get("new"), str) \
                or not isinstance(f.get("sure"), bool):
            return None
    return out["fixes"]


# ---------------------------------------------------------------- 校对的状态：.校对.json
#
# 报告（.校对.md）由这份状态生成，不再是唯一的记录。原因有两个：
# - 一份失败了要能补。原来失败的那几行只在报告里记个数，下次 rex go 看到「有报告 = 校对过了」就
#   跳过——2026-10-12 第一次真跑，开头 7 分半（第 1~120 行）就这么没校。现在 failed 记着行号范围，
#   `--retry` 只补这几段，结果并进原来的状态
# - 网页 App 要逐条「采纳 / 不采纳 / 撤销」。改稿子、挪条目、重写报告都走下面的 decide()，
#   判据和写法只有这一份
#
# 每一条：{rid, id, t, who, old, new, why, by}。id 是 srt 里的序号，t 是那一行的起点秒数（id 对不上时
# 按时间找回来）；by 是「claude」（它有把握、自动改的）或「你」（你在 App 里定的）。

def stamp(x):
    x = int(x)
    h, r = divmod(x, 3600)
    m, s = divmod(r, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


def unstamp(s):
    p = [int(x) for x in s.strip().split(":")]
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]


def new_state():
    return {"version": 1, "runs": [], "applied": [], "unsure": [], "rejected": [], "missed": [],
            "failed": [], "next_rid": 1}


def add_row(state, kind, row):
    row = dict(row, rid=state["next_rid"])
    state["next_rid"] += 1
    state[kind].append(row)
    return row


def find_entry(entries, row, needle):
    """这一条落在哪一行。先按 id，对不上（重新分过人、行被切开）再按时间附近、含着 needle 的找。"""
    i = row.get("id")
    if i and 1 <= i <= len(entries) and needle in entries[i - 1]["text"]:
        return entries[i - 1]
    for e in entries:
        if abs(e["a"] - row.get("t", -99)) < 1.5 and needle in e["text"]:
            return e
    return None


def locate(text, old):
    """old 在这一行正文里的位置。没有回 -1；出现不止一次回 -2——那就不知道该改哪一个，不改。"""
    i = text.find(old)
    if i < 0:
        return -1
    return -2 if text.find(old, i + len(old)) >= 0 else i


def replace_in(e, old, new, pos=None, labeled=None):
    """把这一行里的 old 换成 new。给了 pos 就先核对那个位置上确实是 old（撤销、再采纳都靠它，不然
    「起中→期中」撤销时会把本来就对的那个「期中」改坏）；没给就要求 old 在行里只出现一次。
    成了返回改动处相对正文的偏移，没成返回 None。"""
    who, text = split_label(e["text"], labeled)
    if pos is not None and 0 <= pos <= len(text) and text[pos:pos + len(old)] == old:
        i = pos
    else:
        i = locate(text, old)
        if i < 0:
            return None
    text = text[:i] + new + text[i + len(old):]
    e["text"] = "%s：%s" % (who, text) if who else text
    return i


def bootstrap(prefix, entries):
    """老版本只写了 .校对.md：从表格里把条目读回来。失败的行号范围那时没记，读不回来。"""
    path = prefix + ".校对.md"
    if not os.path.exists(path):
        return None
    state, kind = new_state(), None
    # 中文、英文的报告都认：报告用哪种语言写，看当时是哪种语言在跑，和现在不一定一样
    heads = (("## 改了的", "applied"), ("## 拿不准", "unsure"), ("## 没对上原文", "missed"),
             ("## 你没采纳的", "rejected"),
             ("## Changed", "applied"), ("## Uncertain", "unsure"), ("## Not found in the original", "missed"),
             ("## Rejected by you", "rejected"))
    for line in open(path, encoding="utf-8"):
        if line.startswith("## "):
            kind = next((k for h, k in heads if line.startswith(h)), None)
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not kind or len(cells) != 5 or not re.match(r"^\d+(:\d\d){1,2}$", cells[0]):
            continue
        t, who, old, new, why = cells
        row = {"id": None, "t": float(unstamp(t)), "who": who, "old": old, "new": new, "why": why,
               "by": "claude" if kind == "applied" else ""}
        hit = find_entry(entries, row, new if kind == "applied" else old)
        if hit:
            row["id"], row["t"] = hit["id"], hit["a"]
        add_row(state, kind, row)
    m = re.search(r"^- (?:校对：|Proofread: )(.*)$", open(path, encoding="utf-8").read(), re.M)
    state["runs"].append({"when": L("（老版本报告）", "(old report)"), "note": m.group(1) if m else ""})
    return state


def load_state(prefix, entries):
    path = prefix + ".校对.json"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return bootstrap(prefix, entries)


def write_transcript(prefix, entries):
    srt = prefix + ".srt"
    backup = prefix + ".whisper.srt"
    if not os.path.exists(backup) and os.path.exists(srt):     # 只留最早那份：再校一遍不能把原稿盖掉
        shutil.copy2(srt, backup)
    atomic_write(srt, "".join("%d\n%s --> %s\n%s\n\n" % (i, speakers.stamp(e["a"]), speakers.stamp(e["z"]), e["text"])
                              for i, e in enumerate(entries, 1)))
    if not speakers.rebuild(prefix):           # 不是对话稿就按 whisper 的老格式一行一句
        atomic_write(prefix + ".txt", "\n".join(e["text"] for e in entries) + "\n")


def render_md(name, state):
    total = {"calls": 0, "in": 0, "out": 0, "cost": 0.0}
    for r in state["runs"]:
        for k in total:
            total[k] += r.get("usage", {}).get(k, 0) or 0
    last = state["runs"][-1] if state["runs"] else {}
    fail_lines = sum(b - a + 1 for a, b in state["failed"])
    # 标题、摘要、表头跟着语言走；bootstrap() 两种语言的标题都认。rex.sh / rex_app 按「改了 **N** 处 · 拿不准、
    # 没改 **M** 处」那一行读数字，英文报告是「Changed: **N** · Uncertain, not changed: **M**」
    lines = [L("# 校对报告：%s", "# Proofreading report: %s") % name, ""]
    for r in state["runs"]:
        lines.append(L("- 校对：%s%s", "- Proofread: %s%s")
                     % (r.get("when", ""), L("，", ", ") + r["note"] if r.get("note") else ""))
    if total["calls"]:
        lines.append(L("- 用量：%d 次调用 · 送进去 %s token · 输出 %s · 折合 API 价约 $%.2f"
                       "（Max 订阅不按这个价收钱，只是衡量用了多少额度）"
                       % (total["calls"], claude_cli.wan(total["in"]), claude_cli.wan(total["out"]), total["cost"]),
                       "- Usage: %s (a Max subscription isn't charged this price; it only measures how much quota "
                       "was used)" % claude_cli.usage_text(total)))
    lines.append(L("- 改了 **%d** 处 · 拿不准、没改 **%d** 处 · 没对上原文 %d 处%s",
                   "- Changed: **%d** · Uncertain, not changed: **%d** · Not found in the original: %d%s")
                 % (len(state["applied"]), len(state["unsure"]), len(state["missed"]),
                    L(" · 你没采纳 %d 处", " · Rejected by you: %d") % len(state["rejected"]) if state["rejected"] else ""))
    if state["failed"]:
        lines.append(L("- **还有 %d 行没校成**（第 %s 行）：再跑一次 `rex go` 会只补这几段",
                       "- **Lines not proofread yet: %d** (%s): running `rex go` again redoes just those")
                     % (fail_lines, spans(state["failed"])))
    lines.append(L("- 校对前的原稿：`%s.whisper.srt`；稿子本体是 `.srt`，要自己改就改它（`.txt` 每次由它重新生成）",
                   "- Transcript before proofreading: `%s.whisper.srt`. The transcript itself is the `.srt`: to fix "
                   "something yourself, edit that (the `.txt` is regenerated from it every time)") % name
                 if state["applied"] else
                 L("- 这次没有改动稿子（之前改过的在 `.srt` 里，原稿在 `%s.whisper.srt`）",
                   "- No changes to the transcript this time (earlier changes are in the `.srt`; the original is "
                   "`%s.whisper.srt`)") % name)
    lines.append("")

    def table(rows, head, by=False):
        out = [L("| 时间 | 说话人 | 原文 | %s | 理由 |", "| Time | Speaker | Original | %s | Reason |") % head,
               "|---|---|---|---|---|"]
        for r in rows:
            why = r.get("why", "") + (L("（你采纳的）", " (accepted by you)") if by and r.get("by") == "你" else "")
            out.append("| %s | %s | %s | %s | %s |" % (stamp(r["t"]), r.get("who", ""),
                       r["old"].replace("|", "｜"), r["new"].replace("|", "｜"), why.replace("|", "｜")))
        return out
    if state["applied"]:
        lines += [L("## 改了的（%d）", "## Changed (%d)") % len(state["applied"]), ""] \
            + table(state["applied"], L("改成", "Changed to"), True) + [""]
    if state["unsure"]:
        lines += [L("## 拿不准、没改的（%d）——请你确认", "## Uncertain, not changed (%d): please confirm")
                  % len(state["unsure"]), "",
                  L("这些只是建议，稿子里还是原文。在录音台（rex app）里逐条点「采纳 / 不采纳」，或者自己改。",
                    "These are only suggestions; the transcript still has the original text. In the Recording Desk "
                    "(rex app), click Accept or Reject on each one, or edit the transcript yourself."), ""]
        lines += table(state["unsure"], L("建议", "Suggested")) + [""]
    if state["rejected"]:
        lines += [L("## 你没采纳的（%d）", "## Rejected by you (%d)") % len(state["rejected"]), ""] \
            + table(state["rejected"], L("建议", "Suggested")) + [""]
    if state["missed"]:
        lines += [L("## 没对上原文的（%d）", "## Not found in the original (%d)") % len(state["missed"]), "",
                  L("Claude 引的原文在那一行里找不到（多半是它自己抄错了），没改。",
                    "The text Claude quoted isn't in that line (most likely it copied it wrong), so nothing was "
                    "changed."), ""]
        lines += table(state["missed"], L("建议", "Suggested")) + [""]
    return "\n".join(lines)


def save_state(prefix, state):
    atomic_write(prefix + ".校对.json", json.dumps(state, ensure_ascii=False, indent=1))
    atomic_write(prefix + ".校对.md", render_md(os.path.basename(prefix), state))


def read_entries(prefix):
    return [dict(e, id=i + 1) for i, e in enumerate(speakers.read_srt(prefix + ".srt"))]


def decide(prefix, rid, action):
    """网页 App 的「采纳 / 不采纳 / 撤销」。改稿子、挪条目、重写报告。返回 (成没成, 说明)。"""
    with locked(prefix):
        return _decide(prefix, rid, action)


def _decide(prefix, rid, action):
    entries = read_entries(prefix)
    labeled = has_labels(entries)
    state = load_state(prefix, entries)
    if not state:
        return False, L("这条录音还没有校对报告", "This recording has no proofreading report yet")
    kind, row = next(((k, r) for k in ("unsure", "applied", "rejected") for r in state[k]
                      if r.get("rid") == rid), (None, None))
    if not row:
        return False, L("找不到这一条（报告可能刚被重写过，刷新一下）",
                        "Can't find this item (the report may have just been rewritten; refresh the page)")
    if action == "accept" and kind in ("unsure", "rejected"):
        e = find_entry(entries, row, row["old"])
        if not e:
            return False, L("稿子里找不到原文「%s」了，可能已经改过",
                            "“%s” is no longer in the transcript; it may have been changed already") % row["old"]
        if locate(split_label(e["text"], labeled)[1], row["old"]) == -2:
            return False, L("「%s」在这一行出现不止一次，不知道该改哪一个，请你直接改稿子",
                            "“%s” appears more than once in this line, so it's unclear which one to change; "
                            "please edit the transcript directly") % row["old"]
        pos = replace_in(e, row["old"], row["new"], labeled=labeled)
        if pos is None:
            return False, L("稿子里找不到原文「%s」了，可能已经改过",
                            "“%s” is no longer in the transcript; it may have been changed already") % row["old"]
        state[kind].remove(row)
        state["applied"].append(dict(row, id=e["id"], t=e["a"], by="你", pos=pos))
    elif action == "reject" and kind == "unsure":
        state["unsure"].remove(row)
        state["rejected"].append(dict(row, by="你"))
    elif action == "undo" and kind == "applied":
        if row["new"] == "" and row.get("pos") is None:
            return False, L("这一条是删字，老版本的报告没记位置，没法自动撤销，请你直接改稿子",
                            "This change deleted text, and old reports didn't record where, so it can't be undone "
                            "automatically; please edit the transcript directly")
        e = find_entry(entries, row, row["new"]) if row["new"] else (
            entries[row["id"] - 1] if row.get("id") and 1 <= row["id"] <= len(entries) else None)
        if not e:
            return False, L("稿子里找不到「%s」了，没法撤销",
                            "“%s” is no longer in the transcript, so it can't be undone") % row["new"]
        pos = replace_in(e, row["new"], row["old"], pos=row.get("pos"), labeled=labeled)
        if pos is None:
            return False, L("稿子里「%s」的位置对不上了（这一行后来又改过？），没法自动撤销，请你直接改稿子",
                            "“%s” is no longer where it was in the transcript (was the line edited since?), so it "
                            "can't be undone automatically; please edit the transcript directly") % row["new"]
        state["applied"].remove(row)
        state["rejected"].append(dict(row, id=e["id"], t=e["a"], by="你撤销"))
    else:
        return False, L("这一条现在不能这么操作", "That action isn't available for this item right now")
    write_transcript(prefix, entries)
    state["applied"].sort(key=lambda r: r["t"])
    state["rejected"].sort(key=lambda r: r["t"])
    save_state(prefix, state)
    return True, L("好了", "Done")


def parse_ranges(s, n):
    out = []
    for part in s.split(","):
        a, _, b = part.strip().partition("-")
        a, b = int(a), int(b or a)
        out.append([max(1, a), min(n, b)])
    return [r for r in out if r[0] <= r[1]]


def main():
    ap = argparse.ArgumentParser(description=L("用 Claude 校对转写稿", "Proofread a transcript with Claude"))
    ap.add_argument("prefix")
    ap.add_argument("--context", default="", help=L("一句话说明这是什么录音，帮 Claude 认词",
                                                    "One sentence on what the recording is, to help Claude get "
                                                    "words right"))
    ap.add_argument("--lines", default="", help=L("只校这几段行号，比如 1-120,361-480；结果并进原来的报告",
                                                  "Only proofread these line ranges, e.g. 1-120,361-480; the "
                                                  "results are merged into the existing report"))
    ap.add_argument("--retry", action="store_true", help=L("只补报告里记着没校成的那几段",
                                                           "Only redo the ranges the report lists as not "
                                                           "proofread"))
    a = ap.parse_args()
    global LABELED
    entries = read_entries(a.prefix)
    if not entries:
        log(L("  没有可校对的内容（%s.srt 是空的或不存在）", "  Nothing to proofread (%s.srt is empty or missing)")
            % a.prefix)
        return 2
    LABELED = has_labels(entries)

    ranges = None
    if a.lines or a.retry:
        state = load_state(a.prefix, entries) or new_state()
        ranges = parse_ranges(a.lines, len(entries)) if a.lines else [list(r) for r in state["failed"]]
        # 去重合并：failed 里要是记重了（老版本会），同一段会被校两遍、同一条改动应用两次
        ranges = to_ranges(i for lo, hi in ranges for i in range(lo, hi + 1))
        if not ranges:
            log(L("  报告里没有记着没校成的行，不用补", "  The report lists no lines that failed; nothing to redo")
                if a.retry else L("  --lines 给的范围不在稿子里", "  The --lines ranges aren't in the transcript"))
            print("CHANGES %d %d" % (len(state["applied"]), len(state["unsure"])))
            return 0

    g = glossary()
    extra = ""
    if g:
        extra += L("\n\n用户常用的词（听起来像的时候优先考虑它们）：",
                   "\n\nWords the user often uses (prefer them when something sounds like one): ") \
            + L("、", ", ").join(g)
    if a.context:
        extra += L("\n\n这段录音是：", "\n\nAbout this recording: ") + a.context
    prompt = PROMPT.format(extra=extra)

    if ranges is None:
        jobs = list(chunks(entries))
    else:
        jobs = []
        for lo, hi in ranges:
            for s0 in range(lo, hi + 1, CHUNK):
                body = entries[s0 - 1:min(hi, s0 + CHUNK - 1)]
                jobs.append((entries[max(0, s0 - 1 - CONTEXT):s0 - 1], body))
        log(L("  只补第 %s 行", "  Only redoing lines %s") % spans(ranges))
    n_lines = sum(len(b) for _, b in jobs)
    log(L("  Claude 校对：%d 行，分 %d 份，同时跑 %d 份" % (n_lines, len(jobs), min(PARALLEL, len(jobs))),
          "  Claude proofreading: %s in %s, %d at a time"
          % (plural(n_lines, "line"), plural(len(jobs), "chunk"), min(PARALLEL, len(jobs)))))
    # Ctrl-C / 被 kill：停掉还在跑的、不再发新的，**已经校完的几份照样记进报告**。原来 with 块退出时
    # 等排队的任务一份份起来跑完（稿子照样外发、额度照扣），最后什么都不写
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    results, failed, handled, done = [], [], set(), 0
    account = interrupted = None
    pool = concurrent.futures.ThreadPoolExecutor(PARALLEL)
    futs = {pool.submit(claude_json, prompt, render(c, b), SCHEMA): b for c, b in jobs}
    try:
        for fu in concurrent.futures.as_completed(futs):
            body = futs[fu]
            handled.add(fu)
            done += 1
            where = L("[%d/%d] 第 %d~%d 行", "[%d/%d] lines %d-%d") % (done, len(jobs), body[0]["id"], body[-1]["id"])
            try:
                out = fu.result()
            except claude_cli.AccountError as e:
                account = e.args[0]
                failed.append([body[0]["id"], body[-1]["id"]])
                log(L("  Claude 用不了，后面的不再试：%s", "  Claude is unavailable; not trying the rest: %s") % account)
                break
            except Exception as e:  # noqa: BLE001  一份失败不连坐其余，但要说出来
                failed.append([body[0]["id"], body[-1]["id"]])
                log(L("  %s 校对失败：%s", "  %s failed: %s") % (where, e))
                continue
            fixes = valid_fixes(out)
            if fixes is None:
                failed.append([body[0]["id"], body[-1]["id"]])
                log(L("  %s 回的不是修改清单的格式，这一份算失败：%s",
                      "  %s: the reply isn't in the change-list format, so this chunk counts as failed: %s")
                    % (where, str(out)[:120]))
                continue
            ok = {e["id"] for e in body}
            n = dropped = 0
            for f in fixes:
                if f["id"] in ok:
                    results.append(f)
                    n += 1
                else:
                    dropped += 1
            log(L("  %s：%d 条建议%s", "  %s: %d suggested%s")
                % (where, n, L("，%d 条行号越界不认", ", %d ignored (line number out of range)") % dropped
                   if dropped else ""))
    except KeyboardInterrupt:
        interrupted = True
        log(L("  收到中断：停掉还在跑的，不再发新的；已经校完的照样记进报告",
              "  Interrupted: stopping the chunks still running and not starting new ones; finished chunks still "
              "go into the report"))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        if account or interrupted:
            claude_cli.kill_all()
    for fu, body in futs.items():
        if fu not in handled:                   # 被取消、被杀的：算没校成，下次 --retry 补
            failed.append([body[0]["id"], body[-1]["id"]])
    failed = to_ranges(i for lo, hi in failed for i in range(lo, hi + 1))

    if len(results) == 0 and sum(hi - lo + 1 for lo, hi in failed) >= sum(len(b) for _, b in jobs):
        # 一份都没校成就不写报告：rex go 认「有报告 = 校对过了」，留一份「改了 0 处」的空报告，
        # 下次就不会再校了（第一次真跑 31 份全挂，就留下过这么一份）。补的时候也一样，原样不动
        log(L("  一份都没校成，稿子没动，报告也不动",
              "  No chunk was proofread; the transcript and the report are left as they were"))
        if account:
            print("ACCOUNT %s" % account)
            return 3
        return 130 if interrupted else 4

    with locked(a.prefix):
        # 校对跑了几分钟，这期间录音台里可能点过「采纳」：锁里重读稿子和状态，在最新的上面改
        entries = read_entries(a.prefix)
        byid = {e["id"]: e for e in entries}
        old_state = load_state(a.prefix, entries)
        if ranges is not None:
            state = old_state or new_state()
        else:
            # 整份重校：改动记录从头来，但你亲手「不采纳」的和历史记录留着
            state = new_state()
            if old_state:
                state["rejected"] = old_state.get("rejected", [])
                state["runs"] = old_state.get("runs", [])
                state["next_rid"] = old_state.get("next_rid", 1)
        nA, nU = apply_fixes(state, results, byid)
        if nA:
            write_transcript(a.prefix, entries)
        # 失败范围按行号集合算：旧的失败行里这次跑过的拿掉，这次失败的加进去（原来按区间整段保留、
        # 再追加，同一段会记两遍，下次校两遍、同一条改动应用两次）
        attempted = {e["id"] for _, b in jobs for e in b}
        old_failed = {i for lo, hi in state["failed"] for i in range(lo, hi + 1)}
        state["failed"] = to_ranges((old_failed - attempted) | {i for lo, hi in failed for i in range(lo, hi + 1)})
        for k in ("applied", "unsure", "missed"):
            state[k].sort(key=lambda r: r["t"])
        used = claude_cli.usage_numbers()
        state["runs"].append({"when": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                              "note": L("Claude（%s%s）%s%s", "Claude (%s%s)%s%s")
                              % (claude_cli.models(), L("，思考强度 %s", ", effort %s") % EFFORT if EFFORT else "",
                                 L("，只补了第 %s 行", ", only redid lines %s") % spans(ranges) if ranges else "",
                                 L("，中途被停下", ", stopped partway") if interrupted
                                 else (L("，Claude 中途用不了", ", Claude became unavailable partway") if account else "")),
                              "usage": used})
        save_state(a.prefix, state)

    name = os.path.basename(a.prefix)
    log(L("  改了 %d 处 · 拿不准没改 %d 处%s → %s.校对.md", "  Changed: %d · uncertain, not changed: %d%s → %s.校对.md")
        % (nA, nU, L(" · 第 %s 行没校成", " · lines %s not proofread") % spans(failed) if failed else "", name))
    note = claude_cli.usage_note()
    if note:
        log(L("  用量：%s", "  Usage: %s") % note)
    if account:
        print("ACCOUNT %s" % account)
        return 3
    print("CHANGES %d %d" % (len(state["applied"]), len(state["unsure"])))
    if interrupted:
        return 130
    return 0 if not failed else 4


def apply_fixes(state, results, byid, labeled=None):
    """把 Claude 的清单落到稿子上。同一行的几条先都在**原文**上定位，重叠的、原文出现不止一次的进
    「拿不准」，然后从右往左改（前面的位置不受影响），每条记下改完后的位置给撤销用。回 (改了几处, 拿不准几处)。"""
    nA = nU = 0
    by_line = {}
    for f in results:
        by_line.setdefault(f["id"], []).append(f)
    for lid in sorted(by_line):
        e = byid.get(lid)
        if not e:
            continue
        who, text0 = split_label(e["text"], labeled)
        cands = []
        for f in by_line[lid]:
            old, new = f["old"], f["new"]
            row = {"id": e["id"], "t": e["a"], "who": who or "", "old": old, "new": new, "why": f.get("why", ""),
                   "by": ""}
            if not old or old == new:
                continue
            i = locate(text0, old)
            if i == -1:
                add_row(state, "missed", row)
            elif i == -2:
                row["why"] = (row["why"] + L("；", "; ") if row["why"] else "") \
                    + L("这几个字在这一行出现不止一次，没自动改",
                        "this text appears more than once in the line, so it wasn't changed automatically")
                add_row(state, "unsure", row)
                nU += 1
            elif not f.get("sure") or looks_like_rewrite(old, new):
                if f.get("sure"):      # 它说有把握、是被拦下的：写明为什么没收，不然看着像它自己犹豫
                    row["why"] = (row["why"] + L("；", "; ") if row["why"] else "") \
                        + L("改动太大，不像纠错，没收", "too big a change to be a correction, so it wasn't applied")
                add_row(state, "unsure", row)
                nU += 1
            else:
                cands.append((i, old, new, row))
        cands.sort(key=lambda c: (c[0], c[1], c[2]))
        chosen, seen, last_end = [], set(), -1
        for i, old, new, row in cands:
            if (i, old, new) in seen:           # 同一条给了两遍（范围重叠时会）
                continue
            seen.add((i, old, new))
            if i < last_end:
                row["why"] = (row["why"] + L("；", "; ") if row["why"] else "") \
                    + L("和同一行另一条改动重叠，没改", "overlaps another change in the same line, so it wasn't applied")
                add_row(state, "unsure", row)
                nU += 1
                continue
            chosen.append((i, old, new, row))
            last_end = i + len(old)
        if not chosen:
            continue
        text = text0
        for i, old, new, row in reversed(chosen):
            text = text[:i] + new + text[i + len(old):]
        shift = 0
        for i, old, new, row in chosen:
            add_row(state, "applied", dict(row, by="claude", pos=i + shift))
            nA += 1
            shift += len(new) - len(old)
        e["text"] = "%s：%s" % (who, text) if who else text
    return nA, nU


if __name__ == "__main__":
    sys.exit(main())
