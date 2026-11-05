"""转写完查一遍：**有人声、稿子里却没字**的地方。whisper_run.py 转完调这里，一般不用手敲。

## 为什么要查

whisper 的解码器偶尔会走完一个 30 秒的窗口却不出字，稿子就少一段——退出码是 0，日志也正常。
2026-11-03 给词表做对照实测时撞上的：带词表（`--carry-initial-prompt`）转的 6.5 小时里有 3 处，
每处 15~30 秒，都在说话稀疏、含混的地方；同样的录音不带词表（`-mc 0`）转，那 3 处没漏。不是 no-speech
规则扔的，加 `-nth 1` 照样漏。漏法有两种，两种都要查：

    字幕之间空着     一段手机录的组会，09:01–09:33 一条字幕都没有。不带词表转，这里是
                     「做一次 然后把它切开来……好的好的好的」
    一条字幕很长、   一节课开头 03:24–03:53 助教在发通知，带词表转出来只剩一条
    却几乎没字       00:01–05:06、六个字的「同学们 开始上课」

第二种有重有轻，都是解码器跳过了窗口前面、只转了后面：那条字幕从窗口开头标到末尾，字却只有
末尾那一句。轻的：同一节课 1:42:21 一条 31 秒的字幕只有「我以后在讲科普上跟你们讲百度这个房子
做的有多差」，前面 25 秒的讲课（「所有人都在忙……它是人类的第二座八别塔……」）没了。不带词表也会：
那段组会 02:42 一条 21 秒的字幕只剩最后一句。还有编出来的：那节课的开头不带词表转，助教那段被一条
00:01–03:53 的「请不吝点赞 订阅 转发 打赏支持明镜与点点栏目」盖住了。

## 人声怎么量

用 Silero VAD，就是转写时挡静音幻觉的那个模型，同一个文件、同样的参数（只是不加边缘留白，
量的是真有声音的时长）。whisper_run.py 认语言时用的能量门槛（voiced_frac）不行：手机录音的
底噪本身就响，门槛在那上面不准。VAD 认的是「像不像人说话」，不看响不响。

单独跑 whisper-vad-speech-segments（whisper-cpp 自带）：两小时的录音约 10 秒（机器忙时 20 秒），只加载 0.9 MB 的
VAD 模型，不碰 547 MB 的大模型。分出来的段和 whisper-cli 自己开 VAD 时一样（同一段音频逐条对过）。
整个文件量一次，时间轴就是原文件的；分语言转的稿子（whisper_run.py 里 srt_shift 已经把每段
加回了起点）也是原文件的，两边直接比，不用再算偏移。

## 怎么判

- **实的字幕**盖住它那段时间。**薄的**——里面人声至少 THIN_VOICE 秒，字却不到每秒 THIN_RATE 个——
  不算数，它里面的人声照样算没转出来。字按「中日韩一个字一个，别的一个词算 1.5 个」数：念一个英文词
  差不多是念一个半汉字的工夫
- 没被盖住的人声按停顿串起来：停顿不到 JOIN 秒、中间也没有实字幕，算同一处。攒够 MIN_VOICE 秒才报

标定（人声都是不加留白的秒数；每秒几个字 = 字数 ÷ 字幕里的人声秒数）：

    漏了的            0.36、0.41（那节课两处只剩一句的）、1.07（1:42:21 那条）、
                      1.10（编出来的那条）、1.81（组会 02:42 那条）
    没漏的            最稀的 2.72（中英混着说的），纯中文最稀 2.95，一般 4 以上。门槛定在 2
    一处多少人声      组会漏的 8.4 秒；同一条不带词表转，没漏的地方最大一处 1.9 秒
    停顿              助教那段中间停了 12.7 秒（所以 JOIN 不能小于 13）

门槛高一点不怕：报之前先重转（见下），重转出来的话稿子里都有，就不算漏、不报。

课间、下课后没人说话的长空档不会报：没人声就什么都不算。那节课课间十分钟里人声一共 33 秒，
下课后五分钟里 3.5 秒。课间偶尔有人说几句，也得攒够 5 秒、而且稿子里真没有这几句才报——
那节课课间一段 14 秒的对话，带不带词表都漏了（带词表时被一条 7 分钟、八个字的字幕吞了），报出来补回去是对的。

## 补转

报出来的每一处，前后各多切 EDGE 秒（不越过前后的实字幕），**不带词表、`-mc 0`** 单独再转一遍
（模型、语言、VAD 都和正式转写一样）。转出来的字幕：

- 时间轴加回切的起点，落在切出来的这段以外的不要
- 按小句跟附近字幕（包括盖在这段上的薄字幕）比，已经有的小句去掉——不重复。「已经有」= 这个小句六成以上
  落在附近字幕里按顺序、至少两个单位连着对得上的地方（中日韩一个字、别的一个词算一个单位，先折成简体，
  见 hant.py）。要按小句比：重转常把几句并成一条，整条比的话新话把旧话冲淡，旧话就插了第二遍。
  全都已经有的，说明字其实在、只是时间轴标偏了，不算漏
- 按开始时间插进去，原来的字一个不改、先后不变，序号重排——不打乱时间轴。只有一处挪动：补进来的
  落在一条薄字幕里，就把那条的开头挪到它那几个字真正在的地方——重转出来跟它是同一句的那条在哪就在哪；
  没有的话挪到补进来的后面，因为薄字幕那几个字在它末尾（解码器跳过了前面）。见过的几条都是：
  「同学们 开始上课」05:05 才说（字幕从 00:01 起），「这会不会出问题啊?」1:04:16 才说（从 57:10 起）

补了什么、补在哪，逐条打出来。重转也没出字的照样报，只是说明「可能听不清，或者不是说话声」；重转出错
（切音频、whisper 退出码不是 0）会直说，不说成听不清。语言没定下来（auto）的只报不补：一小段让 whisper
自己认语言，含混的地方会认成白名单外的。
"""

