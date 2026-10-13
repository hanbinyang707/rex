#!/usr/bin/env python3
"""把录音末尾的空白切掉——忘了 `rex stop` 的那一段。

被 rex.sh 的 `rex trim` 调用：

    rex trim                     # 最近一次录音
    rex trim 某文件.m4a
    rex trim 某文件.m4a --to 49:30   # 手动指定：只保留到 49:30
    rex trim --dry-run           # 只看会切多少，不动文件

## 只切末尾，不切中间

2026-09-22 真事：一条 1 小时 43 分的 `sys` 录音，内容到 49:51 就结束了，后面
53 分 54 秒是忘了停的数字静音。但**中间还有 4 段 20~67 秒的停顿**（播客里的
间歇、换片段）。「把所有空白都删掉」会把这 4 段一起切了，时间轴整体前移，
已经转写的 .srt 就对不上音频了。

只切末尾则完全没有这个问题：末尾之前的每一秒都原样保留，时间戳一个都不动。
开头的空白也**故意不切**——切开头会让后面所有时间戳整体平移。

## 判据按音源分，不共用一个阈值

这条是 2026-08-19 看门狗那次踩出来的：

  - `sys` / `both-sys`：BlackHole 虚拟设备，没声音就是**真数字零**（-91.0 dB）。
    阈值放在 -70 dB，离真实内容和真静音都很远，不会误判。
  - 其他（麦克风、手机、播客下载）：真麦克风有本底噪声，安静房间 -55 ~ -70 dB。
    阈值放在 -50 dB。说话的峰值基本在 -10 ~ -35 dB，远在它上面。

而且只认**至少 `MIN_TAIL` 秒、一直延续到文件结尾**的静音。说话随时会打断它，
所以中间的停顿再长也不会被当成末尾空白。

## 原件进废纸篓，不删

这个工具链在这台机器上删过作者的录音（`rm` 不经过废纸篓，三份转写稿找回一份），
所以这里**绝不删除**：切好的新文件验证过时长，才把原件用 macOS 自带的
`/usr/bin/trash` 送进废纸篓——访达里右键「放回原处」就能恢复。`trash` 不可用时
退而把原件改名成 `<名字>.m4a.untrimmed` 留在原处（这个后缀不匹配 `*.m4a`，
所以 `rex ls` / `rex text` 不会把它当成录音）。

## 切的是容器，不重新编码

`ffmpeg -c copy -t`：只截断，不解码不重编，**音质零损失**，几秒钟完成。
AAC 一帧约 21 毫秒，切点落在帧边界上，误差在这个量级。

## 已经转写过的话

.srt 里起点晚于切点的条目会被去掉，.txt 按剩下的条目重建。有 VAD 的话，
数字静音里本来就转不出东西，通常一条都不用删。
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

from i18n import L

MIN_TAIL = 30      # 末尾空白至少这么长才值得切。短了就是正常的收尾停顿
KEEP = 3.0         # 切点往后多留几秒，免得切掉最后一个字的尾音
DIGITAL = -70      # BlackHole 那一路的阈值（真静音是 -91.0）
ACOUSTIC = -50     # 真麦克风那一路的阈值（本底噪声 -55 ~ -70）


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace")


def duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path])
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def threshold_for(path):
    """从文件名认音源。`_sys` 和 `_both-sys` 走的是 BlackHole，其余都是真麦克风。"""
    stem = os.path.basename(path)
    if re.search(r"_(both-)?sys(\b|_|\.|-)", stem):
        return DIGITAL, L("系统声音（数字通路，静音即 -91 dB）", "system audio, a digital path where silence is -91 dB")
    return ACOUSTIC, L("麦克风类音源（有本底噪声）", "a microphone-type source with a noise floor")


def trailing_silence(path, dur, noise):
    """返回末尾静音的起点（秒）；末尾没有够长的静音就返回 None。"""
    # -map 0:a:0：rex both 的文件里有三条轨（混音/麦克风/系统声音），量混音那条。
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:a:0",
             "-af", "silencedetect=noise=%ddB:d=%d" % (noise, MIN_TAIL),
             "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", r.stderr)]
    if not starts:
        return None
    last = starts[-1]
    # 两种形态都要认：有的版本在文件结尾补一个 silence_end，有的不补
    if len(ends) < len(starts):
        return last
    if ends and abs(ends[-1] - dur) <= 1.5 and ends[-1] > last:
        return last
    return None


def peak_between(path, a, b):
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-ss", "%.2f" % a, "-t", "%.2f" % (b - a),
             "-i", path, "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"max_volume: (-?[0-9.]+|-inf) dB", r.stderr)
    return m.group(1) if m else "?"


def parse_time(s):
    """49:30 / 1:02:03 / 2970 都认。"""
    parts = s.strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise SystemExit(L("看不懂这个时间：%s（写成 49:30 或 1:02:03 或秒数）",
                           "Can't parse this time: %s (write 49:30, 1:02:03 or a number of seconds)") % s)
    sec = 0.0
    for n in nums:
        sec = sec * 60 + n
    return sec


def hms(sec):
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


def human(n):
    for u in ("B", "K", "M", "G"):
        if n < 1024 or u == "G":
            return "%dB" % n if u == "B" else "%.1f%s" % (n, u)
        n /= 1024.0


def trim_transcript(stem, cut):
    """去掉 .srt 里起点晚于切点的条目，.txt 按剩下的重建。返回去掉了几条。"""
    srt = stem + ".srt"
    if not os.path.exists(srt):
        return None
    text = open(srt, "rb").read().decode("utf-8", "replace")
    blocks = [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    keep, dropped = [], 0
    for b in blocks:
        m = re.search(r"(\d\d):(\d\d):(\d\d)[,.](\d\d\d)\s*-->", b)
        if m:
            h, mi, s, ms = (int(x) for x in m.groups())
            if h * 3600 + mi * 60 + s + ms / 1000.0 >= cut:
                dropped += 1
                continue
        keep.append(b)
    if not dropped:
        return 0
    out, lines = [], []
    for i, b in enumerate(keep, 1):
        ls = b.strip().split("\n")
        body = ls[2:] if ls[0].strip().isdigit() else ls[1:]
        ts = ls[1] if ls[0].strip().isdigit() else ls[0]
        out.append("%d\n%s\n%s" % (i, ts, "\n".join(body)))
        lines.append(" ".join(x.strip() for x in body if x.strip()))
    with open(srt, "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(out) + "\n")
    # 对话稿（speakers.py 写的，每条前面带名字）要按发言轮次重排，
    # 不能拍平成一条一行——那样时间戳和「谁说的」都丢了。
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import speakers
        if speakers.rebuild(stem):
            return dropped
    except ImportError:
        pass
    with open(stem + ".txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(l for l in lines if l) + "\n")
    return dropped


def to_trash(path):
    """原件送进废纸篓。失败就改名留在原处——无论如何不删。"""
    if shutil.which("trash"):
        r = run(["trash", path])
        if r.returncode == 0 and not os.path.exists(path):
            return L("原件已放进废纸篓（访达里右键「放回原处」可以恢复）",
                     "Original moved to the Trash (Finder's Put Back restores it)")
    keep = path + ".untrimmed"
    n = 1
    while os.path.exists(keep):
        n += 1
        keep = "%s.untrimmed%d" % (path, n)
    os.rename(path, keep)
    return L("废纸篓不可用，原件改名留在原处：%s",
             "Trash unavailable; original renamed and left in place: %s") % os.path.basename(keep)


def main():
    ap = argparse.ArgumentParser(description=L("切掉录音末尾的空白", "Cut the trailing silence off a recording"))
    ap.add_argument("path")
    ap.add_argument("--to", default="", help=L("手动指定：只保留到这个时间（49:30）",
                                               "manual cut: keep only up to this time (49:30)"))
    ap.add_argument("--dry-run", action="store_true", help=L("只报告，不动文件", "report only; don't touch the file"))
    a = ap.parse_args()

    f = a.path
    if not os.path.isfile(f):
        print(L("没有这个文件：%s", "No such file: %s") % f)
        return 1
    dur = duration(f)
    if dur <= 0:
        print(L("读不出时长：%s", "Can't read the duration: %s") % f)
        return 1

    name = os.path.basename(f)
    print(L("%s  （%s）", "%s  (%s)") % (name, hms(dur)))

    if a.to:
        cut = parse_time(a.to)
        if cut >= dur - 0.5:
            print(L("  --to %s 不短于录音本身（%s），没什么可切的。",
                    "  --to %s is not shorter than the recording itself (%s); nothing to cut.")
                  % (a.to, hms(dur)))
            return 0
        if cut <= 0:
            print(L("  --to 必须大于 0。", "  --to must be greater than 0."))
            return 1
        print(L("  手动切点：只保留到 %s，后面 %s 丢掉（峰值 %s dB）",
                "  Manual cut: keeping up to %s, dropping the remaining %s (peak %s dB)")
              % (hms(cut), hms(dur - cut), peak_between(f, cut, dur)))
    else:
        noise, what = threshold_for(f)
        start = trailing_silence(f, dur, noise)
        if start is None:
            tail = max(0.0, dur - 60)
            print(L("  末尾没有 %d 秒以上的空白，不用切。",
                    "  No trailing silence of %d seconds or more; nothing to cut.") % MIN_TAIL)
            print(L("  （按%s判，阈值 %d dB；最后 1 分钟峰值 %s dB）",
                    "  (judged as %s; threshold %d dB; peak in the last minute %s dB)")
                  % (what, noise, peak_between(f, tail, dur)))
            print(L("  如果确实有一段没用的尾巴，但它不是静音（比如电脑在放别的），",
                    "  If there really is a useless tail that isn't silence (say, the computer was "
                    "playing something else),"))
            print(L("  用 --to 手动指定保留到哪里，例如：rex trim %s --to 49:30",
                    "  use --to to set how much to keep, e.g.: rex trim %s --to 49:30") % name)
            return 0
        cut = min(dur, start + KEEP)
        print(L("  末尾空白：%s → %s，共 %s（峰值 %s dB）",
                "  Trailing silence: %s → %s, %s in total (peak %s dB)")
              % (hms(start), hms(dur), hms(dur - start), peak_between(f, start, dur)))
        print(L("  切到 %s（多留 %d 秒，免得切掉最后一个字的尾音）",
                "  Cutting at %s (keeping %d extra seconds so the last word isn't clipped)") % (hms(cut), KEEP))

    if a.dry_run:
        print(L("  --dry-run：没动文件。", "  --dry-run: file not touched."))
        return 0

    root, ext = os.path.splitext(f)
    tmp = root + ".trimming" + ext
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", f,
             "-t", "%.3f" % cut, "-map", "0", "-c", "copy", "-movflags", "+faststart", tmp])
    got = duration(tmp) if os.path.exists(tmp) else 0.0
    # 验过才动原件：新文件时长必须对得上切点。对不上就是 ffmpeg 出了岔子，
    # 这时候去动原件等于拿一个坏文件换一个好文件。
    if r.returncode != 0 or abs(got - cut) > 1.5:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(L("  ✗ 切出来的文件不对（期望 %s，实际 %s），原件没动。",
                "  ✗ The trimmed file is wrong (expected %s, got %s); the original is untouched.")
              % (hms(cut), hms(got)))
        if r.stderr.strip():
            print("    " + r.stderr.strip().splitlines()[-1])
        return 1

    before = os.path.getsize(f)
    msg = to_trash(f)
    os.rename(tmp, f)
    print("  ✓ %s → %s · %s → %s" % (hms(dur), hms(got), human(before), human(os.path.getsize(f))))
    print("  %s" % msg)

    n = trim_transcript(root, cut)
    if n:
        print(L("  转写稿里切点之后的 %d 条也一并去掉了（.srt 和 .txt）",
                "  Transcript entries after the cut point removed as well: %d (.srt and .txt)") % n)
    elif n == 0:
        print(L("  转写稿不用动（切点之后本来就没有内容）",
                "  Transcript unchanged (there was nothing after the cut point)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
