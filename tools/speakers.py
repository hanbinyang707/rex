#!/usr/bin/env python3
"""把两轨各自的转写合成一份对话稿：谁、几点、说了什么。

    python3 tools/speakers.py --a 我.srt --b 对方.srt --names 我,对方 \\
        --audio-a 录音.m4a --map-a 0:1 --audio-b 录音.m4a --map-b 0:2 --out 输出前缀

由 rex.sh 的 transcribe_speakers() 调用，一般不用手敲。写出 <前缀>.txt（按发言轮次
排好的对话）和 <前缀>.srt（每条前面带名字）。

    python3 tools/speakers.py --rebuild 前缀

只拿 <前缀>.srt 把 .txt 重排一遍（rex trim 切掉末尾以后用）。

## 「谁在说话」靠的是分轨，不是猜

`rex both` 同时录两路**物理上分开**的信号：麦克风那一路是本机这边的人，BlackHole
那一路是电脑放出来的声音（通话对方、网课、视频）。谁在说话在录的那一刻就定了，
不需要模型去猜——两轨各转各的，按时间合起来，标签就是对的。

做不到的要说清楚：

  · 同一轨里的**多个人**分不开。线上会议对面三个人都在系统声音那一轨，一律标「对方」
  · 一个麦克风录的多人谈话（手机录音、线下开会）分不开
  · 混成一轨的老录音（2026-10 之前的 `rex both`）分不开

这三种交给 tools/diarize.py（`rex who`，声纹模型，是推测）。

## 外放时的回声

不戴耳机时，对方的声音从喇叭出来又被麦克风收进去：系统声音那一轨转一遍（对），
麦克风那一轨**又转一遍**，还被标成「我」。所以合并前要把麦克风那一轨里的回声挑出来。

判据两条一起看，单看哪条都会误杀：

  1. 文字：这一段和同一时刻对方说的话几乎一样
  2. 音量：这一段比你平时说话轻一大截——回声隔着空气衰减过

只看文字，两个人同时说「对对对」就会被当成回声；只看音量，你小声嘀咕一句也会被扔掉。
文字几乎一模一样（`ECHO_TEXT`）时才不看音量——外放开得大、麦克风又近，回声可以很响。

扔了几段会打印出来。**戴耳机时这个数应该是 0**，不是 0 就去看看是不是外放了。

## whisper 的段会跨过对方的话

这条是合成测试里撞出来的，不处理的话对话顺序是乱的。whisper 开着人声检测（VAD）时，
先把静音剪掉、把有人说话的片段**拼起来**再识别——而单看一轨，对方说话的那几秒正好是
静音，被剪掉了。于是 whisper 听到的是「我」连续不断地说，自然会把隔着对方一整句话的
两轮并成一段，段的起止就横跨了对方那句：

    我    12.97 → 21.78   我最近在选下学期的课，主要是纠结统计那门
    对方  16.53 → 19.80   哪一门统计？能具体说说吗？      ← 被包在里面

按起点一排，「主要是纠结统计那门」就跑到了对方提问之前。还有更坏的连锁：对方的段被拉成
33.6 → 44.5，盖住了「我」在 38.3 秒说的「对，是担心跟不上」——这句复述了对方的原话，
时间上又「重叠」，被当成回声扔掉了。**一句真话，没了，而且不报错。**

所以合并前先用各自那一轨的能量包络把段重新定位（`refine`）：

  1. 起止收紧到这一轨真的有声音的地方（whisper 的段起点经常提前到前面的停顿里）
  2. 段内有超过 `SPLIT_GAP` 的停顿、**而且这期间另一轨在说话**，就从这里切开，
     文字按两边的发声时长比例分，切点尽量落在标点上

判回声也随之改成先看时间：回声和原声是同时的（差几十毫秒），所以「我」这一段得有一半
以上和对方的话同时，才去比文字和音量。复述发生在对方说完之后，到不了比文字那一步。

切点是按时长比例估的，可能差一两个字——宁可一两个字放错一轮，也不要整段顺序错乱。

## 一轨是空的要说出来

2026-09-26 一场通话：开场戴上蓝牙耳机，通话声音改走耳机、绕过了 BlackHole，系统声音
那一轨从第 1 分钟起全是数字静音。合出来的稿子只有一个人在说话，看上去却很正常——
又是「降级时看起来像正常工作」。所以这里量每一轨数字静音（< −90 dB）占多少，
超过门槛就报警。真麦克风有本底噪声，不会出数字静音；麦克风那一轨出现大段 −91 dB，
就是读的那一头被掐断了：笔记本合着盖（合盖时内建麦克风在硬件上断开，2026-10-11
测试时撞上过），或者会议 App 把麦克风抢走了（rex-使用说明「开会」那节）。
"""

