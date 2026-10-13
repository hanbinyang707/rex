#!/usr/bin/env python3
"""按声纹分人：一个麦克风录的多人谈话，或者混成一轨的老 `rex both`。

    python3 tools/diarize.py --wav 16k单声道.wav --srt 转写.srt --out 输出前缀 \\
        [--speakers N] [--call 原始录音.m4a]

由 rex.sh 的 `rex who` / `rex text --who` 调用。写出 <前缀>.txt（对话稿）和 <前缀>.srt。
`--call` 给的是 2026-10-11 之前录的、混成一轨的 `rex both`：分完人再按频谱把
「本机这边」对成「我」、「通话那头」对成「对方」。

新的 `rex both` 用不着这个——它录的时候就分轨了，见 speakers.py，那条路标签是确定的。
这里是**推测**，说明里、稿子里都这么说。

## 用到的东西

sherpa-onnx（k2-fsa，Apache-2.0）：命令行程序做第一步切分，C 接口（libsherpa-onnx-c-api，
标准库 ctypes 直接调，不装任何 Python 包）算声纹。模型两个：pyannote segmentation-3.0
（MIT）、3D-Speaker CAM++ 中英文版（Apache-2.0）。全在 ~/.cache/sherpa-onnx，第一次用时
rex.sh 去下。**没用 Rev 的 reverb-diarization**：「非生产用途许可」，用了就算同意。

## 两步：先细分，再按「平均声纹」合并

第一版只用 sherpa 自己的聚类，按单段之间的距离和一个阈值数人数。**这个办法在长录音上
彻底失效**：2026-10-11 一段两个人聊了 2 小时 30 分钟的录音被分成了 12 个人。把阈值放宽
也救不回来：

| sherpa 阈值 | 0.8 | 0.9 |
|---|---|---|
| ≥30 秒的簇 | 18 个 | 15 个 |

两个半小时里同一个人的嗓音会变（累了、激动、离手机忽远忽近），单段和单段比，同一个人
前后两段可以比两个不同的人还远——所以任何一个单段阈值都会把他切碎。

现在的办法：

  1. sherpa 先**故意分细**（阈值 `INIT_TH`），宁可把一个人切成几十堆，也不让两个人进同一堆
  2. 每一堆取若干段，用 C 接口算声纹，求**平均声纹**——几十段平均下来，嗓音的一时变化抵消了
  3. 两堆的平均声纹相似度 ≥ `MERGE_SIM` 就并成一堆，从最像的一对开始，并到最像的一对也
     不够像为止
  4. 太小的碎堆（不到总时长 3% 且不到 30 秒）不算一个人，并给**声纹最像**的那个人
  5. 给了人数就一直并到恰好剩那么多人

平均声纹之间的相似度，同一个人和不同的人分得非常开：

| | 平均声纹相似度 |
|---|---|
| 10-10 两人谈话，同一个人被拆成的两堆 | 0.98 |
| 2.5 小时那条，同一个人的各堆之间 | 0.81~0.93 |
| 10-10 两人之间 | 0.15 |
| 2.5 小时那条，两个人之间 | 0.48~0.70 |
| 两个 macOS 合成语音（一男一女） | 0.62 |

合并门槛在 0.65~0.80 之间改，四条录音的结果都不变（都是 2 个人），取 0.7。

**第一步的阈值要细到 0.5**：0.6 时 sherpa 已经把两个合成语音并进了同一堆，后面怎么合并
都拆不开。代价是长录音的堆很多（2.5 小时那条 243 堆），所以一秒半以内的零碎堆不单独
算声纹、每堆最多取 `MAXSEG` 段。

## 标定

| 录音 | 第一版（单段阈值 0.8） | 现在 |
|---|---|---|
| 10-10 两人谈话（2 人，有频谱参照） | 3 人（一个人被拆开） | **2 人**，逐句和频谱参照一致 97% |
| 10-11 04:32 手机录音 | 4 人 | **2 人** |
| 10-11 2.5 小时聊天（确认是 2 人） | 12~18 人 | **2 人** |
| 两个合成语音的电话 | 1 人 | **2 人** |

04:32 那条，第一版分出 4 个人时我照内容说「至少 3 人」——说「那我们下周一再碰一下」和说
「你继续」的那位，平均声纹相似度 0.81，是同一个人。**凭内容猜人数也不可靠。**

逐句 97% 的说法来自 10-10：那场两边频谱不同（通话那头 7.5 kHz 以上被砍掉），能当参照。
逐帧比只有 85%，不一致的段挑出来读是对方在讲，频谱规则把夹在里面的轻音判错了——参照
自己的噪声。换 ERes2NetV2（68 MB）没更好还慢三倍，所以用 CAM++。

## 速度

分段窗口步长 0.1 → 0.5、4 线程：46 分钟的录音 sherpa 那一步从 6 分钟降到 30 多秒，逐句
一致率不变。整个分人实测：15 分钟约 40 秒、46 分钟约 1.5 分钟、2.5 小时约 5 分钟（转写它
要二十分钟，这一步不是瓶颈）。逐帧查「这一刻谁在说」要先建时间线表（`timeline`）——之前逐帧
扫所有段，2.5 小时那条是 7.5 分钟。

## 碎片、短句、再跑一遍

- **别按比例硬切短句。**步长 0.5 时换人的时刻只准到几秒，第一版把「我现在看了一些大学的
  网页」切成「我现在看 / 了一些大学的网页」分给两个人。只切 ≥ 5 秒、两边各 ≥ 1.5 秒的句子
- **再跑一遍要认出旧标签**（`unlabel`），不然变成「说话人2：说话人1：……」
- 只听出一个人（讲座、播客）就不改稿子，退出码 5
- C 接口加载失败就退回只用 sherpa 自己的聚类，并且说出来（人数会偏多）
"""

