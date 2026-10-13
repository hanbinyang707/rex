#!/usr/bin/env python3
"""从转写稿里抽几个关键词，用来给文件起名。

    python3 tools/keywords.py 某个转写稿.txt
    python3 tools/keywords.py 稿.txt -n 4 --glossary tools/whisper-prompt.txt

打印一行，形如 `网文-中二-赤心巡天`。抽不出来就打印空行——
调用方看到空就保持原来的时间戳名字，不硬凑。

## 为什么不调模型

这个工具链从头到尾的承诺是「全程本地，不联网」。为了起个文件名把你的私人
录音稿发给某个 API，是拿承诺换便利，不划算。所以这里只用词频。

代价要说清楚：**它抽的是「反复提到的词」，不是「这段在讲什么」。**
一段一直在说某个词但重点在别处的稿子，它会起错名字。名字只是索引，
不是摘要——真要知道讲了什么，还是得打开看。

## 口语转写稿的特殊之处

这不是文章，是人说话。「就是」「然后」「这个」「我觉得」的密度远高于书面语，
不过滤的话抽出来的三个词永远是这些。所以 STOP 里塞了大量**口语填充词**，
这部分比通用停用词表重要得多。

## 中文没有词边界

没有分词器（不引第三方依赖），所以走 n-gram 词频：把 2~4 字的所有片段都数一遍，
再靠三条规则筛：

  1. 首尾不能是虚词——「的问题」「个东西」这种切歪的片段直接排掉
  2. 长的优先：「赤心巡天」和「赤心巡」次数接近时留长的
  3. 自己维护的词表（whisper-prompt.txt）里出现过的词，权重乘 5——
     那份表本来就是你的领域词汇，命中了几乎一定是关键词
"""

import argparse
import os
import re
import sys
from collections import Counter

from i18n import L

# 单字虚词。只用来判断 n-gram 的**首尾**，不用来判断中间——
# 「有意思」中间是「意」，按首尾判没问题；按整体判就把它误杀了。
EDGE = set(
    "的了是在我你他她它这那就都也而及与和或但不没很太更最又还再才只会要能可"
    "把被让给对从到向于以为之其此该等个些们地得着过上下里外中前后时把将由"
    "说讲做看想来去有无被跟同并且则当已经很挺蛮"
    "一二三四五六七八九十零两几多少半"
    "啊呀吧呢吗嘛哦噢诶嗯哈嘿唉哎么"
    # 繁体。whisper 的中文输出**时繁时简**，不是设置问题——2026-08-19 一条会议
    # 录音整篇出成繁体（繁体特征字 181 次 / 简体 55 次），而同一天别的稿子是简体。
    # 只有简体表的话，繁体稿里这些虚词一个都拦不住。
    "這那們來時後說話麼給對從於為個些裡將由講過還會要能讓並當"
)

# 整词级别的停用词。口语转写稿里这些的密度极高，不排掉抽出来的永远是它们。
STOP = set("""
这个 那个 就是 然后 所以 因为 但是 其实 可能 一个 我们 你们 他们 什么 怎么
这样 那样 现在 时候 东西 问题 觉得 知道 可以 应该 需要 已经 还是 或者 如果
的话 一下 有点 比较 非常 真的 确实 当然 反正 其他 这些 那些 自己 大家 那种
这种 一点 一样 一直 一定 一些 什么样 为什么 怎么样 这么 那么 而且 不过 只是
其中 之类 等等 之后 之前 后来 开始 结束 出来 起来 下来 上来 过来 过去 回来
这里 那里 哪里 里面 外面 上面 下面 前面 后面 中间 情况 方面 时间 地方 事情
意思 感觉 看到 听到 想到 说到 提到 讲到 用来 拿来 变成 成为 作为 关于 对于
通过 根据 按照 由于 除了 包括 比如 例如 也就是 也就 就会 就有 就要 就能 就说
我说 你说 他说 我想 我看 我是 我在 我有 我要 我会 我就 我也 我还 我都
部分 处理 直接 肯定 结果 估计 主要 基本 整个 完全 特别 明显 简单 复杂 重要
具体 相当 至少 起码 大概 也许 大约 稍微 到底 究竟 一部分 这部分 那部分 而已
方式 办法 东西 内容 状态 过程 位置 数量 程度 之类的 什么的 这块 那块
不是 不会 不能 不要 不用 不太 不到 没有 没什么 有些 有个 有的 有点儿
可是 那就 那你 那我 那他 这就 这你 这我 这他 好像 差不多 差不多是
""".split()) | set("""
這個 那個 就是 然後 所以 因為 但是 其實 可能 一個 我們 你們 他們 什麼 怎麼
這樣 那樣 現在 時候 東西 問題 覺得 知道 可以 應該 需要 已經 還是 或者 如果
的話 一下 有點 比較 非常 真的 確實 當然 反正 其他 這些 那些 自己 大家 那種
這種 一點 一樣 一直 一定 一些 為什麼 怎麼樣 這麼 那麼 而且 不過 只是
其中 之類 等等 之後 之前 後來 開始 結束 出來 起來 下來 上來 過來 過去 回來
這裡 那裡 哪裡 裡面 外面 上面 下面 前面 後面 中間 情況 方面 時間 地方 事情
意思 感覺 看到 聽到 想到 說到 提到 講到 用來 拿來 變成 成為 作為 關於 對於
通過 根據 按照 由於 除了 包括 比如 例如 就會 就有 就要 就能 就說
我說 你說 他說 我想 我看 我是 我在 我有 我要 我會 我就 我也 我還 我都
部分 處理 直接 肯定 結果 估計 主要 基本 整個 完全 特別 明顯 簡單 複雜 重要
具體 相當 至少 起碼 大概 也許 大約 稍微 到底 究竟 而已
方式 辦法 內容 狀態 過程 位置 數量 程度 這塊 那塊
不是 不會 不能 不要 不用 不太 不到 沒有 沒什麼 有些 有個 有的
可是 那就 那你 那我 那他 這就 這你 這我 這他 好像 差不多
""".split())