import argparse
import os
import re
import statistics
import subprocess
import sys
import tempfile

FRAME = 0.05          # 能量包络一帧多长（秒）
SPLIT_GAP = 1.0       # 段内停顿超过这么久、且这期间另一轨在说话，就是 whisper 把两轮并成了一段
PAD = 0.2             # 重新定位时往段外多看这么久，whisper 的段尾偶尔收得太早
SPEECH_SPAN = 20.0    # 一轨的「说话门限」= 说话时响的那部分往下这么多 dB。回声低于它
TOL_REFINED = 0.3     # 判「同时」的余量：定位过的段准，只留回声的延迟
TOL_RAW = 1.0         # 没能定位的段（读不到音量）只能放宽
ECHO_OVERLAP = 0.5    # 「我」这一段至少这么大比例和对方同时，才可能是回声
ECHO_TEXT = 0.6       # 文字重合到这个程度，就是同一句话，不再看音量
ECHO_TEXT_WEAK = 0.3  # 重合到这个程度，要再看音量才下结论
QUIET_DB = 10.0       # 比自己平时说话轻这么多，才算「隔着空气过来的」
DIGITAL = -90.0       # 低于这个算数字静音（BlackHole 没信号是 -91.0）
SILENT_MIC = 0.2      # 麦克风那一轨数字静音超过这个比例就报警（真麦克风根本出不了数字静音）
SILENT_SYS = 0.5      # 系统声音那一轨的门槛高得多：对方不出声时它本来就是 0
PARA_GAP = 8.0        # 同一个人停顿超过这么久就另起一段，方便按时间找
PARA_MAX = 400        # 一段攒到这么多字也另起，免得一屏一整段

PUNCT = re.compile(r"[\s,.!?;:，。！？、；：…—\-\"'“”‘’()（）\[\]【】《》<>~～·]+")
ENDS_PUNCT = re.compile(r"[，。！？、；：…,.!?;:]$")
NAME_OK = re.compile(r"^[^：:\n,，]{1,12}$")


def tsec(s):
    h, m, r = s.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + float(r.replace(",", "."))


def stamp(x):
    """SRT 用的 00:01:02,345"""
    ms = int(round(x * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def clock(x):
    """稿子里的 [01:02]，过了一小时是 [1:01:02]"""
    x = int(x)
    h, r = divmod(x, 3600)
    m, s = divmod(r, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


def read_srt(path):
    if not path or not os.path.exists(path):
        return []
    text = open(path, "rb").read().decode("utf-8", "replace")
    out = []
    for blk in re.split(r"\n\s*\n", text.strip()):
        lines = blk.strip().split("\n")
        i = next((k for k, l in enumerate(lines) if "-->" in l), None)
        if i is None:
            continue
        try:
            a, z = (tsec(x) for x in lines[i].split("-->"))
        except ValueError:
            continue
        body = " ".join(l.strip() for l in lines[i + 1:] if l.strip())
        if body:
            out.append({"a": a, "z": z, "text": body})
    return out


def envelope(audio, mapspec):
    """每 FRAME 秒一个 RMS（dB）。读不出来返回 None，调用方退回只看文字，并且说出来。"""
    tmp = tempfile.mkdtemp(prefix="rex-env-")
    path = os.path.join(tmp, "env.txt")
    # 路径要塞进滤镜参数里，那里的 : 和 , 是语法。临时目录理论上不会有，有就别冒险。
    if re.search(r"[:,'\\\[\]]", path):
        return None
    af = ("aresample=16000,aformat=channel_layouts=mono,asetnsamples=n=%d,"
          "astats=metadata=1:reset=1:measure_overall=RMS_level:measure_perchannel=none,"
          "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=%s"
          % (int(16000 * FRAME), path))
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                            "-i", audio, "-map", mapspec, "-af", af, "-f", "null", "-"],
                           capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(path):
            return None
        env = []
        for line in open(path):
            if line.startswith("lavfi.astats.Overall.RMS_level="):
                try:
                    v = float(line.split("=", 1)[1])
                except ValueError:
                    v = -200.0
                env.append(max(v, -200.0))    # -inf（整帧是 0）也落在 -200
        return env
    finally:
        if os.path.exists(path):
            os.remove(path)
        os.rmdir(tmp)


def level(env, a, z):
    """一段里响的那部分有多响（80 分位）。取分位数是不让句中停顿把它拉低。"""
    if not env:
        return None
    i = max(0, int(a / FRAME))
    j = max(i + 1, int(z / FRAME))
    xs = sorted(env[i:j])
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(len(xs) * 0.8))]


