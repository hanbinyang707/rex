#!/usr/bin/env python3
"""跑 whisper，并且**先搞清楚这段录音是哪几种语言**。

被 rex.sh 的 transcribe() 调用，一般不用手敲：

    python3 tools/whisper_run.py --model M.bin --audio 16k单声道.wav \
        --out /path/不带后缀 --lang auto --prompt-file tools/whisper-prompt.txt

## 为什么不能直接 whisper-cli -l auto

whisper 的自动语言识别**只在文件开头做一次**，之后整个文件按那一种语言解码。
2026-08-18 实测一条 5 分 39 秒的录音：前 60 秒英文、之后 279 秒（82%）中文，
它在 t=0 认定 en（p=0.99），后面 82% 的中文**一个字都没出来**。

更糟的是它不会报错。模型被逼着用英文去解中文，输出掉进重复陷阱：

    [00:01:20] It's better than the other bits format.
    [00:01:21] It's better than the other bits format.
    …（同一行连着 300 多次，一直到录音结束）

然后自动命名把文件叫成了 `2026-08-18_1324_phone_It's-better-format`。
**一个静默的失败，被下游包装成了一个看起来正常的结果。**

## 两个独立的毛病，两个独立的修法

**一、重复陷阱 → `-mc 0`。**whisper 默认把已经转出来的文本当上下文喂回去
（`--max-context -1`，无限）。一旦开始重复，重复本身进了上下文，于是更倾向重复，
正反馈。实测同一个文件：

    -mc 默认    最高频那一行重复 54 次
    -mc 0       降到 4 次

代价是跨句连贯性略降（它不再知道前文说过什么）。对口述稿这笔买卖划算——
连贯性丢一点可以接受，整段变成同一句话不行。

**二、语言锁死 → 分段探测，每段用自己的语言解码。**

## 探测的成本，以及为什么是这个网格

`whisper-cli -dl` 一次约 1.5 秒，**几乎全是加载 547 MB 模型的时间**，
不是识别本身。所以要控制的是「探测几次」，不是「每次多快」。

策略：先按粗网格铺 `MAX_PROBES` 个探测点（长文件网格自动拉大），只有相邻两点
**语言不一样**才去二分找边界，二分到 `MIN_GAP` 秒为止。单语文件就是纯粹的
`MAX_PROBES` 次开销；双语文件多花的只是几次二分。

网格既有上限（`MAX_PROBES` 个点）也有**下限密度**（至少 `MIN_STEP` 秒一个）。
只设上限不够：21 分钟的文件按 30 秒一格正好顶到 40 点，探测 60 秒 / 转写 160 秒
= 27%。加了下限之后实测开销：

    5 分钟    5~8 次探测    ≈ 20~30%
    21 分钟    21 次        ≈ 20%
    130 分钟   40 次        ≈ 6%

短文件的比例下不去——探测次数有个不能再少的底（要覆盖到开头和结尾），
而转写时间跟着时长缩。**这是实测值，不是估的**；早先文档里写的「4%」只对
两小时以上的文件成立，短文件上是错的。

## 探测结果要平滑

置信度低于 `MIN_P` 的点不算数，继承前一个已知的语言——安静段落、笑声、
"嗯"，这些地方 whisper 会给出随机的语言。短于 `MIN_RUN` 秒的段并进邻居，
否则一次误判就会把一整段切成三块，每块单独加载一次模型。
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile

MAX_PROBES = 40      # 粗网格上限。再多的话光探测就比转写还贵
SURVEY_WIN = 30      # 粗网格的探测窗口。宽一点稳，不容易落进一段停顿里
BISECT_WIN = 10      # 二分时改用窄窗口。宽窗口跨在语言边界上，两种语言各占一半，
                     # 定位精度就卡在 30 秒。实测同一处边界：30 秒窗口只能说
                     # 「在 30~60 秒之间」，10 秒窗口直接指到 40 秒，且置信度
                     # 反而更高（en 0.98 / zh 0.91）
MIN_GAP = 10         # 二分到这个精度就停
MIN_STEP = 60        # 粗网格最密就这么密。见 probe_map 里为什么要有下限

# 语言白名单。白名单外的探测结果一律当「不确定」，和低置信度同样处理（继承邻居）。
#
# 2026-09-22 真事：一条中英混说的录音被切成 13 段，其中 5 段判成 `is`（冰岛语），
# 合计 5.8 分钟。按冰岛语硬解，**这 5.8 分钟一个字都没出来**。起因是那条录音在
# 采集时丢了 14% 的样本（见 audiocap.swift），声音一卡一卡的，语言识别就开始乱猜——
# 而冰岛语这种训练数据少的语言，恰恰是 whisper 在「听不清」时最爱猜的。
#
# 采集那头已经修了，但音乐片头、笑声、底噪照样能骗过语言识别。作者的材料是中文和
# 英文，所以默认只认这两种；要加就 REX_LANGS=zh,en,ja。
ALLOWED = {x.strip() for x in os.environ.get("REX_LANGS", "zh,en").split(",") if x.strip()}
MIN_P = 0.60         # 置信度低于这个的探测点不算数
# 探测窗口里得**真有人在说话**，语言判定才算数。2026-09-26 一条录音（对方那一路没录上，
# 大段只有本机的底噪）实测：有声帧 0~2% 的窗口被判成 en，置信度 0.78~0.79，高过 MIN_P，
# 于是那几段按英文硬解，「ok ok ok ok 我理解你意思」被翻成了 "Okay… I understand your
# meaning"，「男生都有」被编成 "I'm going to put it on my face"。纯合成静音反而只给
# 0.38，挡得住——真实房间的底噪更像「有点什么」。分轨转写（speakers.py）让这件事更常见：
# 每一轨在对方说话时都是静音，只剩零星的「嗯」「对」。
#
# 「有声」= 这一帧高过 -50 dB，**并且**高出这个窗口自己的底噪（10 分位）6 dB。两条都要：
# 只用绝对值，吵的手机录音（底噪本身就 -49 dB）整段都算有声，拦不住什么；
# 相对值给大了又会误杀——第一版用 +15 dB，iPhone 录的一段连续说话 8 个探测点被判
# 「太安静」8 个，整条退回默认语言，中英混说的文件就又回到了原来那个 bug。
# 标定用了 12 个窗口（两条真实录音）：判错的 5 个静音窗口有声 0%~18%，
# 7 个说话窗口 21%~62%。门槛 20% 卡在中间，余量不大。
QUIET_FLOOR = -50.0  # 一帧（50ms）的 RMS 低于这个算没声音
QUIET_ABOVE = 6.0    # 并且得高出窗口自己的底噪这么多
MIN_VOICED = 0.20    # 有声帧不到这个比例的窗口不认语言
ORDER = [x.strip() for x in os.environ.get("REX_LANGS", "zh,en").split(",") if x.strip()]
MIN_RUN = 30         # 短于这么多秒的语言段并进邻居
MAX_BISECT = 24      # 二分的总次数上限，防止来回切换的录音把探测拖爆

NOISE = re.compile(r'^(ggml_|load_backend|read_audio_data|whisper_|main:|system_info|init:)')
SRT_TIME = re.compile(r'(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)')


def sh(cmd, quiet=True):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace")


def duration(path):
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", path])
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def slice_wav(src, start, length, dst):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "%.3f" % start]
    if length is not None:
        cmd += ["-t", "%.3f" % length]
    cmd += ["-i", src, "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", dst]
    return sh(cmd).returncode == 0


def voiced_frac(wav):
    """窗口里有声的帧占多少。量不出来返回 1.0——宁可退回老行为，也不因为量具坏了把探测全拦掉。"""
    r = sh(["ffmpeg", "-hide_banner", "-nostats", "-i", wav, "-af",
            "asetnsamples=n=800,astats=metadata=1:reset=1:measure_overall=RMS_level"
            ":measure_perchannel=none,ametadata=print:key=lavfi.astats.Overall.RMS_level",
            "-f", "null", "-"])
    vals = []
    for v in re.findall(r"RMS_level=(\S+)", r.stderr):
        try:
            vals.append(max(float(v), -120.0))
        except ValueError:
            vals.append(-120.0)
    if not vals:
        return 1.0
    floor = sorted(vals)[len(vals) // 10]
    thr = max(QUIET_FLOOR, floor + QUIET_ABOVE)
    return sum(1 for v in vals if v > thr) / float(len(vals))


QUIET = []       # 太安静、没去认语言的探测点，最后报出来


def detect(model, wav, dur, center, tmp, win=SURVEY_WIN):
    """探测 center 这个时刻是什么语言，窗口以它为中心。

    **按中心点记，不按窗口起点记**——这是踩出来的。一个从 31 秒开始的 30 秒窗口
    如果被判成中文，意思是「31~61 秒里中文占多数」，不是「31 秒处是中文」。
    照起点记的话，边界会被系统性地往前推半个窗口：实测真边界在 40 秒，
    按起点记报的是 30 秒，整整 10 秒的英文被划进中文段。
    """
    start = max(0.0, min(center - win / 2.0, max(0.0, dur - win)))
    c = os.path.join(tmp, "probe.wav")
    if not slice_wav(wav, start, win, c):
        return None, 0.0
    if voiced_frac(c) < MIN_VOICED:
        QUIET.append(center)
        return None, 0.0
    r = sh(["whisper-cli", "-m", model, "-f", c, "-dl"])
    m = re.search(r"auto-detected language: ([a-z]+) \(p = ([0-9.]+)\)",
                  r.stdout + r.stderr)
    if not m:
        return None, 0.0
    lang, p = m.group(1), float(m.group(2))
    if ALLOWED and lang not in ALLOWED:
        REJECTED[lang] = REJECTED.get(lang, 0) + 1
        return None, 0.0
    return lang, p


REJECTED = {}    # 被白名单挡掉的语言和次数，最后报出来——挡了什么要让人看得见


def probe_map(model, wav, dur, tmp, log):
    """铺粗网格 + 对分歧处二分。返回按时间排序的 [(中心秒, 语言)]。"""
    # 网格既有**上限**（MAX_PROBES 个点）也有**下限密度**（至少 MIN_STEP 秒一个）。
    # 只有上限是不够的：21 分钟的文件按 30 秒一个点正好顶到 40，探测花 60 秒、
    # 转写才 160 秒——27% 的开销，而不是给长文件算的那个 4%。粗网格只负责查出
    # 「这文件里有几种语言」，边界交给二分，所以稀一点不损失精度。
    step = max(MIN_STEP, dur / MAX_PROBES)
    n = max(2, min(MAX_PROBES, int(dur / step)))
    # 第一个点贴着开头、最后一个点贴着结尾。**这条不能省**：网格一稀，第一个点
    # 就可能骑在语言边界上，把开头那段的语言整个漏掉——而开头恰恰是最需要认对的
    # （whisper 原本的毛病就是只认开头）。
    half = SURVEY_WIN / 2.0
    lo, hi = min(half, dur / 2), max(dur - half, dur / 2)
    seen = {}
    for i in range(n):
        c = round(lo + (hi - lo) * (i / (n - 1.0) if n > 1 else 0), 1)
        lang, p = detect(model, wav, dur, c, tmp)
        seen[c] = lang if (lang and p >= MIN_P) else None

    budget = MAX_BISECT
    while budget > 0:
        ks = sorted(seen)
        gap = next(((a, b) for a, b in zip(ks, ks[1:])
                    if seen[a] and seen[b] and seen[a] != seen[b]
                    and (b - a) > MIN_GAP), None)
        if not gap:
            break
        mid = round((gap[0] + gap[1]) / 2, 1)
        if mid in seen:
            break
        lang, p = detect(model, wav, dur, mid, tmp, win=BISECT_WIN)
        seen[mid] = lang if (lang and p >= MIN_P) else None
        budget -= 1

    # 平滑：置信度不够的点继承前一个已知语言。安静段、笑声、「嗯」这些地方
    # whisper 给出的语言基本是随机的，让它们自己成段只会把文件切碎。
    ks = sorted(seen)
    log("  探测 %d 点（网格 %.0fs，二分 %d 次）" % (len(ks), step, MAX_BISECT - budget))
    if QUIET:
        log("  其中 %d 点太安静（有声不到 %d%%），不认语言，跟着邻居段走"
            % (len(QUIET), round(MIN_VOICED * 100)))
    if REJECTED:
        log("  白名单外的判定当作不确定处理：" + "、".join(
            "%s×%d" % (k, v) for k, v in sorted(REJECTED.items(), key=lambda kv: -kv[1]))
            + "（只认 %s，改 REX_LANGS 可以加）" % ",".join(sorted(ALLOWED)))
    known = [seen[k] for k in ks if seen[k]]
    if not known:
        return []
    cur = known[0]
    out = []
    for k in ks:
        if seen[k]:
            cur = seen[k]
        out.append((k, cur))
    return out


def to_runs(points, dur):
    """把探测点合成连续的语言段。

    相邻两点语言不同时，边界取**两点的中点**——二分已经把它们收敛到
    MIN_GAP 以内，所以中点就是当前精度下最好的估计。
    """
    if not points:
        return []
    cuts = []
    for (ta, la), (tb, lb) in zip(points, points[1:]):
        if la != lb:
            cuts.append(((ta + tb) / 2.0, lb))
    runs = [[0.0, dur, points[0][1]]]
    for t, lang in cuts:
        runs[-1][1] = t
        runs.append([t, dur, lang])

    merged = []
    for r in runs:
        if merged and (r[1] - r[0]) < MIN_RUN:
            merged[-1][1] = r[1]          # 太短，并进前一段
        elif merged and merged[-1][2] == r[2]:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(a, b, l) for a, b, l in merged if b - a > 0.5]


def run_whisper(model, wav, out, lang, prompt, vad, vpad, vmodel, echo, offset,
                hide_paths=False):
    cmd = ["whisper-cli", "-m", model, "-f", wav, "-l", lang,
           "-mc", "0",              # 上下文回灌是重复陷阱的燃料，见文件头
           "-otxt", "-osrt", "-of", out, "-np"]
    if prompt:
        cmd += ["--prompt", prompt]
    if vad and vmodel and os.path.exists(vmodel):
        cmd += ["--vad", "-vm", vmodel, "-vp", str(vpad)]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, errors="replace", bufsize=1)
    for line in p.stdout:
        line = line.rstrip("\n")
        if not line or NOISE.match(line):
            continue
        # 分段模式下 whisper 报的是**临时**分片路径，摆给人看只会误导
        # （「我的稿子怎么在 /var/folders 里？」）。合并后的真实路径最后统一报。
        if hide_paths and line.startswith(("output_txt:", "output_srt:")):
            continue
        echo(shift_line(line, offset))
    return p.wait()


def short(sec):
    """给人看的时刻：不到一小时 MM:SS，过了一小时 H:MM:SS。原来一律截成 MM:SS，
    65 分钟的录音分段显示成「59:30–00:56」，像是倒着走。"""
    t = hhmmss(sec)
    return t[3:8] if sec < 3600 else "%d:%s" % (int(sec) // 3600, t[3:8])


def hhmmss(sec):
    sec = max(0.0, sec)
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return "%02d:%02d:%02d.%03d" % (h, m, s, int(round((sec % 1) * 1000)))


PROGRESS = re.compile(
    r"\[(\d\d):(\d\d):(\d\d)\.(\d\d\d) --> (\d\d):(\d\d):(\d\d)\.(\d\d\d)\]")


def shift_line(line, offset):
    """whisper 打的进度行时间是**段内**的。不加偏移的话，转到第二段时屏幕上
    时间会跳回 00:00，看着像录音倒带了。"""
    if not offset:
        return line

    def rep(m):
        g = [int(x) for x in m.groups()]
        a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0 + offset
        b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0 + offset
        return "[%s --> %s]" % (hhmmss(a), hhmmss(b))

    return PROGRESS.sub(rep, line)


def srt_shift(text, offset, start_index):
    """把一段 SRT 的时间轴整体后移，并接着上一段的序号编号。"""
    out, idx = [], start_index
    blocks = re.split(r"\n\s*\n", text.strip())
    for b in blocks:
        lines = b.strip().split("\n")
        if len(lines) < 2:
            continue
        m = SRT_TIME.search(lines[1] if lines[0].strip().isdigit() else lines[0])
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0 + offset
        c = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0 + offset
        body = lines[2:] if lines[0].strip().isdigit() else lines[1:]
        out.append("%d\n%s --> %s\n%s" % (
            idx, hhmmss(a).replace(".", ","), hhmmss(c).replace(".", ","),
            "\n".join(body)))
        idx += 1
    return "\n\n".join(out), idx


def main():
    ap = argparse.ArgumentParser(description="按语言分段跑 whisper")
    ap.add_argument("--model", required=True)
    ap.add_argument("--audio", required=True, help="16 kHz 单声道 wav")
    ap.add_argument("--out", required=True, help="输出前缀，不带后缀")
    ap.add_argument("--lang", default="auto")
    ap.add_argument("--prompt-file", default="")
    ap.add_argument("--vad-model", default="")
    ap.add_argument("--vad-pad", default="200")
    ap.add_argument("--no-vad", action="store_true")
    a = ap.parse_args()

    def log(s):
        print(s, flush=True)

    prompt = ""
    if a.prompt_file and os.path.exists(a.prompt_file):
        with open(a.prompt_file, encoding="utf-8") as fh:
            prompt = " ".join(l.strip() for l in fh
                              if l.strip() and not l.startswith("#"))

    vad = not a.no_vad
    dur = duration(a.audio)

    with tempfile.TemporaryDirectory(prefix="rex-wr-") as tmp:
        if a.lang != "auto" or dur < SURVEY_WIN * 2:
            lang = a.lang if a.lang != "auto" else "auto"
            rc = run_whisper(a.model, a.audio, a.out, lang,
                             prompt if lang in ("zh", "auto") else "",
                             vad, a.vad_pad, a.vad_model, log, 0.0)
            return 0 if os.path.exists(a.out + ".txt") else (rc or 1)

        pts = probe_map(a.model, a.audio, dur, tmp, log)
        runs = to_runs(pts, dur) if pts else []
        langs = {l for _, _, l in runs}

        if len(runs) <= 1:
            only = (runs[0][2] if runs else "auto")
            if not runs and QUIET and ORDER:
                # 一个能用的探测点都没有，而且是因为太安静（对方几乎不出声的那一轨）。
                # 这时交给 whisper 自己认，它只听开头 30 秒——多半又是底噪，又判成 en。
                # 用 REX_LANGS 的第一个当默认语言，比让它对着底噪猜靠谱。
                only = ORDER[0]
                log("  探测点都太安静，认不出语言——按 REX_LANGS 的第一个（%s）转，"
                    "不对就 --lang 指定" % only)
            log("  语言：%s（整段一致）" % only)
            # 探到了就显式指定，别再让 whisper 自己猜一遍
            rc = run_whisper(a.model, a.audio, a.out, only,
                             prompt if only == "zh" else "",
                             vad, a.vad_pad, a.vad_model, log, 0.0)
            return 0 if os.path.exists(a.out + ".txt") else (rc or 1)

        log("  语言分段：" + " · ".join(
            "%s %s–%s" % (l, short(s), short(e)) for s, e, l in runs))
        log("  分 %d 段各按自己的语言转写（whisper 只在开头认一次语言，"
            "不分段的话后面全按第一种语言硬解）" % len(runs))

        txts, srts, idx = [], [], 1
        for i, (s, e, l) in enumerate(runs):
            part = os.path.join(tmp, "part%d.wav" % i)
            if not slice_wav(a.audio, s, e - s, part):
                log("  ⚠️ 第 %d 段切不出来（%s–%s），跳过" % (i + 1, hhmmss(s), hhmmss(e)))
                continue
            stem = os.path.join(tmp, "part%d" % i)
            log("\n  ── 第 %d/%d 段 · %s · %s–%s ──"
                % (i + 1, len(runs), l, short(s), short(e)))
            rc = run_whisper(a.model, part, stem, l,
                             prompt if l == "zh" else "",
                             vad, a.vad_pad, a.vad_model, log, s, hide_paths=True)
            if rc:
                # 原来不看退出码：whisper 中途挂了，半截输出照样并进去，稿子看着正常、只是短了
                log("  ⚠️ 第 %d 段 whisper 退出码 %d，这一段可能不完整" % (i + 1, rc))
            if os.path.exists(stem + ".txt"):
                t = open(stem + ".txt", "rb").read().decode("utf-8", "replace")
                if t.strip():
                    txts.append(t.strip())
            if os.path.exists(stem + ".srt"):
                raw = open(stem + ".srt", "rb").read().decode("utf-8", "replace")
                block, idx = srt_shift(raw, s, idx)
                if block.strip():
                    srts.append(block)

        if not txts:
            log("  ⚠️ 分段转写一段都没出内容")
            return 1
        with open(a.out + ".txt", "w", encoding="utf-8") as fh:
            fh.write("\n".join(txts) + "\n")
        with open(a.out + ".srt", "w", encoding="utf-8") as fh:
            fh.write("\n\n".join(srts) + "\n")
        log("\n  %d 段合并完成（时间轴已按各段起点校正）" % len(runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