import difflib
import os
import re
import shutil
import subprocess
import unicodedata
from bisect import bisect_left, bisect_right

import hant
import speakers
from i18n import L

MIN_VOICE = 5.0      # 一处攒够这么多秒人声才报
JOIN = 15.0          # 人声之间停顿不到这么久，算同一处。见文件头：一段话里停 12.7 秒是有的
THIN_VOICE = 5.0     # 一条字幕里至少有这么多秒人声，才看它薄不薄
THIN_RATE = 2.0      # 每秒人声不到这么多字，算薄。漏了的最多 1.81，没漏的最少 2.72，见文件头
WORD = 1.5           # 不是中日韩文字的，一个词算这么多个字
SLACK = 0.5          # 实字幕往前后各多盖这么一点。whisper 和 VAD 的时间轴对不齐：一句话 VAD 量到 5.60 秒，
                     # 字幕止在 5.586，剩下 14 毫秒跟 8 秒后没转的那句串成一处，报的起点早了 8 秒
EDGE = 0.5           # 补转时前后多切这么一点，免得把字切断
MAX_REDO = 20        # 补转最多这么多处，再多的只报不补
SAME = 0.6           # 补转的一个小句有这么大比例在附近字幕里连着对得上，就是已经有的

SRT_TIME = re.compile(r'(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)')


def speech(vmodel, wav):
    """Silero VAD 认出的人声段 [(起, 止)]，秒，按时间排好。

    量不出来（没装、模型不在、退出码不对、输出看不懂）返回 None——量具坏了要说出来，
    不能当成「没人说话」。"""
    exe = shutil.which("whisper-vad-speech-segments")
    if not exe or not vmodel or not os.path.exists(vmodel):
        return None
    r = subprocess.run([exe, "-vm", vmodel, "-f", wav, "-vp", "0", "-np"],
                       capture_output=True, text=True, errors="replace")
    m = re.search(r"Detected (\d+) speech segments", r.stdout)
    # 它报的是**厘秒**（帮助里写着），不是秒
    segs = [(float(a) / 100, float(b) / 100)
            for a, b in re.findall(r"start = ([0-9.]+), end = ([0-9.]+)", r.stdout)]
    if r.returncode or not m or int(m.group(1)) != len(segs):
        return None
    return sorted(segs)


def read_cues(text):
    """SRT → [(起, 止, 正文)]，正文原样（多行就是多行）。"""
    out = []
    for b in re.split(r"\n\s*\n", text.strip()):
        lines = b.strip().split("\n")
        i = next((k for k, l in enumerate(lines) if SRT_TIME.search(l)), None)
        if i is None:
            continue
        g = [int(x) for x in SRT_TIME.search(lines[i]).groups()]
        out.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0,
                    g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0,
                    "\n".join(lines[i + 1:])))
    return out


def write_cues(cues):
    return "\n\n".join("%d\n%s --> %s\n%s" % (i, speakers.stamp(a), speakers.stamp(z), t)
                       for i, (a, z, t) in enumerate(cues, 1)) + "\n"


def cjk(ch):
    return bool(ch) and ord(ch) >= 0x2E80 and unicodedata.category(ch).startswith("L")