def silent_frac(env):
    if not env:
        return None
    return sum(1 for x in env if x < DIGITAL) / len(env)


def similarity(mine, theirs):
    """mine 里的字有多少也出现在 theirs 里。两字片段算，不看语序细节。"""
    a = PUNCT.sub("", mine).lower()
    b = PUNCT.sub("", theirs).lower()
    if not a or not b:
        return 0.0
    if len(a) <= 2:                        # 「对」「嗯嗯」这种，按字算
        return 1.0 if all(ch in b for ch in a) else 0.0
    ga = {a[i:i + 2] for i in range(len(a) - 1)}
    gb = {b[i:i + 2] for i in range(len(b) - 1)}
    return len(ga & gb) / len(ga)


def gate(env, segs):
    """这一轨的「说话门限」：段内响的那部分（90 分位）往下 SPEECH_SPAN dB，
    且至少高出本底 8 dB。外放时麦克风里的回声比麦克风前的人说话轻一大截，落在门限以下，
    所以重新定位时回声那几秒算「没人说话」，不会把切点糊掉。"""
    if not env:
        return None
    allv = sorted(env)
    floor = allv[int(len(allv) * 0.10)]
    inside = []
    for s in segs:
        inside.extend(env[max(0, int(s["a"] / FRAME)):int(s["z"] / FRAME) + 1])
    if not inside:
        return floor + 10
    inside.sort()
    return max(floor + 8, inside[int(len(inside) * 0.90)] - SPEECH_SPAN)


def active(env, a, z, thr, bridge=0.5):
    """[a, z] 里这一轨有声音的区间。短于 bridge 的停顿（字间、换气）不算断开。"""
    regs = []
    for i in range(max(0, int(a / FRAME)), min(len(env), int(z / FRAME) + 1)):
        if env[i] >= thr:
            t = i * FRAME
            if regs and t - regs[-1][1] <= bridge:
                regs[-1][1] = t + FRAME
            else:
                regs.append([t, t + FRAME])
    return regs


def busy(env, a, z, thr):
    """[a, z] 里有多大比例的帧这一轨在出声。"""
    xs = env[max(0, int(a / FRAME)):int(z / FRAME) + 1] if env else []
    return sum(1 for x in xs if x >= thr) / len(xs) if xs else 0.0


def split_text(text, weights):
    """按各块的发声时长比例切文字，切点在比例位置附近找标点，找不到就硬切。"""
    n, total = len(text), float(sum(weights))
    cuts, acc, prev = [], 0.0, 0
    for w in weights[:-1]:
        acc += w
        target = int(round(n * acc / total))
        best = None
        for d in range(0, max(3, int(n * 0.15)) + 1):
            for k in (target - d, target + d):
                if prev < k < n and text[k - 1] in "，。！？；、,.!?; ":
                    best = k
                    break
            if best:
                break
        cut = best if best else min(max(target, prev + 1), n - 1)
        cuts.append(cut)
        prev = cut
    pieces, prev = [], 0
    for c in cuts + [n]:
        pieces.append(text[prev:c].strip(" ，,"))
        prev = c
    return pieces


def refine(segs, env, thr, env_o, thr_o):
    """用这一轨自己的能量包络重新定位每一段：起止收紧到真有声音的地方；
    段内长停顿期间另一轨在说话，就从那里切开。返回 (新的段, 切了几处)。"""
    if not env or thr is None:
        return [dict(s, sure=False) for s in segs], 0
    out, splits = [], 0
    for s in segs:
        regs = active(env, s["a"] - PAD, s["z"] + PAD, thr)
        if not regs:                     # 门限以下：很轻的话、回声、或者幻觉，留原样交给后面判
            out.append(dict(s, sure=False))
            continue
        groups = [[regs[0]]]
        for r in regs[1:]:
            g0, g1 = groups[-1][-1][1], r[0]
            if g1 - g0 >= SPLIT_GAP and env_o and thr_o is not None and busy(env_o, g0, g1, thr_o) >= 0.3:
                groups.append([r])
            else:
                groups[-1].append(r)
        if len(groups) == 1:
            out.append(dict(s, a=regs[0][0], z=regs[-1][1], sure=True))
            continue
        pieces = split_text(s["text"], [sum(r[1] - r[0] for r in g) for g in groups])
        for g, p in zip(groups, pieces):
            if p:
                out.append(dict(s, a=g[0][0], z=g[-1][1], text=p, sure=True))
        splits += len(groups) - 1
    return out, splits