import argparse
import collections
import ctypes
import glob
import math
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import speakers  # noqa: E402  turns / write_txt / write_srt / split_text 共用一套

CACHE = os.environ.get("REX_DIAR_DIR") or os.path.expanduser("~/.cache/sherpa-onnx")
INIT_TH = 0.5         # 第一步故意分细。0.6 时两个相似的声音已经会进同一堆
MERGE_SIM = 0.7       # 两堆平均声纹相似度到这个就并。0.65~0.80 结果都一样
FALLBACK_TH = 0.8     # C 接口用不了时退回的单段阈值（第一版的做法，长录音人数偏多）
FRAGMENT_SEC = 30.0   # 碎堆：不到这么久（短录音按总时长的 10%）……
FRAGMENT_FRAC = 0.03  # ……而且不到总时长的这个比例
MAXSEG = 12           # 每堆最多取几段算平均声纹
MIN_EMB = 1.0         # 短于这个的段不算声纹，太短不准
TINY = 1.5            # 总时长不到这个的堆不单独算声纹，直接当碎片
SHIFT = 0.5           # 分段窗口步长（相对 10 秒窗口）。默认 0.1 慢 5 倍，准确率一样
THREADS = 4
SPLIT_MIN = 1.5       # 一句字幕里两个人各连续说了这么久以上，才在这句里切开
SPLIT_LEN = 5.0       # 而且这句本身得有这么长（见文件头「别按比例硬切短句」）
FRAME = 0.05


def tools():
    """sherpa-onnx 的程序、两个模型、C 接口所在目录。找不到返回 None（rex.sh 负责下载）。"""
    bins = sorted(glob.glob(os.path.join(CACHE, "sherpa-onnx-v*-osx-*", "bin",
                                         "sherpa-onnx-offline-speaker-diarization")))
    seg = os.path.join(CACHE, "sherpa-onnx-pyannote-segmentation-3-0", "model.onnx")
    emb = os.path.join(CACHE, "campplus_zh_en.onnx")
    if not bins or not os.path.exists(seg) or not os.path.exists(emb):
        return None
    lib = os.path.join(os.path.dirname(os.path.dirname(bins[-1])), "lib")
    return bins[-1], seg, emb, lib


def diarize(wav, threshold, kit):
    binp, seg, emb, _ = kit
    r = subprocess.run([binp, "--clustering.cluster-threshold=%.3f" % threshold,
                        "--segmentation.num-threads=%d" % THREADS,
                        "--embedding.num-threads=%d" % THREADS,
                        "--segmentation.pyannote-window-shift-ratio=%.2f" % SHIFT,
                        "--segmentation.pyannote-model=" + seg, "--embedding.model=" + emb, wav],
                       capture_output=True, text=True, errors="replace")
    out = []
    for line in r.stdout.splitlines():
        m = re.match(r"\s*([\d.]+) -- ([\d.]+) (speaker_\d+)", line)
        if m:
            out.append((float(m.group(1)), float(m.group(2)), m.group(3)))
    return out


