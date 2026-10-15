#!/usr/bin/env python3
"""用手机录：手机扫码打开一页，录音一边录一边传回这台 Mac，放进收件箱走 `rex go`。
一般用 `rex link` 起（它顺便开 tailscale serve、打二维码）。

    python3 tools/rex_link.py               # 端口默认 8791（REX_LINK_PORT）
    python3 tools/rex_link.py --token       # 打印口令（rex link 拼地址用）
    python3 tools/rex_link.py --new-token   # 换一个口令，旧二维码作废

## 为什么要 https，为什么走 Tailscale

手机浏览器只在 https 页面里给麦克风（getUserMedia 要「安全上下文」）。`tailscale serve` 给这台 Mac
一个只在你自己 tailnet 里能访问、带正式证书的 https 地址，转到这里的 127.0.0.1——不用自签证书，
也不对公网开放（对公网的是 Funnel，这里不用）。

## 安全：和录音台分开，只给最小的权限

录音台（rex_app.py）能改稿子、开始录音、把稿子发给 Claude，它只认 127.0.0.1。这个服务是要让手机
连进来的，所以单独一个进程，能做的事只有四件：收一段新录音放进收件箱、收一个文件放进收件箱、
列最近几份稿子、下载稿子（Word / 字幕）。不能删、不能改、不能开录、不能发给 Claude。
- 只听 127.0.0.1；外面只能经 tailscale serve 进来（Host 头必须是 127.0.0.1 / localhost / *.ts.net）
- 每个请求都要口令（二维码里的 ?t=…，存在 ~/.config/rex/link-token，权限 600）。`rex link new-token`
  换了口令，开着的服务下一个请求就认新的，旧二维码当场作废
- 会写东西的请求（POST）口令必须放在 X-Rex-Token 头里，并核对 Origin 和 Host 一致
- 文件名由这里起，不用手机传来的路径；单块 ≤ 32 MB，一条 ≤ 4 GB

## 边录边传

页面每 5 秒交一块，这里按顺序追加到 ~/.cache/rex/link/<id>.part。手机锁屏、网断了，已经传到的不丢；
录完 /api/end 才改名进收件箱（收件箱不认 .part，半截不会被处理）。
没收尾的（页面关了、手机没电、这边重启了）：半小时没新块，或者服务重启时发现的，照样进收件箱，
名字带「未收尾」——不留在缓存里没人管。
"""
import argparse
import errno
import hmac
import http.server
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import rex_export  # noqa: E402
from i18n import L, EN  # noqa: E402

PORT = int(os.environ.get("REX_LINK_PORT") or 8791)
REX_DIR = os.environ.get("REX_DIR") or os.path.expanduser("~/Recordings")
INBOX = os.environ.get("REX_INBOX") or os.path.join(REX_DIR, "收件箱")
INBOX_LABEL = os.environ.get("REX_INBOX_LABEL") or "local.rex.inbox"
CONF = os.path.expanduser("~/.config/rex")
TOKEN_FILE = os.path.join(CONF, "link-token")
PARTS = os.path.expanduser("~/.cache/rex/link")
LOG = os.environ.get("REX_LINK_LOG") or os.path.expanduser("~/Library/Logs/rex-link.log")
REX_SH = os.path.join(TOOLS, "rex.sh")
PAGE = os.path.join(TOOLS, "rex_link", "index.html")

MAX_CHUNK = 32 << 20
MAX_TOTAL = 4 << 30
# 手机浏览器录出来的格式：Safari 是 audio/mp4（AAC），安卓 Chrome 是 webm/opus
REC_EXT = {"m4a": ".m4a", "mp4": ".m4a", "webm": ".webm", "ogg": ".ogg"}
# 和 rex.sh 的 MEDIA_GLOB 一样：收件箱不认的格式，传进去也只会被挪进「转不了」
UPLOAD_EXT = {".m4a", ".mp3", ".wav", ".qta", ".mov", ".mp4", ".m4v", ".aac", ".caf", ".aiff", ".aif",
              ".flac", ".ogg", ".opus", ".webm", ".mkv", ".m4b"}