def overlap(s, others, tol):
    """s 有多大比例的时长和 others 里的某一段同时。"""
    dur = max(s["z"] - s["a"], FRAME)
    tot = 0.0
    for t in others:
        lo, hi = max(s["a"], t["a"] - tol), min(s["z"], t["z"] + tol)
        if hi > lo:
            tot += hi - lo
    return min(1.0, tot / dur)


def drop_echo(mine, theirs, env_mine):
    """把 mine 里的回声挑出来。返回 (留下的, 扔掉的, 有没有用上音量)。

    先看时间再看文字：回声和原声同时出现，所以「我」这一段得有一半以上和对方同时，
    才去比文字和音量。对方说完之后的复述（访谈里很常见）到不了比文字那一步。"""
    info = []
    for s in mine:
        tol = TOL_REFINED if s.get("sure") else TOL_RAW
        ov = overlap(s, theirs, tol)
        near = " ".join(t["text"] for t in theirs
                        if t["a"] < s["z"] + tol and t["z"] > s["a"] - tol)
        sm = similarity(s["text"], near) if near else 0.0
        info.append((ov, sm, level(env_mine, s["a"], s["z"])))
    # 「平时说话多响」只拿不和对方同时的段来算：外放时回声段很多，全算进去中位数会
    # 被拉低，真回声反而显得不轻了。
    clean = [lv for ov, sm, lv in info if lv is not None and ov < ECHO_OVERLAP]
    if not clean:
        clean = [lv for ov, sm, lv in info if lv is not None]
    typical = statistics.median(clean) if clean else None

    keep, dropped = [], []
    for s, (ov, sm, lv) in zip(mine, info):
        quiet = typical is not None and lv is not None and lv < typical - QUIET_DB
        short = len(PUNCT.sub("", s["text"])) <= 2
        if ov < ECHO_OVERLAP:
            echo = False
        elif short:
            echo = sm >= 1.0 and quiet           # 短的必须又同字又轻，不然「对」「嗯」全被吃掉
        else:
            echo = sm >= ECHO_TEXT or (sm >= ECHO_TEXT_WEAK and quiet)
        (dropped if echo else keep).append(s)
    return keep, dropped, typical is not None


def join(parts):
    """同一个人连着的几段接起来。whisper 的中文段尾通常不带标点，接缝补个逗号。"""
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not out:
            out = p
        elif ENDS_PUNCT.search(out):
            out += p
        elif re.search(r"[A-Za-z0-9]$", out) and re.match(r"[A-Za-z0-9]", p):
            out += " " + p
        else:
            out += "，" + p
    return out


def turns(segs):
    """按时间排好的段 → 发言轮次。同一个人连着说的并成一轮，停太久或太长另起。"""
    out = []
    for s in segs:
        last = out[-1] if out else None
        if (last and last["who"] == s["who"] and s["a"] - last["z"] < PARA_GAP
                and sum(len(p) for p in last["parts"]) < PARA_MAX):
            last["parts"].append(s["text"])
            last["z"] = max(last["z"], s["z"])
        else:
            out.append({"who": s["who"], "a": s["a"], "z": s["z"], "parts": [s["text"]]})
    return out


FULL = {",": "，", "?": "？", "!": "！", ";": "；", ":": "："}


def tidy(s):
    """whisper 的中文输出用半角标点（「老师好,能听见吗?」），接缝处补的是全角逗号，
    混在一起很难看。跟在汉字后面的半角标点换成全角；轮次末尾的逗号去掉。
    只动对话稿 .txt，.srt 保持 whisper 原样。"""
    s = re.sub(r"(?<=[一-鿿])[,?!;:]", lambda m: FULL[m.group(0)], s)
    return s.rstrip("，,、 ")


def write_txt(path, segs):
    lines = ["[%s] %s：%s" % (clock(t["a"]), t["who"], tidy(join(t["parts"])))
             for t in turns(segs)]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(lines) + ("\n" if lines else ""))


def write_srt(path, segs):
    with open(path, "w", encoding="utf-8") as fh:
        for i, s in enumerate(segs, 1):
            fh.write("%d\n%s --> %s\n%s：%s\n\n" % (i, stamp(s["a"]), stamp(s["z"]),
                                                  s["who"], s["text"]))