class Embedder:
    """sherpa-onnx 的 C 接口，ctypes 直接调。给一段 16 kHz float32 原始字节，还一个单位长度的声纹。"""

    def __init__(self, lib, model):
        # C 接口依赖 @rpath/libonnxruntime.dylib，ctypes 不认 rpath，先把它载进来
        ctypes.CDLL(os.path.join(lib, "libonnxruntime.dylib"), mode=ctypes.RTLD_GLOBAL)
        so = ctypes.CDLL(os.path.join(lib, "libsherpa-onnx-c-api.dylib"))

        class Cfg(ctypes.Structure):   # 和 c-api.h 的 SherpaOnnxSpeakerEmbeddingExtractorConfig 一致
            _fields_ = [("model", ctypes.c_char_p), ("num_threads", ctypes.c_int32),
                        ("debug", ctypes.c_int32), ("provider", ctypes.c_char_p)]
        V, P = ctypes.c_void_p, ctypes.POINTER(ctypes.c_float)

        def f(name, res, *args):
            fn = getattr(so, name)
            fn.restype, fn.argtypes = res, list(args)
            return fn
        create = f("SherpaOnnxCreateSpeakerEmbeddingExtractor", V, ctypes.POINTER(Cfg))
        self.dim_ = f("SherpaOnnxSpeakerEmbeddingExtractorDim", ctypes.c_int32, V)
        self.mkst = f("SherpaOnnxSpeakerEmbeddingExtractorCreateStream", V, V)
        self.accept = f("SherpaOnnxOnlineStreamAcceptWaveform", None, V, ctypes.c_int32, P, ctypes.c_int32)
        self.finished = f("SherpaOnnxOnlineStreamInputFinished", None, V)
        self.ready = f("SherpaOnnxSpeakerEmbeddingExtractorIsReady", ctypes.c_int32, V, V)
        self.compute = f("SherpaOnnxSpeakerEmbeddingExtractorComputeEmbedding", P, V, V)
        self.freeemb = f("SherpaOnnxSpeakerEmbeddingExtractorDestroyEmbedding", None, P)
        self.freest = f("SherpaOnnxDestroyOnlineStream", None, V)
        self._cfg = Cfg(model=model.encode(), num_threads=THREADS, debug=0, provider=b"cpu")
        self.ex = create(ctypes.byref(self._cfg))
        if not self.ex:
            raise RuntimeError("创建声纹提取器失败")
        self.dim = self.dim_(self.ex)

    def __call__(self, raw):
        n = len(raw) // 4
        if n < 1600:
            return None
        buf = (ctypes.c_float * n).from_buffer_copy(raw[:n * 4])
        st = self.mkst(self.ex)
        self.accept(st, 16000, buf, n)
        self.finished(st)
        if not self.ready(self.ex, st):
            self.freest(st)
            return None
        p = self.compute(self.ex, st)
        v = [p[i] for i in range(self.dim)]
        self.freeemb(p)
        self.freest(st)
        return unit(v)


def unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def durations(segs):
    d = collections.Counter()
    for a, z, s in segs:
        d[s] += z - a
    return d


def floor_of(total):
    """多大的堆才算一个人：30 秒（短录音按总时长 10%），而且至少总时长的 3%。"""
    return max(min(FRAGMENT_SEC, 0.1 * total), FRAGMENT_FRAC * total)


def mains(segs):
    d = durations(segs)
    fl = floor_of(sum(d.values()))
    return [s for s, t in d.most_common() if t >= fl]


def nearest_in_time(segs, keep):
    """没有声纹的碎段：并给时间上最近的主要说话人。"""
    big = [x for x in segs if x[2] in keep]
    out = []
    for a, z, s in segs:
        if s in keep or not big:
            out.append((a, z, s))
            continue
        near = min(big, key=lambda b: max(0.0, b[0] - z, a - b[1]))
        out.append((a, z, near[2]))
    return out


def centroids(segs, wav, emb):
    """每一堆取最长的若干段算声纹，求平均。太小的堆不算。"""
    by = collections.defaultdict(list)
    for a, z, s in segs:
        by[s].append((a, z))
    dur = durations(segs)
    with tempfile.TemporaryDirectory(prefix="rex-diar-") as tmp:
        raw = os.path.join(tmp, "a.f32")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", wav,
                        "-f", "f32le", "-ar", "16000", "-ac", "1", raw], capture_output=True)
        cent = {}
        with open(raw, "rb") as fh:
            for s, items in by.items():
                if dur[s] < TINY:
                    continue
                pick = sorted([x for x in items if x[1] - x[0] >= MIN_EMB],
                              key=lambda x: x[0] - x[1])[:MAXSEG]
                vs = []
                for a, z in pick:
                    fh.seek(int(a * 16000) * 4)
                    e = emb(fh.read(int((min(z, a + 10.0) - a) * 16000) * 4))
                    if e:
                        vs.append(e)
                if vs:
                    cent[s] = unit([sum(c) for c in zip(*vs)])
    return cent


