#!/usr/bin/env python3
"""几段录音合成一条（rex join）：同一场谈话分几次录的、手机录了几段的，接成一条录音，再一起校对、分析。

    python3 tools/rex_join.py 录音1 录音2 … [--name 名字] [--keep]

参数可以是音频文件，也可以是 ~/Recordings 里一条录音的名字（不带扩展名）。按给的顺序接。

## 怎么接

- 音频首尾相接，转成 48 kHz AAC。每段都是 rex both 录的（文件里有 mic、sys 两路分轨），就三路都接：混音、麦克风、
  电脑声音，对话稿照样按分轨出；否则只接每段的第一路。
- 每段都转写过（有 .srt），就不重转：稿子按时间接起来（后一段的时间戳加上前面几段的总长），校对记录也接上——
  采纳过的、拿不准等你确认的、不采纳的都留着；没校对过的那几段记成「没校成」，rex go 只补校它们。
  有一段没转写，就整条交给 rex go 重新转写（说话人也按整条一起判，几段之间对得上）。
- 记一份 <新名字>.分段.json：每段从第几秒开始、多长、原来叫什么。分析时据此告诉 Claude 这是几段接起来的。
- 原来那几条（~/Recordings 里的）挪进 ~/Recordings/已合并/<新名字>/，一个文件都不删；--keep 就留在原处。
  录音台拖进来要合成的那几个文件（先传到 ~/Recordings/.join/<组>/）也一样挪过去。
  别处的文件（比如下载目录里的）原样不动。

## 新名字

第一段开录的时刻 + 来源 + 名字。几段都是同一种来源（都是 rex both 录的、都是麦克风录的……）就沿用它，名字放在
关键词的位置：2026-10-19_090000_both_周会；来源不一样的、别处的文件，按导入的起：2026-10-19_090000_drop-周会。
名字不给就用第一段的名字（导入时的原名，或者转写后起的关键词）；第一段还没有名字，就先不起，rex go 转写完按关键词起。

先在 ~/Recordings/.join/ 下的工作目录里做齐（音频、稿子、校对记录、分段），挪走原来那几条，再一起放进录音文件夹：
列表里不会冒出半截的一条；新名字和第一段一样也不要紧（第一段已经挪走了），不用加 -2。

## 输出

最后一行 `JOINED <新录音的音频路径>`，rex.sh 接着对它跑 rex go。
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import proofread  # noqa: E402
import speakers  # noqa: E402
from i18n import L  # noqa: E402
from rex_export import NAME, parse_name  # noqa: E402

REX_DIR = os.environ.get("REX_DIR") or os.path.expanduser("~/Recordings")
CACHE = os.path.expanduser("~/.cache/rex")
AUDIO_EXT = (".m4a", ".wav", ".mp3", ".aac", ".flac", ".ogg", ".opus", ".caf", ".aiff", ".aif", ".m4b",
             ".webm", ".mp4", ".mov", ".m4v", ".mkv", ".qta")
# 一条录音在磁盘上的那些文件（和 rex_app.py 的 REC_SUFFIXES 一样，只认确切的名字）
REC_SUFFIXES = (".txt", ".srt", ".whisper.srt", ".校对.json", ".校对.md", ".分析.md", ".对话.json", ".docx", ".分段.json")
DONE_DIR = "已合并"
# 录音台拖进来要合成的几个文件，先传到这里（rex_app.py 的 save_upload），合完和录音文件夹里的一样挪进 已合并/
STAGE_DIR = os.path.join(REX_DIR, ".join")


class JoinError(Exception):
    """说给人听的一句话"""


def resolve(arg):
    """→ 一段的信息：音频、前缀（稿子在 前缀.srt）、在不在录音文件夹里（在的话 key 是它的名字）"""
    p = os.path.abspath(os.path.expanduser(arg))
    if os.path.isfile(p) and os.path.splitext(p)[1].lower() in AUDIO_EXT:
        audio, prefix = p, os.path.splitext(p)[0]
    else:
        prefix = p if os.sep in arg else os.path.join(REX_DIR, arg)      # 带斜杠的是路径，否则是录音的名字
        prefix = re.sub(r"\.(txt|srt)$", "", prefix)
        audio = next((prefix + e for e in AUDIO_EXT if os.path.isfile(prefix + e)), None)
        if not audio:
            if any(os.path.isfile(prefix.replace("_both", "_both-mic", 1) + e) for e in AUDIO_EXT):
                raise JoinError(L("「%s」是老的分轨录音（-mic、-sys 两个文件），还不能合并",
                                  "\"%s\" is an old split recording (separate -mic and -sys files); it can't be joined yet")
                                % os.path.basename(prefix))
            raise JoinError(L("找不到录音：%s", "Recording not found: %s") % arg)
    where = os.path.realpath(os.path.dirname(prefix))
    inside = where == os.path.realpath(REX_DIR)
    staged = os.path.dirname(where) == os.path.realpath(STAGE_DIR)
    return {"audio": audio, "prefix": prefix, "key": os.path.basename(prefix) if inside else None,
            "movable": inside or staged}


def probe(path):
    """→（时长秒，[每一路音频的声道数]，{分轨名: 第几路}）。分轨名是 rex both 写的 handler_name：mix / mic / sys"""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,channels:stream_tags=handler_name:format=duration", "-of", "json", path],
                       capture_output=True, text=True)
    try:
        j = json.loads(r.stdout or "{}")
    except ValueError:
        j = {}
    audio = [s for s in j.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio:
        raise JoinError(L("「%s」里没有声音", "\"%s\" has no audio") % os.path.basename(path))
    tracks = {}
    for i, s in enumerate(audio):
        h = (s.get("tags") or {}).get("handler_name")
        if h in ("mix", "mic", "sys"):
            tracks.setdefault(h, i)
    return float((j.get("format") or {}).get("duration") or 0), [int(s.get("channels") or 1) for s in audio], tracks


def started(seg):
    """这一段开录的时刻：rex 起的名字里有；别的文件看修改时间（收件箱也按它起名）"""
    m = NAME.match(seg["key"] or "")
    if m:
        y, mo, d, hh, mm, ss = m.groups()[:6]
        return datetime.datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss or 0))
    return datetime.datetime.fromtimestamp(os.path.getmtime(seg["audio"]))


def clean_name(s):
    """名字里只留字母、数字、汉字和连字符：下划线是本工具的字段分隔符，混进来会让名字认不出来"""
    s = re.sub(r"[^0-9A-Za-z一-鿿]+", "-", s).strip("-")
    return s[:40].strip("-")


def real_title(seg):
    """这一段有没有名字：导入时的原名、转写后按关键词起的名、别处文件的文件名。只有来源的（还没转写的录音）→ 空"""
    if not seg["key"]:
        return os.path.splitext(os.path.basename(seg["audio"]))[0]
    info = parse_name(seg["key"])
    if not info:
        return seg["key"]
    return (info["origin"] if info["origin"] != "drop" else "") or info["kw"]


def source_of(seg):
    """rex 起的名字里的来源：mic / sys / both / phone。导入的（drop-…）、别处的文件、老的分轨 → None"""
    m = NAME.match(seg["key"] or "")
    if not m or m.group(8) or m.group(7).startswith("drop-"):
        return None
    return m.group(7)


def stamp_of(seg):
    """名字开头的「日期_时刻」：rex 起的名字照抄（有的只到分钟），别的文件按开录时刻"""
    m = NAME.match(seg["key"] or "")
    if m:
        return "%s-%s-%s_%s%s%s" % (m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6) or "")
    return started(seg).strftime("%Y-%m-%d_%H%M%S")


def pick_key(segs, both, name, free):
    """新录音的名字（不带扩展名）。free：合完要挪走的那几段的文件，它们占着的名字可以给新录音"""
    when = stamp_of(segs[0])
    srcs = {source_of(s) for s in segs}
    src = srcs.pop() if len(srcs) == 1 else None
    if src == "both" and not both:     # 名字说是通话、文件里却没有分轨（2026-10-11 之前的 rex both）：别冒充
        src = None
    nm = clean_name(name or real_title(segs[0]))

    def named(n):
        return "%s_%s_%s" % (when, src, n) if src else "%s_drop-%s" % (when, n)

    def taken(k):
        return any(os.path.exists(f) and os.path.realpath(f) not in free
                   for f in (os.path.join(REX_DIR, k) + x for x in AUDIO_EXT + REC_SUFFIXES))

    # 没名字：先不起（drop-drop 是导入时「没有原名」的写法），rex go 转写完按关键词起
    first = named(nm) if nm else ("%s_%s" % (when, src) if src else "%s_drop-drop" % when)
    if not taken(first):
        return first
    base, i = nm or clean_name(L("合并", "joined")), 2 if nm else 1
    while True:
        k = named(base if i == 1 else "%s-%d" % (base, i))
        if not taken(k):
            return k
        i += 1


def seg_files(s):
    """这一段在磁盘上的文件：音频，加上稿子、校对、分析那些（只认确切的名字）"""
    return [s["audio"]] + [f for f in (s["prefix"] + x for x in REC_SUFFIXES) if os.path.isfile(f)]


def parts_of(segs):
    """写进 .分段.json 的每一段。哪段本身就是合成的，展开成它原来的那几段（时间挪到合起来以后的位置）"""
    out = []
    for s in segs:
        inner = []
        try:
            with open(s["prefix"] + ".分段.json", encoding="utf-8") as fh:
                inner = json.load(fh).get("segments") or []
        except (OSError, ValueError, AttributeError):
            pass
        if len(inner) > 1:      # via：中间那条合成的叫什么（它也挪进了 已合并/），录音台靠它跟到这一条上
            via = s["key"] or os.path.basename(s["audio"])
            out += [dict(p, start=round(p["start"] + s["start"], 3), via=(p.get("via") or []) + [via]) for p in inner]
        else:
            out.append({"name": os.path.basename(s["audio"]), "key": s["key"], "start": round(s["start"], 3),
                        "duration": round(s["duration"], 3), "recorded": started(s).strftime("%Y-%m-%d %H:%M")})
    return out


def go_locked(key):
    """rex go 正在处理这一条吗（和 rex.sh 的 go_one、rex_app.py 的 go_locked 同一个算法）"""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})_(\d{4,6})", key)
    k = "%s_%s" % (m.group(1), m.group(2)) if m else key
    lk = os.path.join(CACHE, "locks", hashlib.sha1(("%s/%s" % (REX_DIR, k)).encode("utf-8")).hexdigest()[:16] + ".go")
    try:
        with open(os.path.join(lk, "pid"), encoding="utf-8") as fh:
            pid = int(fh.read().strip() or 0)
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def recording_now():
    """正在录的那条的文件（.current 里的 files=），没在录就空"""
    try:
        with open(os.path.join(REX_DIR, ".current"), encoding="utf-8") as fh:
            for ln in fh:
                if ln.startswith("files="):          # 老的 --split 是两条：「a|b」
                    return {os.path.realpath(f) for f in ln[6:].rstrip("\n").split("|") if f}
    except OSError:
        pass
    return set()


def concat(segs, out, both):
    """几段音频首尾相接写到 out。both：三路（mix、mic、sys）各接各的，编码和 rex both 一样"""
    if both:
        kinds = [("mix", 2, "160k"), ("mic", 1, "64k"), ("sys", 1, "64k")]
    else:
        ch = 2 if any(s["channels"][0] >= 2 for s in segs) else 1
        kinds = [("mix", ch, "128k" if ch == 2 else "96k")]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for s in segs:
        cmd += ["-i", s["audio"]]
    parts = []
    for name, ch, _ in kinds:
        lay = "stereo" if ch == 2 else "mono"
        for i, s in enumerate(segs):
            k = s["tracks"].get(name, 0) if both else 0
            parts.append("[%d:a:%d]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=%s[%s%d]" % (i, k, lay, name, i))
        parts.append("%sconcat=n=%d:v=0:a=1[%s]" % ("".join("[%s%d]" % (name, i) for i in range(len(segs))), len(segs), name))
    cmd += ["-filter_complex", ";".join(parts)]
    for name, _, _ in kinds:
        cmd += ["-map", "[%s]" % name]
    cmd += ["-c:a", "aac", "-ar", "48000"]
    for j, (name, _, br) in enumerate(kinds):
        cmd += ["-b:a:%d" % j, br]
        if both:
            cmd += ["-metadata:s:a:%d" % j, "handler_name=%s" % name]
    tmp = os.path.join(os.path.dirname(out), "." + os.path.basename(out) + ".part.m4a")   # 点开头：列表里不冒出半截的
    r = subprocess.run(cmd + [tmp], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(tmp):
        if os.path.exists(tmp):
            os.remove(tmp)
        raise JoinError(L("接音频失败：%s", "Joining the audio failed: %s") % (r.stderr.strip().splitlines() or ["?"])[-1])
    os.replace(tmp, out)


def write_srt(path, entries):
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        fh.write("".join("%d\n%s --> %s\n%s\n\n" % (i, speakers.stamp(e["a"]), speakers.stamp(e["z"]), e["text"])
                         for i, e in enumerate(entries, 1)))
    os.replace(path + ".tmp", path)


def join_transcripts(segs, prefix):
    """每段都转写过：稿子、原稿、校对记录按时间接起来。返回接上的行数"""
    entries, raw, state = [], [], proofread.new_state()
    any_state, line_off, rid = False, 0, 1
    for n, s in enumerate(segs, 1):
        ents = proofread.read_entries(s["prefix"])
        for e in ents:
            entries.append({"a": e["a"] + s["start"], "z": e["z"] + s["start"], "text": e["text"]})
        src = s["prefix"] + ".whisper.srt" if os.path.exists(s["prefix"] + ".whisper.srt") else s["prefix"] + ".srt"
        raw += [{"a": e["a"] + s["start"], "z": e["z"] + s["start"], "text": e["text"]} for e in speakers.read_srt(src)]
        st = proofread.load_state(s["prefix"], ents) if ents else None
        if st:
            any_state = True
            # 行号、时刻挪到合起来以后的位置；编号重新排，免得几段的编号撞上（撤销、采纳都按编号认）
            for kind in ("applied", "unsure", "rejected", "missed"):
                for r in st.get(kind, []):
                    state[kind].append(dict(r, id=r["id"] + line_off, t=r["t"] + s["start"], rid=rid))
                    rid += 1
            state["failed"] += [[lo + line_off, hi + line_off] for lo, hi in st.get("failed", [])]
            for run in st.get("runs", []):
                state["runs"].append(dict(run, note=(run.get("note") or "")
                                          + L("（合并前第 %d 段）", " (segment %d before joining)") % n))
        elif ents:
            state["failed"].append([line_off + 1, line_off + len(ents)])     # 没校对过：rex go 补校这几行
        line_off += len(ents)
    write_srt(prefix + ".srt", entries)
    write_srt(prefix + ".whisper.srt", raw)
    if not speakers.rebuild(prefix):                 # 不是对话稿：一行一句
        with open(prefix + ".txt", "w", encoding="utf-8") as fh:
            fh.write("\n".join(e["text"] for e in entries) + "\n")
    if any_state:                                    # 一段都没校对过就不写，rex go 整条校
        state["next_rid"] = rid
        state["failed"] = proofread.to_ranges(sorted({i for lo, hi in state["failed"] for i in range(lo, hi + 1)}))
        proofread.save_state(prefix, state)
    return len(entries)


def move_originals(segs, key):
    """录音文件夹里的（和录音台暂存区里的）那几条挪进 已合并/<新名字>/，一个文件都不删"""
    dest = os.path.join(REX_DIR, DONE_DIR, key)
    moved = 0
    for s in segs:
        if not s["movable"]:
            continue
        os.makedirs(dest, exist_ok=True)
        for f in seg_files(s):
            to = os.path.join(dest, os.path.basename(f))
            if os.path.exists(to):
                to = os.path.join(dest, "%d-%s" % (int(datetime.datetime.now().timestamp()), os.path.basename(f)))
            os.replace(f, to)
            moved += 1
        if not s["key"]:
            try:
                os.rmdir(os.path.dirname(s["audio"]))       # 暂存区那一组空了就收掉；还有东西就留着
            except OSError:
                pass
    return dest if moved else None


def join(args, name=None, keep=False):
    """→ 新录音的音频路径。出错抛 JoinError，什么都不留下"""
    if len(args) < 2:
        raise JoinError(L("要两段以上才能合成一条", "Joining needs at least two recordings"))
    segs = [resolve(a) for a in args]
    if len({os.path.realpath(s["audio"]) for s in segs}) < len(segs):
        raise JoinError(L("同一段给了两遍", "The same recording was given twice"))
    now = recording_now()
    for s in segs:
        if os.path.realpath(s["audio"]) in now:
            raise JoinError(L("「%s」正在录，先停下再合并", "\"%s\" is still recording; stop it before joining") % os.path.basename(s["prefix"]))
        if s["key"] and go_locked(s["key"]):
            raise JoinError(L("「%s」正在处理，等它跑完再合并", "\"%s\" is being processed; wait for it to finish") % s["key"])
        s["duration"], s["channels"], s["tracks"] = probe(s["audio"])
    both = all("mic" in s["tracks"] and "sys" in s["tracks"] for s in segs)
    off = 0.0
    for s in segs:
        s["start"] = off
        off += s["duration"]
    reuse = all(os.path.exists(s["prefix"] + ".srt") and os.path.getsize(s["prefix"] + ".srt") > 0 for s in segs)
    free = set() if keep else {os.path.realpath(f) for s in segs if s["movable"] for f in seg_files(s)}
    key = pick_key(segs, both, name, free)

    os.makedirs(STAGE_DIR, exist_ok=True)
    work = tempfile.mkdtemp(prefix="work-", dir=STAGE_DIR)       # 和录音文件夹在同一个盘上：最后一步只是改名
    wp = os.path.join(work, key)
    try:
        concat(segs, wp + ".m4a", both)
        lines = join_transcripts(segs, wp) if reuse else 0
        with open(wp + ".分段.json", "w", encoding="utf-8") as fh:
            json.dump({"tracks": both, "reused_transcripts": reuse, "segments": parts_of(segs)},
                      fh, ensure_ascii=False, indent=1)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)      # 工作目录里只有这次新做的东西
        raise
    dest = None if keep else move_originals(segs, key)
    made = [f for f in sorted(os.listdir(work)) if not f.startswith(".")]
    clash = [f for f in made if os.path.exists(os.path.join(REX_DIR, f))]
    if clash:      # 刚才还空着的名字被占了（收件箱同时放进来一条？）：绝不盖掉，做好的留在工作目录里
        raise JoinError(L("录音文件夹里已经有「%s」了，没放进去；合好的在 %s", "\"%s\" already exists in the recordings folder, "
                          "so nothing was put there; the joined recording is in %s") % (clash[0], work))
    for f in made:
        os.replace(os.path.join(work, f), os.path.join(REX_DIR, f))
    shutil.rmtree(work, ignore_errors=True)
    audio = os.path.join(REX_DIR, key + ".m4a")

    print(L("合成了 %d 段，共 %d 分钟：%s", "Joined %d recordings, %d min in total: %s")
          % (len(segs), round(off / 60), os.path.basename(audio)), file=sys.stderr)
    if reuse:
        print(L("  几段的稿子和校对记录接上了（%d 行），不重新转写", "  The transcripts and proofreading records were joined (%d lines); nothing is transcribed again")
              % lines, file=sys.stderr)
    else:
        print(L("  有的段还没转写：整条重新转写", "  Some recordings weren't transcribed yet: the whole thing will be transcribed"), file=sys.stderr)
    if dest:
        print(L("  原来那几条挪进了 %s（没删）", "  The original recordings were moved to %s (nothing deleted)") % dest, file=sys.stderr)
    return audio


def main():
    ap = argparse.ArgumentParser(description=L("几段录音合成一条", "Join several recordings into one"))
    ap.add_argument("recordings", nargs="+", help=L("音频文件，或录音文件夹里录音的名字；按给的顺序接",
                                                     "Audio files or names of recordings in the recordings folder, in order"))
    ap.add_argument("--name", help=L("新录音的名字（默认用第一段的标题）", "Name of the new recording (default: the first one's title)"))
    ap.add_argument("--keep", action="store_true", help=L("原来那几条留在原处", "Leave the original recordings where they are"))
    a = ap.parse_args()
    try:
        audio = join(a.recordings, a.name, a.keep)
    except JoinError as e:
        print(e.args[0], file=sys.stderr)
        return 1
    print("JOINED %s" % audio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
