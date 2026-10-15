#!/usr/bin/env python3
"""录音台：rex 的本地网页界面。只开在 127.0.0.1，一般用 `rex app` 起。

    python3 tools/rex_app.py            # 端口默认 8790，改 REX_APP_PORT

## 为什么是网页，不是原生 App

作者 2026-10-12 提的：命令太多记不住，录完之后的活又多——一条 65 分钟的
录音校对完有 130 处「拿不准」，在 Markdown 表格里一条条看、再手动改稿子，很累。「看、对照、点采纳」
这种活网页最顺手，而且仓库本来就是一个只在本机跑的站点。Safari 里「添加到程序坞」就是一个独立窗口。

## 分工和别处一样：Python 干活，页面只显示

判断和计算全在这里和 proofread.py 里：列录音、读状态、改稿子（`proofread.decide()`，和命令行同一份
写法）、跑 rex.sh。app.js 只画界面、把按钮翻译成请求。要处理录音就排队跑 `rex.sh go`，一次只跑一个
（转写吃显卡，两个一起跑谁都慢）。

## 安全

这个服务能改稿子、能开始录音、能把稿子发给 Claude。浏览器里任何一个网页都能往 127.0.0.1 发请求，
所以光「只开在本机」不够：
- 认 Host 头，只接受 127.0.0.1 / localhost 加本端口（防 DNS rebinding：别的域名解析到 127.0.0.1）
- 打开首页时发一个随机口令放进 cookie（SameSite=Strict，别的网站发来的请求不带它），除首页和 app.js
  以外的请求都要带；服务每次启动换一个口令
- 会改东西的请求（POST）还要带自定义头 X-Rex-App，并核对 Origin。跨站请求带自定义头会先发预检，
  这里不答应预检，浏览器就不会发出去

## 不写进仓库

录音、稿子都在 ~/Recordings，这里只读写那里。缓存（时长、任务日志）在 ~/.cache/rex。
"""

import datetime
import http.server
import json
import hashlib
import os
import queue
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import claude_cli  # noqa: E402
import proofread  # noqa: E402
import rex_export  # noqa: E402
from i18n import L, EN  # noqa: E402
from rex_export import parse_name  # noqa: E402  文件名怎么认、标题怎么取：和手机页、Word 共用一份

REX_DIR = os.environ.get("REX_DIR") or os.path.expanduser("~/Recordings")
INBOX = os.environ.get("REX_INBOX") or os.path.join(REX_DIR, "收件箱")
INBOX_LOG = os.environ.get("REX_INBOX_LOG") or os.path.expanduser("~/Library/Logs/rex-inbox.log")
INBOX_LABEL = os.environ.get("REX_INBOX_LABEL") or "local.rex.inbox"
VM_DIR = os.path.expanduser("~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings")
PORT = int(os.environ.get("REX_APP_PORT") or 8790)
CACHE = os.path.expanduser("~/.cache/rex")
STATIC = os.path.join(TOOLS, "rex_app")
REX_SH = os.path.join(TOOLS, "rex.sh")
TOKEN = secrets.token_hex(16)
CHAT_TIMEOUT = 900

AUDIO_EXT = {".m4a", ".wav", ".qta", ".mp3", ".aac", ".flac", ".ogg", ".opus", ".caf", ".aiff", ".aif",
             ".m4b", ".webm", ".mp4", ".mov", ".m4v", ".mkv"}
MEDIA_TYPE = {".m4a": "audio/mp4", ".m4b": "audio/mp4", ".mp4": "video/mp4", ".m4v": "video/mp4",
              ".mov": "video/quicktime", ".wav": "audio/wav", ".mp3": "audio/mpeg", ".aac": "audio/aac",
              ".flac": "audio/flac", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".webm": "audio/webm",
              ".caf": "audio/x-caf", ".aiff": "audio/aiff", ".aif": "audio/aiff", ".qta": "audio/mp4"}
DIALOGUE = re.compile(r"^\[[0-9:]+\] ([^：]{1,12})：")

_dur_lock = threading.Lock()


def log(msg):
    print("%s %s" % (time.strftime("%H:%M:%S"), msg), file=sys.stderr, flush=True)


def child_env():
    # REX_LANG 显式传下去：录音、处理排出去的 rex.sh 回的话（页面上直接显示）和界面同一种语言，
    # 哪怕服务起来以后 ~/.config/rex/lang 又改过
    env = dict(os.environ, LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8", REX_DIR=REX_DIR, REX_LANG="en" if EN else "zh")
    return env


# ---------------------------------------------------------------- 时长缓存
#
# ffprobe 一个文件几十毫秒，二十几条录音每次刷新都量一遍就太慢了。按 (路径, 修改时间, 大小) 记住

def _dur_path():
    return os.path.join(CACHE, "app-durations.json")


def durations(paths):
    with _dur_lock:
        try:
            with open(_dur_path(), encoding="utf-8") as fh:
                cache = json.load(fh)
        except (OSError, ValueError):
            cache = {}
        out, dirty = {}, False
        for p in paths:
            try:
                st = os.stat(p)
            except OSError:
                continue
            sig = "%d:%d" % (st.st_mtime, st.st_size)
            hit = cache.get(p)
            if hit and hit[0] == sig:
                out[p] = hit[1]
                continue
            try:
                r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "csv=p=0", p], capture_output=True, text=True, timeout=20)
                d = float((r.stdout.strip().split("\n") or ["0"])[0] or 0)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                d = 0.0
            cache[p] = [sig, d]
            out[p] = d
            dirty = True
        if dirty:
            try:
                os.makedirs(CACHE, exist_ok=True)
                tmp = _dur_path() + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(cache, fh, ensure_ascii=False)
                os.replace(tmp, _dur_path())
            except OSError as e:            # 缓存写不进去（磁盘满、目录不可写）不该让整个 /api/state 报 500
                log(L("时长缓存没写进去：%s", "Couldn't write the duration cache: %s") % e)
        return out