def tokens(text):
    """比对用的单位：中日韩一个字一个，别的一个词一个（小写）；标点、空白不算。先折成简体（见 hant.py）。"""
    out = []
    for run in re.findall(r"[^\W_]+", hant.fold(text)):
        word = ""
        for ch in run:
            if cjk(ch):
                if word:
                    out.append(word.lower())
                    word = ""
                out.append(ch)
            else:
                word += ch
        if word:
            out.append(word.lower())
    return out


def units(text):
    """一段字有多少：中日韩的字一个算一个，别的按词算，一个词算 WORD 个。"""
    return sum(1 if cjk(t[0]) else WORD for t in tokens(text))


def clauses(text):
    """一条字幕切成小句：按标点，和挨着中日韩字的空白（whisper 拿空格隔开中文的短语）；英文词之间的空格不切。
    不到 3 个单位的并进前后的小句——太短的单拿出来比，到处都对得上。"""
    pieces, cur = [], ""
    for i, ch in enumerate(text):
        if ch in "，。！？、；：,.!?;:…" or (ch.isspace() and (cjk(text[i - 1:i]) or cjk(text[i + 1:i + 2]))):
            pieces.append(cur)
            cur = ""
        else:
            cur += ch
    out = []
    for p in pieces + [cur]:
        if not tokens(p):
            continue
        if out and len(tokens(out[-1])) < 3:
            out[-1] += " " + p.strip()
        else:
            out.append(p.strip())
    if len(out) > 1 and len(tokens(out[-1])) < 3:
        last = out.pop()
        out[-1] += " " + last
    return out


def covered(toks, ref):
    """toks 有多大比例在 ref 里对得上：按顺序、至少两个单位连着的才算，零星撞上的单字单词不算。
    不到 3 个单位的，得整串连着出现在 ref 里。

    早先用 speakers.similarity，它把空白也去掉，英文就成了按字母两两比，跟前后十几秒的字幕拼起来一比，
    哪句英文都能对上六七成：真漏了的一句英文，补转出来被当成「稿子里已经有了」。"""
    if len(toks) < 3:
        n = len(toks)
        return 1.0 if any(ref[i:i + n] == toks for i in range(len(ref) - n + 1)) else 0.0
    blocks = difflib.SequenceMatcher(None, toks, ref, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks if b.size >= 2) / float(len(toks))


def voiced(voice, starts, a, z):
    """[a, z] 里有多少秒人声。starts 是 voice 各段的起点，给二分用。"""
    i = max(0, bisect_right(starts, a) - 1)
    n = 0.0
    while i < len(voice) and voice[i][0] < z:
        n += max(0.0, min(voice[i][1], z) - max(voice[i][0], a))
        i += 1
    return n


def solid(voice, cues):
    """实的字幕盖住的时间，合并好、按时间排。薄的（见文件头）不算。"""
    starts = [s for s, _ in voice]
    spans = []
    for a, z, t in sorted(cues):
        v = voiced(voice, starts, a, z)
        if v >= THIN_VOICE and units(t) < THIN_RATE * v:
            continue
        if spans and a <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], z)
        else:
            spans.append([a, z])
    return [tuple(s) for s in spans]


def holes(voice, cues):
    """有人声却没字的地方 [(起, 止, 人声秒数)]：起止是那几段人声的头尾，不是空档的头尾。"""
    cover = []
    for a, z in solid(voice, cues):
        if cover and a - SLACK <= cover[-1][1]:
            cover[-1] = (cover[-1][0], z + SLACK)
        else:
            cover.append((a - SLACK, z + SLACK))
    heads = [a for a, _ in cover]
    left = []
    j = 0
    for s, e in voice:
        # 减掉实字幕盖住的部分。cover 不重叠、按时间排，扫一遍就行
        while j < len(cover) and cover[j][1] <= s:
            j += 1
        k = j
        while k < len(cover) and cover[k][0] < e:
            if cover[k][0] > s:
                left.append((s, cover[k][0]))
            s = max(s, cover[k][1])
            k += 1
        if e > s:
            left.append((s, e))
    out = []
    for s, e in left:
        # 中间夹着实字幕的不串：那是两处，各报各的
        if out and s - out[-1][1] <= JOIN and bisect_left(heads, s) == bisect_left(heads, out[-1][1]):
            out[-1] = (out[-1][0], e, out[-1][2] + e - s)
        else:
            out.append((s, e, e - s))
    return [h for h in out if h[2] >= MIN_VOICE]


def short(sec):
    """给人看的时刻，和 whisper_run.py 的一样：不到一小时 MM:SS，过了一小时 H:MM:SS。"""
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


