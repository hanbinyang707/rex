#!/usr/bin/env python3
"""从一个播客单集网页里取出音频地址，下载下来，交给 rex 的转写流水线。

被 rex.sh 的 `rex url` 调用：

    rex url https://www.xiaoyuzhoufm.com/episode/670a025626fe2954b1a092f3

单独用：

    python3 tools/podcast_url.py <链接> --dir ~/Recordings --print-only

## 为什么不用现成的下载器

因为不需要。**小宇宙这类页面自己就把音频地址摆在 `og:audio` 里**——那是 Open
Graph 的标准标签，播客页面公开它就是为了让别的播放器能嵌。实测
`https://media.xyzcdn.net/….m4a`：`content-type: audio/mp4`、
`accept-ranges: bytes`、**没有鉴权、没有签名、没有防盗链**。一条 curl 就下来了。

装一个几千行的第三方下载器来做这件事，等于为了拿一个 `<meta>` 标签引入一个依赖，
还得跟着它一起腐烂。所以这里只有一百多行标准库。

## 取地址的四道，按可靠性排

1. **URL 本身就是音频文件**（`.m4a` / `.mp3` / …）——直接下，不去解析任何网页
2. **`og:audio` / `twitter:player:stream`**——标准标签，最可靠
3. **`__NEXT_DATA__` 里的 `enclosure.url`**——小宇宙是 Next.js 站，这里还能顺便
   拿到标题、播客名、发布日期、时长，用来起个像样的文件名
4. **兜底**：整页正则捞 `.m4a`/`.mp3` 链接，取第一个

**四道都没命中就明说「这个页面里找不到音频地址」并打印试过什么**，
不静默失败——静默失败在这个工具链里是头号敌人。

## 命名

`2024-10-14_0000_web_投资ABC-E33财富规划…`。日期用**单集的发布日期**，不是下载
日期——`rex find` 的列表按文件名里的日期排，按下载日期排会让一堆老节目挤在今天。

名字里已经带了真标题，所以**不再走关键词自动命名**（那一层是给没有标题的口述稿
用的）。`rex.sh` 的判据是「文件名还是不是本工具生成的那个纯时间戳格式」，
带了标题就自然不是，不用额外开关。

## 边界

这是给**公开发布的播客**用的，和任何播客客户端做的事一样：拿公开的 RSS/网页里
公开的音频地址，下到本地自己听、自己转写。付费专栏、会员专享、需要登录才能听的
内容不在此列——那些页面里本来也没有 `og:audio`，第 4 道兜底如果捞到了什么，
自己掂量一下再用。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
AUDIO_EXT = (".m4a", ".mp3", ".aac", ".wav", ".ogg", ".opus", ".flac", ".m4b")
AUDIO_RE = re.compile(r'https?://[^\s"\'<>]+?\.(?:m4a|mp3|aac|m4b)(?:\?[^\s"\'<>]*)?',
                      re.I)


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


def meta(html, prop):
    for pat in (r'<meta[^>]+property=["\']%s["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']%s["\']',
                r'<meta[^>]+name=["\']%s["\'][^>]+content=["\']([^"\']+)'):
        m = re.search(pat % re.escape(prop), html, re.I)
        if m:
            return m.group(1)
    return None


def dig(o, key, depth=0):
    """在嵌套的 JSON 里找第一个叫 key 的值。页面结构会变，写死路径活不过一次改版。"""
    if depth > 10:
        return None
    if isinstance(o, dict):
        if key in o:
            return o[key]
        for v in o.values():
            r = dig(v, key, depth + 1)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = dig(v, key, depth + 1)
            if r is not None:
                return r
    return None


def next_data(html):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except ValueError:
        return {}


def looks_audio(url):
    return os.path.splitext(url.split("?")[0])[1].lower() in AUDIO_EXT


def resolve(url):
    """返回 (音频地址, 元信息 dict, 走了哪一道)。找不到给 (None, {}, 试过的清单)。"""
    if looks_audio(url):
        return url, {}, "链接本身就是音频文件"

    raw, ctype = fetch(url)
    if ctype.split(";")[0].strip().startswith("audio/"):
        return url, {}, "链接本身就是音频（按 Content-Type 判）"
    html = raw.decode("utf-8", "replace")

    info = {}
    d = next_data(html)
    if d:
        ep = dig(d, "episode") or {}
        if isinstance(ep, dict):
            info["title"] = ep.get("title")
            info["date"] = ep.get("pubDate")
            info["seconds"] = ep.get("duration")
            pod = ep.get("podcast")
            if isinstance(pod, dict):
                info["podcast"] = pod.get("title")
            enc = ep.get("enclosure")
            if isinstance(enc, dict) and enc.get("url"):
                info["_enclosure"] = enc["url"]

    tried = []
    for label, cand in (
            ("og:audio", meta(html, "og:audio")),
            ("og:audio:url", meta(html, "og:audio:url")),
            ("twitter:player:stream", meta(html, "twitter:player:stream")),
            ("__NEXT_DATA__ enclosure", info.pop("_enclosure", None))):
        tried.append(label)
        if cand:
            info.setdefault("title", meta(html, "og:title"))
            return cand, info, label

    tried.append("全页正则捞音频链接")
    m = AUDIO_RE.search(html)
    if m:
        info.setdefault("title", meta(html, "og:title"))
        return m.group(0), info, "全页正则（兜底，不一定是正片）"

    return None, info, tried


def safe(s, n=48):
    """标题 → 文件名。全角标点也要清掉：`：，、《》` 在文件名里合法，但一进 shell
    就得处处加引号，而这些文件是要被 `rex text`、`rex find` 反复引用的。"""
    s = re.sub(r"\s+", " ", (s or "")).strip()
    s = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "", s)
    s = re.sub(r"[：，。、；！？（）《》「」【】·…—“”‘’]+", "-", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s[:n].strip("-.")


def stamp(iso):
    """发布日期 → 文件名前缀。取不到就用现在。"""
    if iso:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})", str(iso))
        if m:
            return "%s-%s-%s_%s%s" % m.groups()
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(iso))
        if m:
            return "%s-%s-%s_0000" % m.groups()
    return time.strftime("%Y-%m-%d_%H%M")


def human(n):
    for u in ("B", "K", "M", "G"):
        if n < 1024 or u == "G":
            return "%dB" % n if u == "B" else "%.1f%s" % (n, u)
        n /= 1024.0


def download(url, dst, referer, tries=5):
    """下载，**并且验证下全了**。支持断点续传。

    这条是踩出来的，而且踩得很难看：第一版拿到 39432614 字节里的 1048576 就退出了
    （正好 4 个读块），然后**照样打了一个 ✓**。`urlopen` 的 `read()` 在连接被对端
    提前关掉时返回空字节串，不抛异常——和这个工具链里反复出现的那类静默失败
    一模一样，只不过这次是我自己写的。

    所以：
      1. `Content-Length` 已知时，读完必须**逐字节对得上**，对不上就是没下完
      2. 没下完就用 `Range` 从断点续，服务端 `accept-ranges: bytes`（实测支持）
      3. 重试 tries 次仍然差字节 → **报错并删掉半截文件**，绝不留一个看着正常的残片
    """
    tmp = dst + ".part"
    got = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    total = 0
    tty = sys.stdout.isatty()
    last = 0.0

    for attempt in range(tries):
        headers = {"User-Agent": UA, "Referer": referer}
        if got:
            headers["Range"] = "bytes=%d-" % got
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                clen = int(r.headers.get("Content-Length") or 0)
                if r.status == 206:
                    total = got + clen
                elif got and r.status == 200:
                    got, total = 0, clen      # 服务端不认 Range，从头来
                    if os.path.exists(tmp):
                        os.remove(tmp)
                else:
                    total = clen
                with open(tmp, "ab" if got else "wb") as fh:
                    while True:
                        chunk = r.read(1 << 18)
                        if not chunk:
                            break
                        fh.write(chunk)
                        got += len(chunk)
                        now = time.time()
                        if tty and now - last > 0.2:
                            last = now
                            sys.stdout.write("\r  下载 %s%s" % (
                                human(got),
                                " / %s  %4.1f%%" % (human(total), 100.0 * got / total)
                                if total else ""))
                            sys.stdout.flush()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            if attempt == tries - 1:
                raise
            if tty:
                sys.stdout.write("\r" + " " * 46 + "\r")
            print("  连接断了（%s），从 %s 处续传…" % (e, human(got)))
            time.sleep(1.5 * (attempt + 1))
            continue

        if not total or got >= total:
            break
        if attempt < tries - 1:
            if tty:
                sys.stdout.write("\r" + " " * 46 + "\r")
            print("  只下到 %s / %s，续传…" % (human(got), human(total)))
            time.sleep(1.0)

    if tty:
        sys.stdout.write("\r" + " " * 46 + "\r")
    if total and got != total:
        os.remove(tmp)
        raise OSError("下不全：%s / %s，重试 %d 次仍然差字节，已删掉半截文件"
                      % (human(got), human(total), tries))
    # 下全了才改名：中途断掉时留下的是 .part，不会被当成一个完好的录音
    os.replace(tmp, dst)
    return got


def main():
    ap = argparse.ArgumentParser(description="下载播客单集音频")
    ap.add_argument("url")
    ap.add_argument("--dir", default=os.path.expanduser("~/Recordings"))
    ap.add_argument("--print-only", action="store_true", help="只打印音频地址，不下载")
    a = ap.parse_args()

    try:
        audio, info, how = resolve(a.url)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print("打不开这个链接：%s" % e)
        return 1

    if not audio:
        print("这个页面里找不到音频地址。试过：")
        for t in (how if isinstance(how, list) else [str(how)]):
            print("  · %s" % t)
        print("\n付费/会员内容通常就是这样——页面里本来就没有公开的音频地址。")
        return 1

    if a.print_only:
        print(audio)
        return 0

    title = info.get("title") or ""
    pod = info.get("podcast") or ""
    print("  来源：%s" % how)
    if pod or title:
        print("  节目：%s%s" % (pod + " · " if pod else "", title))
    if info.get("seconds"):
        s = int(info["seconds"])
        print("  时长：%d 分 %02d 秒" % (s // 60, s % 60))

    ext = os.path.splitext(audio.split("?")[0])[1].lower() or ".m4a"
    name = "_".join(x for x in (stamp(info.get("date")), "web",
                                safe("-".join(x for x in (pod, title) if x))) if x)
    os.makedirs(a.dir, exist_ok=True)
    dst = os.path.join(a.dir, name + ext)
    if os.path.exists(dst):
        print("  已经下过了：%s" % dst)
        print("PATH %s" % dst)
        return 0

    print("  音频：%s" % audio)
    try:
        n = download(audio, dst, a.url)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print("  下载失败：%s" % e)
        for junk in (dst + ".part",):
            if os.path.exists(junk):
                os.remove(junk)
        return 1

    print("  ✓ %s  %s" % (dst, human(n)))
    # 这一行给 rex.sh 读，用来接着跑转写
    print("PATH %s" % dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