# 英文停用词。稿子里夹的英文多半是术语，值得抽，但这些不是。
STOP_EN = set("""
the a an and or but if then that this these those there here what when where
which who whom how why is are was were be been being do does did done have has
had having will would can could should may might must not no yes so very just
really actually basically like about with from into over under than for you
your they them their our its his her one two some any all more most other such
# 口语填充词。转写稿里密度极高，不排掉抽出来的第一名经常是 yeah / okay。
# 2026-08-18 实测一份中英混说的稿子抽出「format-yeah-run」，yeah 排第二。
# 只放**话语标记**，不放内容词——「better」「format」在讨论文件格式时是主题词，
# 排掉它们就把真正想找的东西也排掉了。
yeah yep yup yah okay ok uh um umm hmm mmm mhm huh oh ah eh
gonna wanna gotta kinda sorta dunno lemme
mean know think guess say says said see look well right sure maybe
anyway alright literally obviously definitely probably actually stuff thing things
lot lots bit little good great nice cool
""".split())

CJK = re.compile(r"[一-鿿]+")
EN = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")
# 时间轴和序号：允许直接喂 .srt 进来，不用调用方先清一遍
SRT = re.compile(r"^\s*(\d+|\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->.*)\s*$", re.M)
# 对话稿（speakers.py 写的）每一轮开头的「[01:02] 老师：」。名字每轮都出现一次，
# 不去掉的话「老师」会稳拿第一个关键词。
TURN = re.compile(r"^\[(?:\d+:)?\d{1,2}:\d{2}\] [^：\n]{1,12}：", re.M)


def load_glossary(path):
    """读 whisper-prompt.txt，取出里面的词。这份表是用户自己维护的领域词汇，
    命中即强信号。格式是自由文本，所以按标点全切开当候选词看待。"""
    if not path or not os.path.exists(path):
        return set()
    out = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # 引子那句（「以下是普通话内容……。常见词：」）不是词，只取「常见词：」后面
            if "常见词：" in line:
                line = line.split("常见词：", 1)[1]
            elif line.startswith("以下是"):
                continue
            for w in re.split(r"[、，,。；;：:（）()《》\s]+", line):
                w = w.strip("·—-")
                if len(w) >= 2:
                    out.add(w)
    return out


def cn_candidates(text, min_len=2, max_len=4):
    """所有 2~4 字片段的词频。首尾是虚词的直接不计——那是切歪的片段。"""
    c = Counter()
    for run in CJK.findall(text):
        for n in range(min_len, max_len + 1):
            for i in range(len(run) - n + 1):
                g = run[i:i + n]
                if g[0] in EDGE or g[-1] in EDGE:
                    continue
                if g in STOP:
                    continue
                # 叠字和重复片段：「稳稳稳稳」「网文网文」。口语里语气拖长、
                # 或者 whisper 在卡顿处重复输出，都会造出这种高频长片段，
                # 而长度加权正好把它顶到第一名——实测第一版抽出来的头号
                # 关键词就是「稳稳稳稳」。判据是不同字数不超过一半。
                if len(set(g)) <= len(g) // 2:
                    continue
                c[g] += 1
    return c


def en_candidates(text):
    """中文口语稿里夹的英文，绝大多数是术语或专有名词（docker、GUI、session），
    是整段话里最有区分度的东西。所以单独抽，并且在打分时给更高的权重。
    大小写保留出现最多的那种写法——「GUI」比「gui」像个名字。"""
    c, forms = Counter(), {}
    for w in EN.findall(text):
        k = w.lower()
        if k in STOP_EN:
            continue
        c[k] += 1
        forms.setdefault(k, Counter())[w] += 1
    return c, {k: v.most_common(1)[0][0] for k, v in forms.items()}