def preview(text, n=16):
    t = " ".join(text.split())
    return t if len(t) <= 2 * n else t[:n] + "…" + t[-n:]


def redo_one(cues, cover, s, e, lang, redo):
    """把 [s, e] 这一处单独重转。返回 (要插的新字幕, 稿子里已经有的话 [(大约在哪, 话)])；重转失败返回 (None, [])。

    前后多切 EDGE 秒，但不越过前后的实字幕：越过去就是把人家已经转对的再转一遍。转出来的时间轴加回切的起点，
    落在切出来的这段以外的不要。每条按小句跟附近字幕（包括盖在这段上的薄字幕）比，已经有的小句去掉，剩下的
    照字数比例分它那段时间。不能整条比：重转常把几句并成一条，新话把旧话冲淡，旧话就插了第二遍。"""
    heads = [a for a, _ in cover]
    k = bisect_left(heads, s)
    lo = max(cover[k - 1][1] if k else 0.0, s - EDGE)
    hi = min(cover[k][0] if k < len(cover) else e + EDGE, e + EDGE)
    raw = redo(lo, hi, lang)
    if raw is None:
        return None, []
    ref = tokens(" ".join(t for a, z, t in cues if z > lo - 10 and a < hi + 10))
    new, seen = [], []
    for a, z, t in read_cues(raw):
        a, z = a + lo, z + lo
        if not lo <= (a + z) / 2 <= hi:
            continue
        a, z = max(a, lo), min(z, hi)
        parts = [(p, len(tokens(p)), covered(tokens(p), ref) >= SAME) for p in clauses(t)]
        total = float(sum(n for _, n, _ in parts))
        if not total:
            continue

        def at(i):          # 第 i 句大约从哪起
            return a + (z - a) * sum(n for _, n, _ in parts[:i]) / total
        kept = [i for i, (_, _, old) in enumerate(parts) if not old]
        gone = [i for i, (_, _, old) in enumerate(parts) if old]
        if kept:
            new.append((at(kept[0]), at(kept[-1] + 1), " ".join(parts[i][0] for i in kept) if gone else t))
        if gone:
            seen.append((at(gone[0]), " ".join(parts[i][0] for i in gone)))
    return new, seen


def check(audio, out, vmodel, runs, redo, log):
    """查 out.srt 里有人声却没字的地方，逐处报出来、补转、插回 out.srt 和 out.txt。

    runs 是 [(起, 止, 语言)]，补转时按这一处落在哪段定语言。redo(起, 止, 语言) 把那一段
    不带词表重转一遍，返回 SRT 文本（时间从切的起点算），重转失败返回 None。
    返回报了几处。"""
    voice = speech(vmodel, audio)
    if voice is None:
        log(L("  ⚠️ 这次没查漏转：VAD 量不出人声在哪（要 whisper-cpp 自带的 whisper-vad-speech-segments，"
              "brew upgrade whisper-cpp）",
              "  ⚠️ Skipped the gap check: VAD couldn't measure where the speech is (it needs "
              "whisper-vad-speech-segments, which comes with whisper-cpp: brew upgrade whisper-cpp)"))
        return 0
    try:
        with open(out + ".srt", "rb") as fh:
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return 0
    cues = read_cues(text)
    if len(cues) != text.count("-->"):
        # 读不懂的那几条要是悄悄跳过，它们那段就成了「没字」，会报成漏转
        log(L("  ⚠️ 这次没查漏转：.srt 里有 %d 条的时间轴读不懂", "  ⚠️ Skipped the gap check: %d entries in the .srt "
              "have timestamps it can't read") % (text.count("-->") - len(cues)))
        return 0
    found = holes(voice, cues)
    cover = solid(voice, cues)
    added, seen, n = [], [], 0
    for i, (s, e, v) in enumerate(found):
        head = L("  ⚠️ %s–%s 有声音但没转出字（人声约 %d 秒）",
                 "  ⚠️ %s–%s: there is voice, but nothing was transcribed (about %d s of speech)") % (
            short(s), short(e), round(v))
        lang = next((l for a, z, l in runs if a <= (s + e) / 2 < z), runs[-1][2] if runs else "auto")
        if i >= MAX_REDO or lang == "auto":
            log(head)
            n += 1
            if lang == "auto" and i < MAX_REDO:
                # 语言没定下来时让 whisper 对着一小段自己认，含混的地方会认成白名单外的语言（见 whisper_run.py 的 ALLOWED）
                log(L("     语言没定下来，不自动补转：一小段让 whisper 自己认语言，含混的地方会认错。要紧的话去听一下这一段",
                      "     The language wasn't settled, so it isn't re-transcribed automatically: on a short "
                      "stretch whisper guesses the language and gets murky passages wrong. If it matters, listen to it"))
            continue
        new, old = redo_one(cues, cover, s, e, lang, redo)
        if new is None:
            log(head)
            n += 1
            log(L("     单独重转这一段没成功（切音频或 whisper 出错），没补",
                  "     Re-transcribing this stretch failed (cutting the audio or whisper went wrong); nothing recovered"))
            continue
        seen += old
        if old and not new:
            # 字其实在，只是 whisper 把时间轴标偏了，或者这条字幕就是说得慢
            log(L("  （%s–%s 重转出来的话稿子里都有，不算漏）",
                  "  (%s–%s: everything re-transcribing it gives is already in the transcript; not a gap)")
                % (short(s), short(e)))
            continue
        log(head)
        n += 1
        if new:
            text = " ".join(t for _, _, t in new)
            # 字数和 rex 别处报的一样：不算空白的字符数
            log(L("     不带词表单独重转这一段，补回 %d 字：%s",
                  "     Re-transcribed this stretch on its own, without the vocabulary list; "
                  "recovered %d chars: %s") % (len("".join(text.split())), preview(text)))
            added += new
        else:
            log(L("     不带词表单独重转也没出字：可能听不清，或者不是说话声。要紧的话去听一下这一段",
                  "     Re-transcribing it on its own without the vocabulary list gave nothing either: "
                  "maybe unintelligible, or not speech. If it matters, listen to this stretch"))
    if len(found) > MAX_REDO:
        log(L("  只补转了前 %d 处，后面的只报不补", "  Only the first %d were re-transcribed; the rest are only reported")
            % MAX_REDO)
    if added:
        patch(out, cues, added, seen, log)
    if not found:
        log(L("  查过漏转：没有「有人声、却没出字」的地方",
              "  Gap check: no stretch with speech but no text"))
    return n