def merge(segs, cent, n, log):
    """按平均声纹合并。返回 {原堆: 最终的人}。n>0 时并到恰好剩 n 个主要说话人。"""
    dur = durations(segs)
    total = sum(dur.values())
    fl = floor_of(total)
    cl = {s: (dur[s], cent[s]) for s in cent}
    owner = {s: s for s in cent}
    sim = {}
    ks = list(cl)
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            sim[(ks[i], ks[j])] = cos(cl[ks[i]][1], cl[ks[j]][1])

    def n_main():
        return sum(1 for d, _ in cl.values() if d >= fl)

    while sim:
        (a, b), c = max(sim.items(), key=lambda kv: kv[1])
        if n > 0:
            if n_main() <= n:
                break
        elif c < MERGE_SIM:
            break
        da, ca = cl.pop(a)
        db, cb = cl.pop(b)
        cl[a] = (da + db, unit([x * da + y * db for x, y in zip(ca, cb)]))
        for s, o in owner.items():
            if o == b:
                owner[s] = a
        sim = {k: v for k, v in sim.items() if a not in k and b not in k}
        for k in cl:
            if k != a:
                sim[(a, k)] = cos(cl[a][1], cl[k][1])

    keep = [s for s, (d, _) in cl.items() if d >= fl]
    if not keep and cl:
        keep = [max(cl, key=lambda s: cl[s][0])]
    if n > 0 and len(keep) < n:
        log("  只分得出 %d 个人（细分那一步就没有更多堆了）" % len(keep))
    # 碎堆并给声纹最像的那个人
    final = {}
    for s, o in owner.items():
        if o in keep:
            final[s] = o
        else:
            final[s] = max(keep, key=lambda k: cos(cl[o][1], cl[k][1]))
    return final, keep


def two_stage(wav, kit, n, log):
    """先细分、再按平均声纹合并。C 接口用不了时返回 None，调用方退回老办法。"""
    try:
        emb = Embedder(kit[3], kit[2])
    except Exception as e:  # noqa: BLE001  任何加载失败都退回老办法，说出原因
        log("  声纹 C 接口加载失败（%s），退回只用 sherpa 自己的聚类——人数可能偏多" % e)
        return None
    segs = diarize(wav, INIT_TH, kit)
    if not segs:
        return []
    cent = centroids(segs, wav, emb)
    if not cent:
        return segs
    final, keep = merge(segs, cent, n, log)
    out = [(a, z, final[s]) for a, z, s in segs if s in final]
    rest = [(a, z, s) for a, z, s in segs if s not in final]   # 太小、没算声纹的碎片
    out = nearest_in_time(sorted(out + rest), set(keep))
    log("  先细分成 %d 小堆，再按平均声纹并成 %d 个人" % (len(durations(segs)), len(keep)))
    return out


def fallback(wav, kit, n, log):
    """第一版的做法：只用 sherpa 的单段阈值。长录音会把一个人切碎，只在 C 接口用不了时走。"""
    if n > 0:
        lo, hi, best = 0.5, 0.98, None
        for _ in range(7):
            mid = (lo + hi) / 2
            segs = diarize(wav, mid, kit)
            k = len(mains(segs))
            if best is None or abs(k - n) < abs(best[1] - n):
                best = (segs, k)
            if k == n:
                break
            lo, hi = (mid, hi) if k > n else (lo, mid)
        segs = best[0]
    else:
        segs = diarize(wav, FALLBACK_TH, kit)
    return nearest_in_time(segs, set(mains(segs)))