def dedup(scored):
    """去掉被更长的词包含、且次数差不多的短词。

    「赤心巡天」出现 8 次，「赤心巡」必然也出现 8 次——后者是切歪的。
    但「网文」出现 20 次而「看网文」只有 3 次时，两个是不同的词，都留。
    """
    items = sorted(scored.items(), key=lambda kv: (-len(kv[0]), -kv[1]))
    keep = []
    for w, s in items:
        covered = False
        for kw, ks in keep:
            if w in kw and s <= ks * 1.6:
                covered = True
                break
        if not covered:
            keep.append((w, s))
    return dict(keep)


def collapse_loops(text, keep=2):
    """同一句话最多留 keep 遍，多的丢掉。**按「这句话出现过几次」算，
    不是按「连着出现几次」算。**

    2026-08-18 真事：一条中英混说的录音，后半段中文被按英文硬解，whisper 卡进
    重复陷阱，输出「It's better than the bits format.」167 遍，于是抽出来的
    关键词就是那句话，文件被命名成 `2026-08-18_1324_phone_It's-better-format`
    ——**幻觉被下游包装成了一个看起来正常的文件名。**

    第一版只压「连续」重复，213 行压到 37 行，但那句话仍然剩 6 遍散在各处
    （中间偶尔插进「It's better than the bit format.」这种变体把连续性打断），
    `better` 18 次、`format` 15 次，照样排第一。所以判据换成按总次数封顶：
    卡住的解码器会把同一句刷几十上百遍，正常说话不会。

    真正的修在转写那一层（whisper_run.py 的 `-mc 0` 加分语言转写），这里是
    第二道：**不要让一句话重复几百遍这件事，决定整份稿子叫什么。**
    """
    seen, out = {}, []
    for ln in text.split("\n"):
        k = ln.strip()
        if not k:
            out.append(ln)
            continue
        seen[k] = seen.get(k, 0) + 1
        if seen[k] <= keep:
            out.append(ln)
    return "\n".join(out)


def extract(text, glossary=(), n=3, max_chars=6):
    if TURN.search(text):
        # 对话稿里同一个人连着的几段是用「，」接成一轮的。拆回一段一行，
        # collapse_loops 才能按段封顶——不拆的话一整轮是一行，卡住的解码器
        # 刷出来的几十遍同一句全在这一行里，封不住。
        text = TURN.sub("", text).replace("，", "\n")
    text = collapse_loops(SRT.sub("", text))
    total = len(CJK.sub("", text)) + sum(len(x) for x in CJK.findall(text))
    # 短稿子里出现两次就算重复；长稿子门槛抬高，否则随口说过一次的词也会中
    min_freq = 2 if total < 3000 else 3

    scored = {}
    for w, f in cn_candidates(text).items():
        if f < min_freq or len(w) > max_chars:
            continue
        # 长词的信息量高于短词，但不能碾压——1.3 次方是让「赤心巡天」压过
        # 同频的「网文」，又不至于让只出现两次的四字词压过出现二十次的两字词
        s = f * (len(w) - 1) ** 1.3
        if w in glossary:
            s *= 5
        scored[w] = s

    en, forms = en_candidates(text)
    gl = {g.lower() for g in glossary}
    for w, f in en.items():
        if f < min_freq:
            continue
        # 权重比中文双字词高：一段中文里出现的英文词几乎一定是主题词，
        # 而中文双字词有大量是没被停用词表拦住的通用词。
        s = f * 3.0
        if w in gl:
            s *= 5
        scored[forms.get(w, w)] = s

    if not scored:
        return []
    ranked = sorted(dedup(scored).items(), key=lambda kv: -kv[1])
    return [w for w, _ in ranked[:n]]


def main():
    ap = argparse.ArgumentParser(description=L("从转写稿抽关键词，用于文件命名",
                                               "Extract keywords from a transcript, for naming files"))
    ap.add_argument("path")
    ap.add_argument("-n", type=int, default=3, help=L("抽几个词，默认 3", "number of keywords, default 3"))
    ap.add_argument("--glossary", default="", help=L("whisper-prompt.txt 的路径", "path to whisper-prompt.txt"))
    ap.add_argument("--sep", default="-")
    ap.add_argument("--verbose", action="store_true",
                    help=L("连分数一起打印，调词表时用", "print with scores, for tuning the word lists"))
    a = ap.parse_args()

    if not os.path.exists(a.path):
        print("", end="\n")
        return 1
    with open(a.path, "rb") as fh:
        # 转写稿可能带 whisper 吐出来的坏字节，这里不该因此崩掉
        text = fh.read().decode("utf-8", "replace")

    words = extract(text, load_glossary(a.glossary), n=a.n)
    if a.verbose:
        g = load_glossary(a.glossary)
        for w in extract(text, g, n=20):
            print(w)
        return 0
    # 文件名里不能有分隔符和路径字符
    words = [re.sub(r"[/\\:\s]", "", w) for w in words]
    print(a.sep.join(w for w in words if w))
    return 0


if __name__ == "__main__":
    sys.exit(main())