STEM = re.compile(r"^\d{4}-\d{2}-\d{2}_[^/\\]+$")

SESSIONS = {}
ENDED = {}                       # 收好了的：id → 收件箱里的名字。手机没收到回话、又来收尾一次，照样说好
UPLOADING = set()                # 正在传的文件：收拾残留的时候别当成半截删掉
_lock = threading.Lock()
_inbox_lock = threading.Lock()   # 挑名字和改名一起做：同一分钟收完两条，不然会挑中同一个名字、后一条盖掉前一条
TOKEN = ""
_token_stamp = None
IDLE = 1800                      # 一次录音多久没新块算放弃了（秒）


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S ") + msg, flush=True)


def token(new=False):
    """口令存在 ~/.config/rex/link-token，重启服务二维码照样能用；--new-token 才换。"""
    os.makedirs(CONF, exist_ok=True)
    if not new and os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, encoding="utf-8") as fh:
            t = fh.read().strip()
        if len(t) >= 20:
            return t
    t = secrets.token_urlsafe(18)
    tmp = TOKEN_FILE + ".tmp"                 # 写好再换上：开着的服务随时会来读
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(t + "\n")
    os.replace(tmp, TOKEN_FILE)
    return t


def live_token():
    """服务开着的时候 rex link new-token 换了口令：下一个请求就认新的，旧二维码当场作废，不用重起服务。"""
    global TOKEN, _token_stamp
    try:
        st = os.stat(TOKEN_FILE)
    except OSError:
        return TOKEN
    stamp = (st.st_ino, st.st_mtime_ns, st.st_size)
    if stamp != _token_stamp:
        try:
            with open(TOKEN_FILE, encoding="utf-8") as fh:
                t = fh.read().strip()
        except OSError:
            return TOKEN
        if len(t) >= 20:
            TOKEN, _token_stamp = t, stamp
    return TOKEN