def spectral(call):
    """混成一轨的 rex both：每 50ms 一帧，判它像本机麦克风（轻、全频带）还是通话那头
    （响、7.5 kHz 以上被砍掉）。规则和数字来自 2026-09-26 / 10-10 两场的实测。"""
    tmp = tempfile.mkdtemp(prefix="rex-spec-")
    hf, sp = os.path.join(tmp, "hf.txt"), os.path.join(tmp, "sp.txt")
    if re.search(r"[:,'\\\[\]]", tmp):
        return None
    a = "asetnsamples=n=2400,astats=metadata=1:reset=1:measure_overall=RMS_level:measure_perchannel=none"
    fc = ("[0:a]pan=mono|c0=0.5*c0+0.5*c1,asplit=2[a][b];"
          "[a]highpass=f=7500,highpass=f=7500,%s,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=%s[o1];"
          "[b]highpass=f=300,lowpass=f=3400,%s,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=%s[o2]"
          % (a, hf, a, sp))
    try:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", call,
                        "-filter_complex", fc, "-map", "[o1]", "-f", "null", "-",
                        "-map", "[o2]", "-f", "null", "-"], capture_output=True)

        def load(p):
            vals = []
            if not os.path.exists(p):
                return vals
            for line in open(p):
                if line.startswith("lavfi.astats.Overall.RMS_level="):
                    try:
                        vals.append(max(float(line.split("=", 1)[1]), -200.0))
                    except ValueError:
                        vals.append(-200.0)
            return vals
        H, P = load(hf), load(sp)
    finally:
        for p in (hf, sp):
            if os.path.exists(p):
                os.remove(p)
        os.rmdir(tmp)
    if not P:
        return None
    lab = []
    for h, v in zip(H, P):
        if v > -32 and h - v < -47:
            lab.append("R")
        elif -50 < v <= -32 and h - v > -42:
            lab.append("L")
        else:
            lab.append(None)
    return lab


def map_call(segs, lab):
    """每个人按频谱多数票对成「我」或「对方」。拿不准的返回 None，保持说话人编号。"""
    tab = collections.defaultdict(collections.Counter)
    for a, z, s in segs:
        for i in range(int(a / FRAME), min(len(lab), int(z / FRAME) + 1)):
            if lab[i]:
                tab[s][lab[i]] += 1
    names = {}
    for s, c in tab.items():
        n = c["L"] + c["R"]
        if n < 100:
            continue
        local = c["L"] / float(n)
        if local >= 0.8:
            names[s] = "我"
        elif local <= 0.6:
            names[s] = "对方"
    # 全对成一边说明这个判据在这条录音上不成立（比如通话音频本身就是全频带的）
    if "我" not in names.values() or "对方" not in names.values():
        return None
    return names


def timeline(segs):
    """每 50ms 一格，记这一格是谁在说。两人重叠时记先开始的那个。
    预先建表：2.5 小时的录音逐帧去扫几千个段要好几分钟，查表是瞬间的。"""
    if not segs:
        return []
    n = int(max(z for a, z, s in segs) / FRAME) + 1
    tl = [None] * n
    for a, z, s in sorted(segs):
        for i in range(int(a / FRAME), min(n, int(z / FRAME) + 1)):
            if tl[i] is None:
                tl[i] = s
    return tl


def cut_at_punct(text, weights):
    """按各块时长比例找切点，但只切在标点上——往两边各找到全句 40% 那么远；
    找不到就返回 None，整句给说得多的那个人。2.5 小时那条里出现过「不表认同一 /
    个观点」：比例估的切点落在词中间，最近的逗号在窗口外。换人时刻本来就只准到几秒，
    宁可整句归错人，也不把一个词劈成两半。"""
    n, total = len(text), float(sum(weights))
    cuts, acc, prev = [], 0.0, 0
    for w in weights[:-1]:
        acc += w
        target = int(round(n * acc / total))
        best = None
        for d in range(0, int(n * 0.4) + 1):
            for k in (target - d, target + d):
                if prev < k < n and text[k - 1] in "，。！？；、,.!?; ":
                    best = k
                    break
            if best:
                break
        if not best:
            return None
        cuts.append(best)
        prev = best
    pieces, prev = [], 0
    for c in cuts + [n]:
        pieces.append(text[prev:c].strip(" ，,"))
        prev = c
    return pieces