def rebuild(prefix):
    """只有带名字的 .srt 时（rex trim 切过）重排 .txt。"""
    segs = []
    for s in read_srt(prefix + ".srt"):
        who, sep, text = s["text"].partition("：")
        if not sep or not NAME_OK.match(who):
            return False                         # 不是对话稿，交回调用方按老办法处理
        segs.append({"a": s["a"], "z": s["z"], "who": who, "text": text})
    write_txt(prefix + ".txt", segs)
    return True


def main():
    ap = argparse.ArgumentParser(description="两轨转写合成对话稿")
    ap.add_argument("--a", help="麦克风那一轨的 .srt（本机这边的人）")
    ap.add_argument("--b", help="系统声音那一轨的 .srt（通话对方、电脑里放的）")
    ap.add_argument("--names", default="我,对方")
    ap.add_argument("--audio-a")
    ap.add_argument("--map-a", default="0:a:0")
    ap.add_argument("--audio-b")
    ap.add_argument("--map-b", default="0:a:0")
    ap.add_argument("--out")
    ap.add_argument("--rebuild", metavar="前缀")
    a = ap.parse_args()

    if a.rebuild:
        return 0 if rebuild(a.rebuild) else 2
    if not (a.a and a.b and a.out):
        ap.error("要给 --a --b --out")

    names = [x.strip() for x in a.names.replace("，", ",").split(",")]
    if len(names) != 2 or not all(NAME_OK.match(n) for n in names):
        print("  名字要两个、用逗号隔开、每个不超过 12 个字、不带冒号：%s" % a.names)
        return 1
    na, nb = names

    mine, theirs = read_srt(a.a), read_srt(a.b)
    env_a = envelope(a.audio_a, a.map_a) if a.audio_a else None
    env_b = envelope(a.audio_b, a.map_b) if a.audio_b else None

    # 两轨的数字静音占比。空轨合出来的稿子看上去照样正常，必须在这里喊出来。
    fa, fb = silent_frac(env_a), silent_frac(env_b)
    if fb is not None and fb >= SILENT_SYS:
        print("  ⚠ %s那一轨 %d%% 的时间是数字静音——要么对方一直没出声，要么系统声音中途断了"
              % (nb, round(fb * 100)))
        print("    断了最常见的原因：录到一半戴上蓝牙耳机，声音绕过了 BlackHole（rex stop 时看门狗会报「断了」）")
    if fa is not None and fa >= SILENT_MIC:
        print("  ⚠ %s那一轨 %d%% 的时间是数字静音——真麦克风不会这样" % (na, round(fa * 100)))
        print("    要么笔记本合着盖（合盖时内建麦克风在硬件上断开），")
        print("    要么会议 App 把麦克风抢走了：让会议 App 和 rex 用不同的麦克风（使用说明「开会」那节）")

    # 先各自重新定位（见文件头「whisper 的段会跨过对方的话」），再判回声
    ga, gb = gate(env_a, mine), gate(env_b, theirs)
    mine, sa = refine(mine, env_a, ga, env_b, gb)
    theirs, sb = refine(theirs, env_b, gb, env_a, ga)
    if sa + sb:
        print("  拆开 %d 处（whisper 把隔着另一个人的两句话并成了一段）" % (sa + sb))
    if env_a is None or env_b is None:
        print("  读不到某一轨的音量，没法按声音重新定位——顺序以 whisper 的时间为准，可能有错位")

    keep, dropped, used_level = drop_echo(mine, theirs, env_a)
    if dropped:
        print("  去掉 %d 段回声（%s的声音从喇叭漏进麦克风，又被当成「%s」转了一遍）"
              % (len(dropped), nb, na))
        if not used_level:
            print("    读不到音量，这次只按文字判的，可能误杀——留意稿子里是不是少了你自己说的话")

    segs = [dict(s, who=na) for s in keep] + [dict(s, who=nb) for s in theirs]
    segs.sort(key=lambda s: (s["a"], s["who"] != na))
    write_txt(a.out + ".txt", segs)
    write_srt(a.out + ".srt", segs)

    ca = sum(len(PUNCT.sub("", s["text"])) for s in keep)
    cb = sum(len(PUNCT.sub("", s["text"])) for s in theirs)
    if ca + cb:
        print("  %s %d 字（%d%%）· %s %d 字（%d%%）"
              % (na, ca, round(100 * ca / (ca + cb)), nb, cb, round(100 * cb / (ca + cb))))
    # 只有一边是空的才单独说；两边都空由 rex.sh 报一句「两轨都没转出字」
    if bool(mine) != bool(theirs):
        print("  ○ %s那一轨没转出字（VAD 没找到人声）" % (na if not mine else nb))
    print("CHARS %d" % (ca + cb))
    return 0


if __name__ == "__main__":
    sys.exit(main())