def watcher_installed():
    try:
        return subprocess.run(["launchctl", "print", "gui/%d/%s" % (os.getuid(), INBOX_LABEL)],
                              capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def kick():
    """收件箱监视没装时，自己起一次 rex go --inbox（rex go 有锁，和监视撞上也不会重复转）。"""
    if watcher_installed():
        return
    try:
        with open(LOG, "a") as out:
            subprocess.Popen([REX_SH, "go", "--inbox"], stdout=out, stderr=out, stdin=subprocess.DEVNULL,
                             start_new_session=True)
    except OSError as e:
        log(L("起不了 rex go：%r", "Could not start rex go: %r") % e)


def rec_name(label, t0, ext):
    """手机录的那条在收件箱里叫什么。收件箱按修改时间给录音起名（日期_时刻_drop-这个名字），这里只要分得开。"""
    return "%s-%s%s" % (label, time.strftime("%H%M", time.localtime(t0)), ext)


def into_inbox(tmp, name, t0):
    """把传完的文件改名进收件箱，重名的加 -2、-3。修改时间设成开录（或原文件）的那一刻：收件箱按它给录音起名。"""
    os.makedirs(INBOX, exist_ok=True)
    os.utime(tmp, (t0, t0))
    stem, ext = os.path.splitext(name)
    with _inbox_lock:
        dest, i = os.path.join(INBOX, name), 2
        while os.path.exists(dest):
            dest = os.path.join(INBOX, "%s-%d%s" % (stem, i, ext))
            i += 1
        try:
            os.replace(tmp, dest)
        except OSError as e:
            if e.errno != errno.EXDEV:
                raise
            # 录音文件夹在另一块盘上（REX_DIR 指到了外置硬盘），改名跨不了盘：先拷成收件箱里一个点开头的
            # 名字（收件箱不认），拷完再改名，收件箱就不会捡到拷了一半的文件
            staged = os.path.join(INBOX, ".link-%s.part" % secrets.token_hex(4))
            try:
                shutil.copyfile(tmp, staged)
                os.utime(staged, (t0, t0))
                os.replace(staged, dest)
            except OSError:
                if os.path.exists(staged):
                    os.remove(staged)          # 拷了一半的副本；原件还在缓存里，下一轮再收
                raise
            os.remove(tmp)
    return dest


def t0_of(sid):
    try:
        return time.mktime(time.strptime(sid[:15], "%Y%m%d-%H%M%S"))
    except ValueError:
        return time.time()


def salvage(idle=None, grace=120):
    """没收尾的录音也进收件箱：内存里半小时没动静的，和不在内存里的孤儿 .part（服务重启过）。
    传了一半的文件（up-*.part，服务重启前没传完的）是手机上那份的拷贝，原件还在手机上，删掉。"""
    idle = IDLE if idle is None else idle
    now = time.time()
    with _lock:
        stale = [sid for sid, s in SESSIONS.items() if now - s["last"] > idle]
        gone = [(sid, SESSIONS.pop(sid)) for sid in stale]
        busy = {s["path"] for s in SESSIONS.values()} | UPLOADING
    if os.path.isdir(PARTS):
        known = {s["path"] for _, s in gone}
        for f in os.listdir(PARTS):
            p = os.path.join(PARTS, f)
            try:
                if p in busy or p in known or not f.endswith(".part") or now - os.path.getmtime(p) < grace:
                    continue
            except OSError:                    # 刚好收完、改名走了
                continue
            if f.startswith("up-"):
                os.remove(p)
                log(L("丢掉传了一半的文件：%s", "Discarded a half-uploaded file: %s") % f)
                continue
            sid, _, ext = f[:-5].partition(".")
            gone.append((sid, {"path": p, "size": os.path.getsize(p), "t0": t0_of(sid),
                               "ext": "." + (ext or "m4a")}))
    moved = []
    # 英文别叫 phone-unfinished：收件箱把名字压到 15 个字符以内，会只剩 phone，看不出没收尾
    label = L("手机录音-未收尾", "phone-partial")
    for sid, s in gone:
        try:
            if not s["size"]:
                os.remove(s["path"])
                continue
            dest = into_inbox(s["path"], rec_name(label, s["t0"], s["ext"]), s["t0"])
        except OSError as e:                   # 这一条没收成：文件还在缓存里，下一轮当孤儿再收
            log(L("收拾没收尾的录音出错：%r", "Error tidying unfinished recordings: %r") % e)
            continue
        log(L("没收尾的手机录音放进收件箱了：%s", "Unfinished phone recording added to the inbox: %s") % dest)
        moved.append(dest)
    if moved:
        kick()
    return moved


def sweeper():
    while True:
        time.sleep(300)
        try:
            salvage()
        except Exception as e:  # noqa: BLE001
            log(L("收拾没收尾的录音出错：%r", "Error tidying unfinished recordings: %r") % e)


def recent(n=6):
    """最近几份稿子（按修改时间），给手机那页看。"""
    if not os.path.isdir(REX_DIR):
        return []
    found = []
    for f in os.listdir(REX_DIR):
        if not f.endswith(".txt") or f.endswith(".whisper.txt") or not STEM.match(f[:-4]):
            continue
        p = os.path.join(REX_DIR, f)
        found.append((os.path.getmtime(p), f[:-4], p))
    found.sort(reverse=True)
    res = []
    for _, key, p in found[:n]:
        title, when = rex_export.title_of(key)
        with open(p, "rb") as fh:
            text = fh.read(60000).decode("utf-8", "replace")
        res.append({"key": key, "title": title, "when": when, "text": text,
                    "srt": os.path.exists(os.path.join(REX_DIR, key + ".srt"))})
    return res


STR = {
    "title": L("用手机录", "Record from your phone"),
    "rec": L("开始录音", "Start recording"),
    "stop": L("停止", "Stop"),
    "keep": L("录的时候别锁屏、别切走这一页（手机浏览器在后台会停掉麦克风）。每 5 秒传一次，断网了已经传到的不会丢。",
              "Keep the screen on and stay on this page while recording (phone browsers stop the microphone in the "
              "background). It uploads every 5 seconds, so anything already sent is kept if the network drops."),
    "nohttps": L("这一页要用 https 打开才能用麦克风：扫 rex link 打出来的二维码。下面传文件照样能用。",
                 "This page needs https to use the microphone: scan the QR code that rex link prints. Uploading a "
                 "file below still works."),
    "upload": L("或者传一个文件（语音备忘录、别的录音 App 导出的）",
                "Or upload a file (a Voice Memo, or an export from another recorder)"),
    "recent": L("最近的稿子", "Recent transcripts"),
    "none": L("还没有稿子。录完一般几分钟后出现在这里。",
              "No transcripts yet. They usually appear here a few minutes after recording."),
    "word": "Word",
    "subs": L("字幕", "Subtitles"),
    "sent": L("传好了，放进收件箱了：", "Uploaded and added to the inbox: "),
    "fail": L("没传上：", "Upload failed: "),
    "wait": L("还在传最后几块……", "Sending the last chunks…"),
    "denied": L("拿不到麦克风：", "Could not get the microphone: "),
    "refresh": L("刷新", "Refresh"),
    "uploading": L("正在传……", "Uploading…"),
    "lost": L("这次录音断太久，已经按「未收尾」放进收件箱了。再录请重新开始。",
              "This recording was interrupted too long and has been added to the inbox as unfinished. Start a new one to continue."),
}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "rex-link"

    def log_message(self, fmt, *args):
        pass

    # ---- 守门
    def host_ok(self):
        h = (self.headers.get("Host") or "").lower()
        h = h[1:].partition("]")[0] if h.startswith("[") else h.rsplit(":", 1)[0]
        return h in ("127.0.0.1", "localhost") or h.endswith(".ts.net")

    def token_ok(self, allow_query=True):
        got = self.headers.get("X-Rex-Token") or ""
        if not got and allow_query:
            got = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("t") or [""])[0]
        tok = live_token()
        return bool(got) and bool(tok) and hmac.compare_digest(got.encode(), tok.encode())

    def origin_ok(self):
        o = self.headers.get("Origin")
        if not o:
            return True
        return urllib.parse.urlparse(o).netloc.lower() == (self.headers.get("Host") or "").lower()

    def send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def deny(self, msg):
        self.send(403, {"ok": False, "msg": msg})

    # ---- GET
    def do_GET(self):
        if not self.host_ok():
            return self.deny(L("地址不对", "Wrong host"))
        u = urllib.parse.urlparse(self.path)
        if u.path == "/healthz":                 # rex link 靠 service 这个字认出端口上是它，不是别的服务
            return self.send(200, {"ok": True, "service": "rex-link"})
        if not self.token_ok():
            return self.deny(L("口令不对：重新扫 rex link 的二维码", "Wrong token: scan the QR code from rex link again"))
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                with open(PAGE, encoding="utf-8") as fh:
                    page = fh.read()
                for k, v in STR.items():
                    page = page.replace("{{%s}}" % k, v)
                page = page.replace("{{lang}}", "en" if EN else "zh-CN")
                page = page.replace("{{T}}", json.dumps(STR, ensure_ascii=False).replace("</", "<\\/"))
                return self.send(200, page, "text/html; charset=utf-8")
            if u.path == "/api/recent":
                return self.send(200, {"ok": True, "items": recent()})
            if u.path == "/api/file":
                key = (q.get("k") or [""])[0]
                fmt = (q.get("fmt") or ["docx"])[0]
                if not STEM.match(key) or fmt not in ("docx", "srt"):
                    return self.send(400, {"ok": False, "msg": L("名字不对", "Invalid name")})
                try:
                    path = rex_export.export(os.path.join(REX_DIR, key), fmt)
                except FileNotFoundError:
                    return self.send(404, {"ok": False, "msg": L("没有这份稿子", "No such transcript")})
                with open(path, "rb") as fh:
                    data = fh.read()
                return self.send(200, data, rex_export.MIME[fmt],
                                 {"Content-Disposition": rex_export.disposition(os.path.basename(path))})
        except Exception as e:  # noqa: BLE001
            log(L("出错 %s：%r", "Error %s: %r") % (u.path, e))
            return self.send(500, {"ok": False, "msg": str(e)})
        self.send(404, {"ok": False, "msg": L("没有这个地址", "No such address")})

    # ---- POST
    def do_POST(self):
        if not self.host_ok():
            return self.deny(L("地址不对", "Wrong host"))
        if not self.token_ok(allow_query=False) or not self.origin_ok():
            return self.deny(L("口令不对：重新扫 rex link 的二维码", "Wrong token: scan the QR code from rex link again"))
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        q1 = lambda k, d="": (q.get(k) or [d])[0]  # noqa: E731
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        no_such = {"ok": False, "msg": L("没有这次录音", "No such recording")}
        try:
            if u.path == "/api/begin":
                ext = REC_EXT.get(q1("ext").lower())
                if not ext:
                    return self.send(400, {"ok": False, "msg": L("不认识的格式", "Unknown format")})
                os.makedirs(PARTS, exist_ok=True)
                sid = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
                path = os.path.join(PARTS, sid + ext + ".part")      # 格式写进名字：重启后也知道它是什么
                now = time.time()
                with _lock:
                    SESSIONS[sid] = {"path": path, "seq": 0, "size": 0, "ext": ext, "t0": now, "last": now}
                open(path, "wb").close()
                log(L("开始收手机录音 %s", "Receiving a phone recording %s") % sid)
                return self.send(200, {"ok": True, "id": sid})

            if u.path == "/api/chunk":
                sid = q1("id")
                try:
                    seq = int(q1("seq", "-1"))
                except ValueError:
                    seq = -1
                with _lock:
                    s = SESSIONS.get(sid)
                if not s:
                    return self.send(404, no_such)
                if length <= 0 or length > MAX_CHUNK or s["size"] + length > MAX_TOTAL:
                    return self.send(413, {"ok": False, "msg": L("太大了", "Too large")})
                body = self.rfile.read(length)
                with _lock:
                    if SESSIONS.get(sid) is not s:   # 读这一块的时候，它被当成没收尾的收走了（或者刚收尾）
                        res = (404, no_such)
                    elif seq == s["seq"] - 1:        # 手机没收到回话、又传了一遍：已经写过了，直接说好
                        res = (200, {"ok": True, "seq": seq})
                    elif seq != s["seq"] or len(body) != length:
                        res = (409, {"ok": False, "want": s["seq"],
                                     "msg": L("顺序不对：等第 %d 块，来的是第 %d 块",
                                              "Out of order: expected chunk %d, got %d") % (s["seq"], seq)})
                    else:
                        with open(s["path"], "ab") as fh:
                            fh.write(body)
                        s["seq"] += 1
                        s["size"] += length
                        s["last"] = time.time()
                        res = (200, {"ok": True, "seq": seq})
                return self.send(*res)

            if u.path == "/api/end":
                sid = q1("id")
                with _lock:
                    s = SESSIONS.pop(sid, None)
                    done = ENDED.get(sid)
                if not s:
                    if done:                         # 收过尾了，只是回话没到手机：再说一次
                        return self.send(200, {"ok": True, "name": done})
                    return self.send(404, no_such)
                if s["size"] == 0:
                    os.remove(s["path"])
                    return self.send(400, {"ok": False, "msg": L("什么都没录到", "Nothing was recorded")})
                dest = into_inbox(s["path"], rec_name(L("手机录音", "phone"), s["t0"], s["ext"]), s["t0"])
                with _lock:
                    ENDED[sid] = os.path.basename(dest)
                    while len(ENDED) > 50:
                        ENDED.pop(next(iter(ENDED)))
                log(L("手机录音收完：%s（%.1f MB）", "Phone recording received: %s (%.1f MB)")
                    % (dest, s["size"] / 1e6))
                kick()
                return self.send(200, {"ok": True, "name": os.path.basename(dest)})

            if u.path == "/api/upload":
                # 用原名进收件箱，和拖进收件箱、录音台上传一样（收件箱自己会把名字压短）。去掉控制字符和
                # 开头的点：点开头的文件收件箱不认
                name = re.sub(r"[\x00-\x1f\x7f]", "", os.path.basename(q1("name").replace("\\", "/"))).strip().lstrip(".")
                stem, ext = os.path.splitext(name)
                ext = ext.lower()
                if ext not in UPLOAD_EXT or length <= 0 or length > MAX_TOTAL:
                    return self.send(400, {"ok": False, "msg": L("不是音视频文件，或者太大",
                                                                 "Not an audio or video file, or too large")})
                name = stem[:120] + ext
                try:
                    mtime = float(self.headers.get("X-Rex-Mtime") or 0)
                except ValueError:
                    mtime = 0
                if not 946684800 < mtime < time.time() + 86400:     # 没给、或者明显不对（2000 年以前、将来）：用现在
                    mtime = time.time()
                os.makedirs(PARTS, exist_ok=True)
                tmp = os.path.join(PARTS, "up-%s.part" % secrets.token_hex(4))
                with _lock:
                    UPLOADING.add(tmp)
                try:
                    left = length
                    with open(tmp, "wb") as fh:
                        while left > 0:
                            buf = self.rfile.read(min(1 << 20, left))
                            if not buf:
                                break
                            fh.write(buf)
                            left -= len(buf)
                    if left:
                        os.remove(tmp)
                        return self.send(400, {"ok": False, "msg": L("没传完", "Incomplete upload")})
                    dest = into_inbox(tmp, name, mtime)
                finally:
                    with _lock:
                        UPLOADING.discard(tmp)
                log(L("手机传来文件：%s", "File from phone: %s") % dest)
                kick()
                return self.send(200, {"ok": True, "name": os.path.basename(dest)})
        except Exception as e:  # noqa: BLE001
            log(L("出错 %s：%r", "Error %s: %r") % (u.path, e))
            return self.send(500, {"ok": False, "msg": str(e)})
        self.send(404, {"ok": False, "msg": L("没有这个地址", "No such address")})


def serve(port=None):
    global TOKEN
    TOKEN = token()
    live_token()
    salvage(idle=0)                      # 上次没收尾的先收起来
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT if port is None else port), Handler)
    srv.daemon_threads = True
    return srv


def main():
    ap = argparse.ArgumentParser(description=L("用手机录：手机扫码录音，传回这台 Mac", "Record from your phone"))
    ap.add_argument("--token", action="store_true", help=L("打印口令", "Print the token"))
    ap.add_argument("--new-token", action="store_true", help=L("换一个口令，旧二维码作废", "Make a new token; old QR codes stop working"))
    a = ap.parse_args()
    if a.token or a.new_token:
        print(token(new=a.new_token))
        return 0
    srv = serve()
    threading.Thread(target=sweeper, daemon=True).start()
    log(L("手机录音服务：http://127.0.0.1:%d/（外面经 tailscale serve 进来）",
          "Phone recording service: http://127.0.0.1:%d/ (reached from outside through tailscale serve)") % PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