def patch(out, cues, added, seen, log):
    """把补转的字幕按开始时间插进去：原来的字一个不改、先后不变，序号重排；.txt 照新的 .srt 重写。

    seen 是重转出来、稿子里已经有的话和它们大约在哪，用来认薄字幕的字真正在哪。"""
    try:
        with open(out + ".txt", "rb") as fh:
            txt = fh.read().decode("utf-8", "replace")
    except OSError:
        txt = ""
    lines = [l.strip() for _, _, t in cues for l in t.split("\n") if l.strip()]
    if [l.strip() for l in txt.split("\n") if l.strip()] != lines:
        # .txt 和 .srt 对不上（被别的东西改过），不知道该插在哪一行，两边都不动
        log(L("  ⚠️ .txt 和 .srt 对不上，补转的没插进去（上面打出来的就是漏掉的）",
              "  ⚠️ The .txt and .srt don't match, so the recovered text was not inserted "
              "(what is printed above is what was missing)"))
        return
    merged = list(cues)
    # 补进来的落在一条薄字幕里：把它挪到它那几个字真正在的地方，不然它在稿子里排到补进来的那几句前面，
    # 先后反了（见文件头）。重转出来跟它是同一句的话在哪，它就从哪起；没有的话它那几个字在末尾
    for k, (a, z, t) in enumerate(merged):
        inside = [c for c in added if a <= c[0] < z]
        if not inside:
            continue
        mine = [p for p, x in seen if a <= p < z and covered(tokens(x), tokens(t)) >= SAME]
        start = min(mine) if mine else min(max(c[1] for c in inside), z - SLACK)
        end = min([z] + [c[0] for c in inside if c[0] >= start])
        if a < start < end:
            merged[k] = (start, end, t)
    for c in sorted(added):
        # 插在最后一条不晚于它开始的字幕后面。不重排原来的：它们的先后是 whisper 定的
        i = max((k + 1 for k, x in enumerate(merged) if x[0] <= c[0]), default=0)
        merged.insert(i, c)
    body = [l.strip() for _, _, t in merged for l in t.split("\n") if l.strip()]
    # 两个都先写好临时文件再换上去：写到一半出错，原来的两个都还在
    files = ((out + ".srt", write_cues(merged)), (out + ".txt", "\n".join(body) + "\n"))
    for path, data in files:
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            fh.write(data)
    for path, _ in files:
        os.replace(path + ".tmp", path)
    log(L("  补转的 %d 条已按时间插进 .txt 和 .srt" % len(added),
          "  %d recovered %s inserted into the .txt and .srt by time"
          % (len(added), "entry was" if len(added) == 1 else "entries were")))