# ---------------------------------------------------------------- 录音列表

def proof_summary(prefix):
    js = prefix + ".校对.json"
    if os.path.exists(js):
        try:
            with open(js, encoding="utf-8") as fh:
                st = json.load(fh)
            return {"applied": len(st.get("applied", [])), "unsure": len(st.get("unsure", [])),
                    "failed": sum(b - a + 1 for a, b in st.get("failed", []))}
        except (OSError, ValueError):
            pass
    md = prefix + ".校对.md"
    if os.path.exists(md):
        s = open(md, encoding="utf-8").read(3000)
        # 报告是按写它那会儿的语言写的，和现在界面是什么语言无关：中文、英文的摘要行都认
        m = (re.search(r"改了 \*\*(\d+)\*\* 处 · 拿不准、没改 \*\*(\d+)\*\* 处", s)
             or re.search(r"Changed: \*\*(\d+)\*\* · Uncertain, not changed: \*\*(\d+)\*\*", s))
        f = re.search(r"(\d+) 份校对失败", s) or re.search(r"Lines not proofread yet: (\d+)", s)
        if m:
            return {"applied": int(m.group(1)), "unsure": int(m.group(2)), "failed": int(f.group(1)) if f else 0}
    return None


def scan():
    groups = {}
    try:
        names = os.listdir(REX_DIR)
    except OSError:
        return []
    for f in names:
        p = os.path.join(REX_DIR, f)
        if f.startswith(".") or not os.path.isfile(p):
            continue
        stem, ext = os.path.splitext(f)
        if ext.lower() in AUDIO_EXT:
            key = stem.replace("_both-mic", "_both").replace("_both-sys", "_both")    # 分轨那一对合成一条
            groups.setdefault(key, []).append(p)
        elif ext == ".txt" and "." not in stem:
            groups.setdefault(stem, [])
    durs = durations([p for ps in groups.values() for p in ps])
    out = []
    for key, audio in groups.items():
        prefix = os.path.join(REX_DIR, key)
        info = parse_name(key) or {"when": "", "source": L("其它", "Other"), "origin": "", "title": key}
        audio.sort(key=lambda p: ("-sys" in p, p))           # 分轨的那对：麦克风那条在前
        txt = prefix + ".txt"
        has_txt = os.path.exists(txt) and os.path.getsize(txt) > 0
        speakers_seen, dialogue = [], False
        if has_txt:
            with open(txt, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    m = DIALOGUE.match(line)
                    if m:
                        dialogue = True
                        if m.group(1) not in speakers_seen:
                            speakers_seen.append(m.group(1))
                    if i > 400:
                        break
        mtimes = [os.path.getmtime(p) for p in audio + ([txt] if has_txt else [])]
        if not info["when"]:
            info["when"] = datetime.datetime.fromtimestamp(max(mtimes) if mtimes else 0).strftime("%Y-%m-%d %H:%M")
        out.append(dict(info, key=key, audio=len(audio), split=len(audio) > 1,
                        duration=round(max([durs.get(p, 0) for p in audio] or [0])),
                        transcribed=has_txt, chars=(os.path.getsize(txt) // 3) if has_txt else 0,
                        dialogue=dialogue, speakers=speakers_seen[:6],
                        proof=proof_summary(prefix), analyzed=os.path.exists(prefix + ".分析.md"),
                        chats=len(load_chat(prefix).get("turns", [])),
                        busy=JOBS.busy(key)))
    out.sort(key=lambda r: r["when"], reverse=True)
    return out


def detail(key):
    prefix = os.path.join(REX_DIR, key)
    if not key or "/" in key or not (os.path.exists(prefix + ".txt") or os.path.exists(prefix + ".srt")
                                     or any(os.path.exists(prefix + e) for e in AUDIO_EXT)
                                     or audio_files(key)):
        return None
    entries = proofread.read_entries(prefix) if os.path.exists(prefix + ".srt") else []
    labeled = proofread.has_labels(entries)      # 每份稿子自己判是不是对话稿，别靠 proofread 的进程全局（多线程）
    rows = []
    for e in entries:
        who, text = proofread.split_label(e["text"], labeled)
        rows.append({"id": e["id"], "a": round(e["a"], 2), "z": round(e["z"], 2), "who": who or "", "text": text})
    state = proofread.load_state(prefix, entries) if entries else None
    analysis = None
    if os.path.exists(prefix + ".分析.md"):
        with open(prefix + ".分析.md", encoding="utf-8") as fh:
            analysis = fh.read()
    info = parse_name(key) or {"when": "", "source": L("其它", "Other"), "origin": "", "title": key}
    return dict(info, key=key, entries=rows, proof=state, analysis=analysis,
                chat=load_chat(prefix).get("turns", []), audio=[os.path.basename(p) for p in audio_files(key)],
                busy=JOBS.busy(key), has_session=bool(session_of(prefix)))


def audio_files(key):
    prefix = os.path.join(REX_DIR, key)
    out = [prefix + e for e in sorted(AUDIO_EXT) if os.path.exists(prefix + e)]
    if not out and "_both" in key:
        for tr in ("mic", "sys"):
            k2 = key.replace("_both", "_both-" + tr, 1)
            out += [os.path.join(REX_DIR, k2 + e) for e in sorted(AUDIO_EXT) if os.path.exists(os.path.join(REX_DIR, k2 + e))]
    return out


# 一条录音在磁盘上是这些文件：音频（老的 --split 是两条分轨）、稿子、校对和分析的产物。只认这些确切的名字，
# 不按前缀通配——X 和 X_关键词 是两条不同的录音
REC_SUFFIXES = (".txt", ".srt", ".whisper.srt", ".校对.json", ".校对.md", ".分析.md", ".对话.json", ".docx")


def recording_files(key):
    prefix = os.path.join(REX_DIR, key)
    return audio_files(key) + [prefix + s for s in REC_SUFFIXES if os.path.exists(prefix + s)]


def to_trash(path):
    """移到废纸篓，访达里能「放回原处」。macOS 自带 /usr/bin/trash；没有就让访达来删（同样进废纸篓）。绝不直接删——
    这个工具链删过作者的录音（rm 不经过废纸篓），所以全仓库只有这一种「删」。"""
    tr = shutil.which("trash") or ("/usr/bin/trash" if os.path.exists("/usr/bin/trash") else None)
    if tr:
        subprocess.run([tr, path], capture_output=True, timeout=30)
    if os.path.exists(path):
        esc = path.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", 'tell application "Finder" to delete (POSIX file "%s" as alias)' % esc],
                       capture_output=True, timeout=30)
    return not os.path.exists(path)


def trash_recording(key):
    """录音台里双击一条：整条录音移到废纸篓。正在录的、正在处理的不动。返回 (成没成, 说明)。"""
    files = recording_files(key)
    if not files:
        return False, L("这条没有文件了（刷新一下）", "This recording has no files left (refresh)")
    now = recording_now()
    if now.get("on") and set(now.get("files", [])) & {os.path.basename(f) for f in files}:
        return False, L("这条正在录，先停下再删", "This one is still recording. Stop it before deleting")
    if JOBS.busy(key):
        return False, L("这条正在处理，等它跑完再删", "This one is being processed. Wait for it to finish, then delete")
    for f in files:
        to_trash(f)
    left = [f for f in files if os.path.exists(f)]
    if left:
        return False, L("有 %d 个文件没移走：%s" % (len(left), "、".join(os.path.basename(x) for x in left[:3])),
                        "%s couldn't be moved: %s" % (files_en(len(left)), ", ".join(os.path.basename(x) for x in left[:3])))
    log(L("移到废纸篓：%s（%d 个文件）" % (key, len(files)), "Moved to the Trash: %s (%s)" % (key, files_en(len(files)))))
    return True, L("移到废纸篓了（%d 个文件）。删错了：访达 → 废纸篓 → 右键「放回原处」" % len(files),
                   "Moved to the Trash (%s). To undo: Finder → Trash → right-click → Put Back" % files_en(len(files)))


def files_en(n):
    return "%d file%s" % (n, "" if n == 1 else "s")


# ---------------------------------------------------------------- 接着问（分析那个会话）

def load_chat(prefix):
    try:
        with open(prefix + ".对话.json", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def session_of(prefix):
    """接着问用哪个会话：网页问过就用 .对话.json 记的那个；但重做过分析（.分析.md 比它新）就换成新报告里的。
    不然删了 .分析.md 重跑 rex go 之后，报告是新的、网页还在问旧会话，两边对不上。"""
    c = load_chat(prefix)
    report_sid, report_mtime = None, 0
    try:
        s = open(prefix + ".分析.md", encoding="utf-8").read(4000)
        # 报告头里第一个 UUID 就是会话号（新报告写「会话号 `…`」，老报告写 `claude --resume …`，都认）
        m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", s)
        report_sid = m.group(0) if m else None
        report_mtime = os.path.getmtime(prefix + ".分析.md")
    except OSError:
        pass
    if c.get("sid"):
        try:
            chat_mtime = os.path.getmtime(prefix + ".对话.json")
        except OSError:
            chat_mtime = 0
        if not report_sid or report_mtime <= chat_mtime:
            return c["sid"]
    return report_sid


_chat_locks = {}


def chat(key, question):
    prefix = os.path.join(REX_DIR, key)
    sid = session_of(prefix)
    if not sid:
        return {"ok": False, "msg": L("这条还没有分析，先处理它（rex go）再来问",
                                      "No analysis yet. Process it first (rex go), then ask")}
    lock = _chat_locks.setdefault(key, threading.Lock())
    if not lock.acquire(blocking=False):
        return {"ok": False, "msg": L("上一个问题还在等回答", "Still waiting for the answer to the previous question")}
    try:
        # 会话存在 REX_DIR 下（analyze.py 的 --cwd），resume 要在那儿跑；ANTHROPIC_* 由 claude_cli 清掉
        obj = claude_cli.run(["--resume", sid, "--tools", "", "--disable-slash-commands", question], "",
                             CHAT_TIMEOUT, cwd=REX_DIR)
    except claude_cli.AccountError as e:
        return {"ok": False, "msg": e.args[0]}
    except RuntimeError as e:
        return {"ok": False, "msg": L("没问成：%s", "Couldn't ask: %s") % e}
    finally:
        lock.release()
    answer = (obj.get("result") or "").strip()
    c = load_chat(prefix)
    c["sid"] = obj.get("session_id") or sid
    c.setdefault("turns", []).append({"q": question, "a": answer, "when": time.strftime("%Y-%m-%d %H:%M"),
                                      "cost": obj.get("total_cost_usd")})
    tmp = prefix + ".对话.json.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(c, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, prefix + ".对话.json")
    return {"ok": True, "answer": answer}


# ---------------------------------------------------------------- 任务队列：一次跑一个 rex.sh

class Jobs:
    def __init__(self):
        self.q = queue.Queue()
        self.items = []
        self.lock = threading.Lock()
        threading.Thread(target=self._worker, daemon=True).start()

    # state 只有「排队 / 进行中 / 完成 / 出错」这四个固定值，不跟界面语言走：这里和 app.js 都拿它比较，
    # app.js 显示时再翻成英文。label 只给人看，跟着语言走
    def add(self, kind, key, label, steps):
        """steps：要依次跑的命令；某一步可以是函数，到时候才算出命令（比如导入完才知道文件名）。"""
        jid = uuid.uuid4().hex[:8]
        job = {"id": jid, "kind": kind, "key": key, "label": label, "state": "排队",
               "added": time.time(), "started": None, "ended": None, "rc": None,
               "log": os.path.join(CACHE, "app-jobs", "%s-%s.log" % (time.strftime("%Y%m%d-%H%M%S"), jid)),
               "_steps": steps}
        with self.lock:
            self.items.append(job)
            self.items = self.items[-30:]
        self.q.put(job)
        return job

    def busy(self, key):
        # 自己排的任务（转写改名 X → X_关键词 之后，新名字也算同一条），加上别处（收件箱监视、终端）正在跑的
        with self.lock:
            mine = any((j["key"] == key or (j["key"] and key.startswith(j["key"] + "_")))
                       and j["state"] in ("排队", "进行中") for j in self.items)
        return mine or go_locked(key)

    def running(self, kind):
        with self.lock:
            return any(j["kind"] == kind and j["state"] in ("排队", "进行中") for j in self.items)

    def view(self):
        with self.lock:
            out = []
            for j in self.items[-8:]:
                tail = []
                try:
                    with open(j["log"], encoding="utf-8", errors="replace") as fh:
                        tail = [ln.rstrip() for ln in fh.readlines()[-8:] if ln.strip()]
                except OSError:
                    pass
                out.append({k: j[k] for k in ("id", "kind", "key", "label", "state", "started", "ended", "rc")}
                           | {"tail": [re.sub(r"\x1b\[[0-9;]*m", "", t) for t in tail]})
            return out

    def _worker(self):
        while True:
            job = self.q.get()
            job["state"], job["started"] = "进行中", time.time()
            rc = 1
            try:
                os.makedirs(os.path.dirname(job["log"]), exist_ok=True)
                with open(job["log"], "a", encoding="utf-8") as fh:
                    rc = 0
                    for step in job["_steps"]:
                        cmd = step() if callable(step) else step
                        if not cmd:
                            continue
                        fh.write("$ %s\n" % " ".join(os.path.basename(c) if i == 1 else c for i, c in enumerate(cmd)))
                        fh.flush()
                        try:
                            rc = subprocess.call(cmd, stdout=fh, stderr=subprocess.STDOUT, env=child_env(), cwd="/tmp")
                        except OSError as e:
                            fh.write(L("跑不起来：%s\n", "Couldn't run: %s\n") % e)
                            rc = 127
                        if rc:
                            break
            except Exception as e:  # noqa: BLE001  这是唯一的后台线程：磁盘满、目录不可写时它一死，队列就永远卡住
                log(L("任务 %s 出错：%r", "Job %s failed: %r") % (job["label"], e))
                rc = rc or 1
            finally:
                job["rc"], job["ended"] = rc, time.time()
                job["state"] = "完成" if rc == 0 else "出错"
                log(L("任务 %s %s：%s", "Job %s %s: %s") % (job["label"], L(job["state"], "done" if rc == 0 else "failed"), rc))


JOBS = Jobs()


def rex_cmd(*args):
    return ["/bin/bash", REX_SH] + list(args)


# ---------------------------------------------------------------- 录音、收件箱、手机、登录

def recording_now():
    st = os.path.join(REX_DIR, ".current")
    if not os.path.exists(st):
        # rex stop 一进来就把它改名成 .stopping，收尾那几秒别让人再开一条
        return {"on": False, "stopping": os.path.exists(st + ".stopping")}
    kv = {}
    with open(st, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            k, _, v = line.rstrip("\n").partition("=")
            kv[k] = v
    try:
        pid = int(kv.get("pid") or 0)
        if pid <= 0:            # 没有 pid 的状态文件是半截的；os.kill(0, 0) 永远成功，不能拿它当「在录」
            raise ValueError
        os.kill(pid, 0)
    except (OSError, ValueError):
        return {"on": False}
    # audiocap 每半秒写一次各路电平（.cap/<路>.level）：录进文件的是什么，页面上的电平条就是什么
    levels = {}
    for tag in ("mic", "sys"):
        try:
            with open(os.path.join(REX_DIR, ".cap", tag + ".level"), encoding="utf-8") as fh:
                levels[tag] = json.load(fh)
        except (OSError, ValueError):
            pass
    return {"on": True, "mode": kv.get("mode", ""), "start": int(kv.get("start", "0") or 0),
            "files": [os.path.basename(x) for x in kv.get("files", "").split("|") if x],   # --split 是「a|b」
            "sys": kv.get("sys", ""), "levels": levels, "now": time.time()}


def run_rex(*args, timeout=60):
    """跑一次 rex.sh。超时不能 SIGKILL：那样它的 trap 不跑，锁、直通设备、半截状态文件全留下。
    开成独立进程组，超时先给整组 TERM 让它收尾，等不到再 KILL。"""
    p = subprocess.Popen(rex_cmd(*args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         env=child_env(), cwd="/tmp", start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        for sig, wait in ((signal.SIGTERM, 8), (signal.SIGKILL, 3)):
            try:
                os.killpg(p.pid, sig)
            except OSError:
                pass
            try:
                p.communicate(timeout=wait)
                break
            except subprocess.TimeoutExpired:
                continue
        return 124, L("等了 %d 秒没回来，已叫停；现在到底在不在录，以 rex status 为准",
                      "No answer after %d seconds, so it was stopped. Run rex status to see whether it's recording") % timeout
    out = re.sub(r"\x1b\[[0-9;]*m", "", out or "")
    return p.returncode, out.strip()


# 同一条录音同一时刻只让一个 rex go 处理：录音台排的、收件箱监视起的、终端里手敲的会撞上（两份 whisper
# 同时转、后完成的盖掉先完成并已校对的稿子）。锁由 rex.sh 的 go_one 按「目录 + 文件名开头的日期时刻」
# 算（关键词改名不影响），放 ~/.cache/rex/locks/<sha1 前 16 位>.go，里面记 PID。这里用同一个算法去看
def go_lock_id(key):
    m = re.match(r"^(\d{4}-\d{2}-\d{2})_(\d{4,6})", key)
    k = "%s_%s" % (m.group(1), m.group(2)) if m else key
    return hashlib.sha1(("%s/%s" % (REX_DIR, k)).encode("utf-8")).hexdigest()[:16]


def go_locked(key):
    d = os.path.join(CACHE, "locks", go_lock_id(key) + ".go")
    try:
        pid = int(open(os.path.join(d, "pid"), encoding="utf-8").read().strip() or 0)
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def inbox_state():
    lock = os.path.join(REX_DIR, ".go.lock")
    # 收件箱是 App 自己在处理（没装监视器时）：进度在它自己的任务日志里，别去读监视器那份旧日志
    busy = os.path.isdir(lock) and not JOBS.running("inbox")
    tail = []
    if busy and os.path.exists(INBOX_LOG):
        with open(INBOX_LOG, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()[-200:]
        start = max((i for i, ln in enumerate(lines) if ln.startswith("▶ ")), default=None)
        if start is not None:
            tail = [re.sub(r"\x1b\[[0-9;]*m", "", ln.rstrip()) for ln in lines[start:] if ln.strip()
                    and not ln.startswith("[0")][-8:]
    try:
        waiting = sorted(f for f in os.listdir(INBOX) if not f.startswith(".") and os.path.isfile(os.path.join(INBOX, f)))
    except OSError:
        waiting = []
    return {"busy": busy, "tail": tail, "waiting": waiting}


_record_lock = threading.Lock()
_watcher = {"t": 0, "on": False}


def watcher_installed():
    if time.time() - _watcher["t"] > 30:
        r = subprocess.run(["launchctl", "print", "gui/%d/%s" % (os.getuid(), INBOX_LABEL)],
                           capture_output=True, text=True)
        _watcher.update(t=time.time(), on=r.returncode == 0)
    return _watcher["on"]


UPLOAD_MAX = 8 << 30      # 8 GB：再大也不是一条录音了
UPLOAD_EXT = {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".opus", ".caf", ".aif", ".aiff", ".wma", ".amr",
              ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".3gp", ".qta"}


def save_upload(name, length, rfile, mtime=None):
    """存进收件箱。mtime 是原文件的修改时间：收件箱按它给录音起名（日期_时刻），不传就成了「上传那一刻」。"""
    name = os.path.basename(name.replace("\\", "/")).strip() or "录音.m4a"
    if os.path.splitext(name)[1].lower() not in UPLOAD_EXT:
        return None
    if length <= 0 or length > UPLOAD_MAX:
        return None
    os.makedirs(INBOX, exist_ok=True)
    tmp = os.path.join(INBOX, ".upload-%s.part" % uuid.uuid4().hex[:8])     # 点开头：收件箱不认，传完才改名
    left = length
    try:
        with open(tmp, "wb") as fh:
            while left > 0:
                buf = rfile.read(min(1 << 20, left))
                if not buf:
                    break
                fh.write(buf)
                left -= len(buf)
        if left:
            return None
        if mtime:
            try:
                os.utime(tmp, (mtime, mtime))
            except OSError:
                pass
    finally:
        if left or not os.path.exists(tmp):
            try:
                os.remove(tmp)      # 没传完、连接断了：别把半截留在收件箱里
            except OSError:
                pass
    dest = os.path.join(INBOX, name)
    stem, ext = os.path.splitext(name)
    i = 2
    while os.path.exists(dest):
        dest = os.path.join(INBOX, "%s-%d%s" % (stem, i, ext))
        i += 1
    os.replace(tmp, dest)
    return dest


def phone_list():
    try:
        files = [os.path.join(VM_DIR, f) for f in os.listdir(VM_DIR)
                 if os.path.splitext(f)[1].lower() in (".m4a", ".qta", ".wav")]
    except PermissionError:
        return {"ok": False, "msg": L("读不了语音备忘录（隐私权限）。从终端跑 rex app 起服务就行——终端有这个权限",
                                      "Can't read Voice Memos (privacy permission). Start the server from a terminal "
                                      "with rex app: the terminal has this permission")}
    except OSError:
        return {"ok": False, "msg": L("找不到语音备忘录的同步目录（iPhone 上要打开 iCloud → 语音备忘录）",
                                      "Can't find the Voice Memos sync folder (on the iPhone, turn on iCloud → Voice Memos)")}
    titles = {}
    db = os.path.join(VM_DIR, "CloudRecordings.db")
    try:
        con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(db), uri=True, timeout=2)
        for path, title, label in con.execute("select ZPATH, ZENCRYPTEDTITLE, ZCUSTOMLABEL from ZCLOUDRECORDING"):
            if path:
                titles[os.path.basename(path)] = title or label or ""
        con.close()
    except sqlite3.Error:
        pass
    files.sort(key=os.path.getmtime, reverse=True)
    files = files[:15]
    durs = durations(files)
    done = {f.split("_phone")[0] for f in os.listdir(REX_DIR) if "_phone" in f}
    out = []
    for p in files:
        b = os.path.basename(p)
        m = re.match(r"^(\d{4})(\d{2})(\d{2}) (\d{2})(\d{2})", b)
        stamp = "%s-%s-%s_%s%s" % m.groups() if m else time.strftime("%Y-%m-%d_%H%M", time.localtime(os.path.getmtime(p)))
        out.append({"path": p, "title": titles.get(b, ""), "when": stamp.replace("_", " ")[:-2] + ":" + stamp[-2:],
                    "stamp": stamp, "duration": round(durs.get(p, 0)), "imported": stamp in done})
    return {"ok": True, "items": out}


_login = {"t": 0, "v": None}


def login_state():
    if time.time() - _login["t"] > 60 or _login["v"] is None:
        try:
            r = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=20,
                               env=claude_cli.env())
            v = json.loads(r.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            v = {"loggedIn": False}
        _login.update(t=time.time(), v={"loggedIn": bool(v.get("loggedIn")), "email": v.get("email", ""),
                                        "plan": v.get("subscriptionType", "")})
    return _login["v"]


def search(q):
    """按逐句的字幕找（有 .srt 就用它），时间准到那一句；对话稿 .txt 一段可能有好几分钟。"""
    q = q.strip()
    if not q:
        return []
    out = []
    low = q.lower()
    for f in sorted(os.listdir(REX_DIR), reverse=True):
        if not f.endswith(".txt") or "." in f[:-4]:
            continue
        key = f[:-4]
        prefix = os.path.join(REX_DIR, key)
        hits = []
        if low in key.lower():
            hits.append({"t": None, "text": L("（文件名）", "(file name)")})
        if os.path.exists(prefix + ".srt"):
            ents = proofread.read_entries(prefix)
            lab = proofread.has_labels(ents)
            lines = [(e["a"], proofread.split_label(e["text"], lab)[1]) for e in ents]
        else:
            with open(os.path.join(REX_DIR, f), encoding="utf-8", errors="replace") as fh:
                lines = [(None, ln.strip()) for ln in fh]
        for t, text in lines:
            if low in text.lower():
                i = text.lower().index(low)
                snip = text[max(0, i - 18):i + len(q) + 36]
                hits.append({"t": t, "text": ("…" if i > 18 else "") + snip + ("…" if i + len(q) + 36 < len(text) else "")})
                if len(hits) >= 5:
                    break
        if hits:
            info = parse_name(key) or {"title": key, "when": ""}
            out.append({"key": key, "title": info["title"], "when": info["when"], "hits": hits})
        if len(out) >= 30:
            break
    return out


# ---------------------------------------------------------------- HTTP

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "rex-app"

    def log_message(self, fmt, *args):      # 安静：只记出错的
        if args and str(args[1])[:1] in "45":
            log("%s %s" % (self.command, fmt % args))

    # ---- 回应
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def deny(self, why):
        self.send_json({"ok": False, "auth": True, "msg": why}, 403)

    def allowed_host(self):
        return self.headers.get("Host", "") in ("127.0.0.1:%d" % PORT, "localhost:%d" % PORT)

    def authed(self):
        c = self.headers.get("Cookie", "")
        # cookie 名带端口：浏览器不按端口隔离 cookie，正式的 8790 和测试的 8791 同名会互相覆盖、无限刷新
        return any(part.strip() == "rex_app_%d=%s" % (PORT, TOKEN) for part in c.split(";"))

    def send_static(self, name, ctype, set_cookie=False):
        path = os.path.join(STATIC, name)
        with open(path, "rb") as fh:
            body = fh.read()
        if EN and name == "index.html":
            # 页面语言在这里定：app.js 按 <html lang> 挑中英文，文件本身不动。<title>录音台</title> 也不能动——
            # rex.sh 的 app_up 靠这个确切的字符串认出端口上是录音台；英文的标题由 app.js 设 document.title
            body = body.replace(b'<html lang="zh-CN">', b'<html lang="en">', 1)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if set_cookie:
            self.send_header("Set-Cookie", "rex_app_%d=%s; Path=/; HttpOnly; SameSite=Strict" % (PORT, TOKEN))
            # 127.0.0.1 上别的端口算同站，不许把这一页嵌进 iframe 诱导点开录
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_media(self, path):
        size = os.path.getsize(path)
        ctype = MEDIA_TYPE.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        start, end = 0, size - 1
        rng = self.headers.get("Range", "")
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    buf = fh.read(min(1 << 16, left))
                    if not buf:
                        break
                    self.wfile.write(buf)
                    left -= len(buf)
        except (BrokenPipeError, ConnectionResetError):
            pass                                  # 拖进度条时浏览器会掐掉旧请求，正常

    # ---- GET
    def do_GET(self):
        if not self.allowed_host():
            return self.deny(L("只接受 127.0.0.1", "Only 127.0.0.1 is accepted"))
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        q1 = lambda k, d="": (qs.get(k) or [d])[0]  # noqa: E731
        if u.path in ("/", "/index.html"):
            return self.send_static("index.html", "text/html; charset=utf-8", set_cookie=True)
        if u.path == "/app.js":
            return self.send_static("app.js", "text/javascript; charset=utf-8")
        if u.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if not self.authed():
            return self.deny(L("口令不对：从 http://127.0.0.1:%d/ 重新打开", "Wrong token: reopen http://127.0.0.1:%d/") % PORT)
        try:
            if u.path == "/api/state":
                return self.send_json({"ok": True, "recordings": scan(), "jobs": JOBS.view(),
                                       "recording": recording_now(), "inbox": inbox_state(),
                                       "watcher": watcher_installed(), "rex_dir": REX_DIR})
            if u.path == "/api/rex":
                d = detail(q1("k"))
                return self.send_json({"ok": True, "rex": d} if d else
                                      {"ok": False, "msg": L("找不到这条录音", "Recording not found")})
            if u.path == "/api/login":
                return self.send_json({"ok": True, "login": login_state()})
            if u.path == "/api/search":
                return self.send_json({"ok": True, "results": search(q1("q"))})
            if u.path == "/api/phone":
                return self.send_json(phone_list())
            if u.path == "/api/export":
                key, fmt = q1("k"), q1("fmt", "docx")
                if not key or "/" in key or fmt not in ("docx", "srt"):
                    return self.send_json({"ok": False, "msg": L("名字不对", "Invalid name")}, 400)
                try:
                    path = rex_export.export(os.path.join(REX_DIR, key), fmt)
                except FileNotFoundError:
                    return self.send_json({"ok": False, "msg": L("这条还没有稿子", "This recording has no transcript yet")}, 404)
                with open(path, "rb") as fh:
                    data = fh.read()
                self.send_response(200)
                self.send_header("Content-Type", rex_export.MIME[fmt])
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", rex_export.disposition(os.path.basename(path)))
                self.end_headers()
                self.wfile.write(data)
                return
            if u.path == "/media":
                files = audio_files(q1("k"))
                i = int(q1("i", "0") or 0)
                if "/" in q1("k") or not files or i >= len(files):
                    return self.send_json({"ok": False, "msg": L("没有音频", "No audio")}, 404)
                return self.send_media(files[i])
        except Exception as e:  # noqa: BLE001  页面上看得到比服务挂掉好
            log(L("出错 %s：%r", "Error %s: %r") % (u.path, e))
            return self.send_json({"ok": False, "msg": L("服务出错：%s", "Server error: %s") % e}, 500)
        self.send_json({"ok": False, "msg": L("没有这个地址", "No such address")}, 404)

    # ---- POST
    def do_POST(self):
        if not self.allowed_host():
            return self.deny(L("只接受 127.0.0.1", "Only 127.0.0.1 is accepted"))
        if not self.authed() or self.headers.get("X-Rex-App") != "1":
            return self.deny(L("口令不对：从 http://127.0.0.1:%d/ 重新打开", "Wrong token: reopen http://127.0.0.1:%d/") % PORT)
        origin = self.headers.get("Origin")
        if origin and origin not in ("http://127.0.0.1:%d" % PORT, "http://localhost:%d" % PORT):
            return self.deny(L("不接受别的网页发来的请求", "Requests from other web pages are not accepted"))
        u = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            if u.path == "/api/upload":
                name = urllib.parse.parse_qs(u.query).get("name", ["录音.m4a"])[0]
                try:
                    mtime = float(self.headers.get("X-Rex-Mtime") or 0) or None
                except ValueError:
                    mtime = None
                dest = save_upload(name, length, self.rfile, mtime)
                if not dest:
                    return self.send_json({"ok": False, "msg": L("没传上：不是音视频文件、太大，或者没传完",
                                                                 "Upload failed: not an audio or video file, too large, "
                                                                 "or incomplete")}, 400)
                if not watcher_installed():      # 没装收件箱监视，就自己排一个
                    JOBS.add("inbox", "", L("处理收件箱", "Process the inbox"), [rex_cmd("go", "--inbox")])
                return self.send_json({"ok": True, "msg": L("放进收件箱了：%s", "Added to the inbox: %s") % os.path.basename(dest)})
            data = json.loads(self.rfile.read(length) or b"{}") if length else {}
            key = data.get("key", "")
            if key and "/" in key:
                return self.send_json({"ok": False, "msg": L("名字不对", "Invalid name")}, 400)
            if u.path == "/api/decide_all":
                if JOBS.busy(key):
                    return self.send_json({"ok": False, "msg": L("这条正在处理，等它跑完再改",
                                                                 "This one is being processed. Wait for it to finish, "
                                                                 "then edit")})
                ok, msg, done, skipped = proofread.decide_all(os.path.join(REX_DIR, key), data.get("action", "accept"))
                return self.send_json({"ok": ok, "msg": msg, "done": done, "skipped": skipped})
            if u.path == "/api/decide":
                if JOBS.busy(key):
                    return self.send_json({"ok": False, "msg": L("这条正在处理，等它跑完再改",
                                                                 "This one is being processed. Wait for it to finish, "
                                                                 "then edit")})
                ok, msg = proofread.decide(os.path.join(REX_DIR, key), int(data.get("rid", 0)), data.get("action", ""))
                return self.send_json({"ok": ok, "msg": msg})
            if u.path == "/api/trash":
                if not key:
                    return self.send_json({"ok": False, "msg": L("没说删哪一条", "No recording given")}, 400)
                ok, msg = trash_recording(key)
                return self.send_json({"ok": ok, "msg": msg})
            if u.path == "/api/go":
                files = audio_files(key)
                if not files:
                    return self.send_json({"ok": False, "msg": L("这条没有音频文件", "This recording has no audio file")})
                if JOBS.busy(key):
                    return self.send_json({"ok": False, "msg": L("已经在处理了（录音台排的，或者收件箱 / 终端那边正在跑）",
                                                                 "Already being processed (queued here, or running from "
                                                                 "the inbox / a terminal)")})
                JOBS.add("go", key, L("处理：%s", "Process: %s") % (parse_name(key) or {"title": key})["title"],
                         [rex_cmd("go", files[0])])
                return self.send_json({"ok": True, "msg": L("排上了", "Queued")})
            if u.path == "/api/chat":
                q = (data.get("q") or "").strip()
                if not q:
                    return self.send_json({"ok": False, "msg": L("问点什么", "Ask something")})
                return self.send_json(chat(key, q))
            if u.path == "/api/record":
                mode = data.get("mode", "")
                if mode not in ("sys", "both", "mic"):
                    return self.send_json({"ok": False, "msg": L("不认识的模式", "Unknown mode")})
                # 连点两下就是两次开录（2026-10-13：两秒内开了两次，第一个成了孤儿录了 53 分钟）。
                # rex.sh 自己也加了锁，这里再挡一道，第二下直接回话
                if not _record_lock.acquire(blocking=False):
                    return self.send_json({"ok": False, "msg": L("正在开始录音，别连点",
                                                                 "Already starting a recording; don't click twice")})
                try:
                    if recording_now().get("on"):
                        return self.send_json({"ok": False, "msg": L("已经在录了，先停掉再开", "Already recording. Stop it first")})
                    # 第一次录音会弹麦克风授权框，rex.sh 等用户点（最多两分钟），所以这里也得等
                    rc, out = run_rex(mode, timeout=150)
                finally:
                    _record_lock.release()
                return self.send_json({"ok": rc == 0, "msg": out[-600:]})
            if u.path == "/api/stop":
                rc, out = run_rex("stop", timeout=120)
                return self.send_json({"ok": rc == 0, "msg": out[-1500:]})
            if u.path == "/api/phone/import":
                path = data.get("path", "")
                if not path.startswith(VM_DIR + "/") or not os.path.exists(path):
                    return self.send_json({"ok": False, "msg": L("找不到这条语音备忘录", "Voice memo not found")})
                stamp = data.get("stamp", "")

                def go_step():
                    hit = sorted(f for f in os.listdir(REX_DIR) if f.startswith(stamp + "_phone")
                                 and os.path.splitext(f)[1].lower() in AUDIO_EXT)
                    return rex_cmd("go", os.path.join(REX_DIR, hit[0])) if hit else None
                JOBS.add("phone", stamp + "_phone", L("手机录音 %s", "Phone recording %s") % stamp,
                         [rex_cmd("phone", path), go_step])
                return self.send_json({"ok": True, "msg": L("排上了：先取出来转写，再校对和分析",
                                                            "Queued: import and transcribe it, then proofread and "
                                                            "analyze")})
            if u.path == "/api/reveal":
                files = audio_files(key) or [os.path.join(REX_DIR, key + ".txt")]
                subprocess.run(["open", "-R", files[0]])
                return self.send_json({"ok": True})
        except Exception as e:  # noqa: BLE001
            log(L("出错 %s：%r", "Error %s: %r") % (u.path, e))
            return self.send_json({"ok": False, "msg": L("服务出错：%s", "Server error: %s") % e}, 500)
        self.send_json({"ok": False, "msg": L("没有这个地址", "No such address")}, 404)


def main():
    os.makedirs(CACHE, exist_ok=True)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.daemon_threads = True
    log(L("录音台：http://127.0.0.1:%d/   录音在 %s", "Recording Desk: http://127.0.0.1:%d/   recordings in %s") % (PORT, REX_DIR))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