def attribute(subs, segs):
    """每句字幕找说话人：按 50ms 帧看谁在说，一个人占大头就整句给他；
    长句中间换了人（两边都连续说了 SPLIT_MIN 以上）才切，而且只切在标点上。"""
    tl = timeline(segs)
    out = []
    for s in subs:
        a, z = s["a"], s["z"]
        runs = []
        for i in range(int(a / FRAME), min(len(tl), int(z / FRAME) + 1)):
            w = tl[i]
            if w is None:
                continue
            if runs and runs[-1][0] == w:
                runs[-1][1] += FRAME
            else:
                runs.append([w, FRAME])
        if not runs:
            near = min(segs, key=lambda b: max(0.0, b[0] - z, a - b[1]))
            out.append(dict(s, who=near[2], sure=False))
            continue
        tot = collections.Counter()
        for w, d in runs:
            tot[w] += d
        top, topd = tot.most_common(1)[0]
        big = [r for r in runs if r[1] >= SPLIT_MIN]
        pieces = None
        if (topd / sum(tot.values()) < 0.7 and z - a >= SPLIT_LEN
                and len({r[0] for r in big}) >= 2):
            blocks = []
            for w, d in big:
                if blocks and blocks[-1][0] == w:
                    blocks[-1][1] += d
                else:
                    blocks.append([w, d])
            pieces = cut_at_punct(s["text"], [d for w, d in blocks])
        if not pieces:
            out.append(dict(s, who=top, sure=True))
            continue
        t0, span, tw = a, z - a, sum(d for w, d in blocks)
        for (w, d), p in zip(blocks, pieces):
            t1 = t0 + span * d / tw
            if p:
                out.append(dict(s, a=t0, z=t1, text=p, who=w, sure=True))
            t0 = t1
    return out


def unlabel(subs):
    """已经分过一次人的 .srt 每条前面带着「说话人1：」。再跑一遍 rex who（比如改人数）时
    要先去掉，不然会变成「说话人2：说话人1：……」——第一版就是这样，字数还跟着虚高。
    只有绝大多数条目都带名字时才认为是对话稿：正文里本来就会有「我说：……」。"""
    pre = [speakers.NAME_OK.match(x["text"].partition("：")[0]) and "：" in x["text"] for x in subs]
    if not subs or sum(1 for p in pre if p) < 0.8 * len(subs):
        return subs
    return [dict(x, text=x["text"].partition("：")[2]) if p else x for x, p in zip(subs, pre)]


def main():
    ap = argparse.ArgumentParser(description="按声纹分人")
    ap.add_argument("--wav", required=True, help="16 kHz 单声道")
    ap.add_argument("--srt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--speakers", type=int, default=0, help="已知人数；不给就自动判")
    ap.add_argument("--call", help="混成一轨的老 rex both 原始文件，按频谱对上我/对方")
    a = ap.parse_args()
    log = lambda m: print(m, flush=True)  # noqa: E731

    kit = tools()
    if not kit:
        log("  找不到 sherpa-onnx（应该在 %s）" % CACHE)
        return 3
    subs = unlabel(speakers.read_srt(a.srt))
    if not subs:
        log("  稿子是空的，没什么可分的")
        return 2

    segs = two_stage(a.wav, kit, a.speakers, log)
    if segs is None:
        segs = fallback(a.wav, kit, a.speakers, log)
    if not segs:
        log("  声纹分人没出结果（sherpa-onnx 没吐出任何段）")
        return 4
    order = []
    for x in sorted(segs):
        if x[2] not in order:
            order.append(x[2])

    names = None
    if a.call:
        lab = spectral(a.call)
        names = map_call(segs, lab) if lab else None
        if names:
            log("  按频谱对上了：麦克风这边 = 我，通话那头 = 对方（推测，不是分轨）")
        else:
            log("  频谱对不上（通话音频不是窄带的，或者某一边几乎没声音），保持说话人编号")
    if not names:
        names = {s: "说话人%d" % (i + 1) for i, s in enumerate(order)}
    for s in order:
        names.setdefault(s, "说话人%d" % (order.index(s) + 1))
    if len(set(names.values())) < 2:
        # 独白、讲座、播客：一个人从头说到尾，贴满「说话人1」只会让稿子更难读
        log("  只听出 1 个人在说话，稿子保持原样（其实不止一个人：rex who 文件 人数——"
            "声音很像的两个人可能被当成一个）")
        return 5

    lines = attribute(subs, segs)
    for x in lines:
        x["who"] = names[x["who"]]
    lines.sort(key=lambda x: x["a"])
    speakers.write_txt(a.out + ".txt", lines)
    speakers.write_srt(a.out + ".srt", lines)

    dur = durations(segs)
    chars = collections.Counter()
    for x in lines:
        chars[x["who"]] += len(speakers.PUNCT.sub("", x["text"]))
    shown = collections.OrderedDict()
    for s in order:
        shown.setdefault(names[s], 0.0)
        shown[names[s]] += dur[s]
    log("  分出 %d 个人：%s" % (len(shown), " · ".join(
        "%s %d 秒 %d 字" % (nm, round(t), chars[nm]) for nm, t in shown.items())))
    if a.speakers <= 0 and not a.call:
        log("  人数不对就指定：rex who 文件 人数（不重转，用已有的稿子）")
    print("CHARS %d" % sum(chars.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
