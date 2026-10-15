"""用手机录（rex_link.py）和导出（rex_export.py）。不碰真的家目录、不起 tailscale、不跑 rex go。

    python3 -m unittest discover -s tests
"""
import errno
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

HOME = os.environ["HOME"] = tempfile.mkdtemp()
os.environ["REX_LANG"] = "zh"
REXDIR = tempfile.mkdtemp()
os.environ["REX_DIR"] = REXDIR
os.environ["REX_LINK_LOG"] = os.path.join(HOME, "link.log")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import rex_export  # noqa: E402
import rex_link  # noqa: E402

rex_link.kick = lambda: None          # 不真的起 rex go


def tearDownModule():
    shutil.rmtree(REXDIR, ignore_errors=True)
    shutil.rmtree(HOME, ignore_errors=True)


class Link(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = rex_link.serve(port=0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.tok = rex_link.TOKEN

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": host or "127.0.0.1:%d" % self.port}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data

    def post(self, path, body=b"", **kw):
        h = {"X-Rex-Token": self.tok}
        h.update(kw.pop("headers", {}))
        return self.req("POST", path, body, h, **kw)

    def slow_post(self, path, length):
        """先只发请求头：服务那边拿到请求、正在等正文。正文由测试自己分几次发。"""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest("POST", path, skip_host=True, skip_accept_encoding=True)
        c.putheader("Host", "127.0.0.1:%d" % self.port)
        c.putheader("X-Rex-Token", self.tok)
        c.putheader("Content-Length", str(length))
        c.endheaders()
        return c

    def test_token_file_is_private(self):
        mode = os.stat(rex_link.TOKEN_FILE).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_needs_token(self):
        self.assertEqual(self.req("GET", "/api/recent")[0], 403)
        self.assertEqual(self.req("GET", "/?t=wrong")[0], 403)
        self.assertEqual(self.req("GET", "/?t=" + self.tok)[0], 200)

    def test_new_token_takes_effect_while_running(self):
        # rex link new-token 说「旧二维码作废」：开着的服务不重起也得马上认新的、不认旧的
        old, new = self.tok, rex_link.token(new=True)
        type(self).tok = new
        self.assertEqual(self.req("GET", "/?t=" + old)[0], 403)
        self.assertEqual(self.req("GET", "/?t=" + new)[0], 200)
        self.assertEqual(os.stat(rex_link.TOKEN_FILE).st_mode & 0o777, 0o600)

    def test_post_token_only_in_header(self):
        # 口令放在网址里的 POST 不认：别的网页里的表单能带网址参数，带不了自定义头
        self.assertEqual(self.req("POST", "/api/begin?ext=m4a&t=" + self.tok)[0], 403)

    def test_host_must_be_local_or_tailnet(self):
        self.assertEqual(self.req("GET", "/?t=" + self.tok, host="evil.example.com")[0], 403)
        self.assertEqual(self.req("GET", "/?t=" + self.tok, host="mac.tail1234.ts.net:8443")[0], 200)

    def test_healthz_says_who_it_is(self):
        # rex link 靠这个认出端口上是它；别的服务答 200 不算
        self.assertEqual(self.req("GET", "/healthz"), (200, {"ok": True, "service": "rex-link"}))

    def test_cross_origin_post_refused(self):
        st, _ = self.post("/api/begin?ext=m4a", headers={"Origin": "https://evil.example.com"})
        self.assertEqual(st, 403)

    def test_chunks_in_order_land_in_inbox(self):
        st, j = self.post("/api/begin?ext=mp4")
        self.assertEqual(st, 200)
        sid = j["id"]
        self.assertEqual(self.post("/api/chunk?id=%s&seq=0" % sid, b"AAA")[0], 200)
        self.assertEqual(self.post("/api/chunk?id=%s&seq=0" % sid, b"AAA")[0], 200)   # 重传同一块：不重复写
        st, j = self.post("/api/chunk?id=%s&seq=5" % sid, b"ZZZ")                   # 跳号：拒绝，并说等哪块
        self.assertEqual((st, j["want"]), (409, 1))
        self.assertEqual(self.post("/api/chunk?id=%s&seq=1" % sid, b"BB")[0], 200)
        st, j = self.post("/api/end?id=%s" % sid)
        self.assertEqual(st, 200, j)
        path = os.path.join(rex_link.INBOX, j["name"])
        self.assertTrue(j["name"].startswith("手机录音-") and j["name"].endswith(".m4a"))
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), b"AAABB")
        self.assertFalse(any(f.endswith(".part") for f in os.listdir(rex_link.INBOX)))

    def test_end_twice_is_fine(self):
        # 收尾的回话没到手机，手机再来一次：照样说好、名字一样，不说「没有这次录音」
        sid = self.post("/api/begin?ext=m4a")[1]["id"]
        self.post("/api/chunk?id=%s&seq=0" % sid, b"ONCE")
        first = self.post("/api/end?id=%s" % sid)
        self.assertEqual(first[0], 200)
        self.assertEqual(self.post("/api/end?id=%s" % sid), first)

    def test_abandoned_recording_still_reaches_inbox(self):
        sid = self.post("/api/begin?ext=webm")[1]["id"]
        self.post("/api/chunk?id=%s&seq=0" % sid, b"HALF")
        rex_link.SESSIONS[sid]["last"] -= rex_link.IDLE + 1
        moved = rex_link.salvage()
        self.assertEqual(len(moved), 1)
        self.assertIn("未收尾", moved[0])
        self.assertTrue(moved[0].endswith(".webm"))
        with open(moved[0], "rb") as fh:
            self.assertEqual(fh.read(), b"HALF")
        self.assertEqual(self.post("/api/chunk?id=%s&seq=1" % sid, b"MORE")[0], 404)   # 页面据此提示

    def test_chunk_arriving_while_salvaged_is_refused(self):
        # 正在收这一块的时候，它被当成没收尾的收走了：这一块不能再写出一个新的 .part（不然又多一条「未收尾」）
        sid = self.post("/api/begin?ext=m4a")[1]["id"]
        self.post("/api/chunk?id=%s&seq=0" % sid, b"AAAA")
        c = self.slow_post("/api/chunk?id=%s&seq=1" % sid, 4)
        c.send(b"BB")
        time.sleep(0.3)
        rex_link.SESSIONS[sid]["last"] -= rex_link.IDLE + 1
        moved = rex_link.salvage()
        c.send(b"BB")
        r = c.getresponse()
        r.read()
        c.close()
        self.assertEqual(r.status, 404)
        self.assertEqual(len(moved), 1)
        with open(moved[0], "rb") as fh:
            self.assertEqual(fh.read(), b"AAAA")
        self.assertFalse(any(f.startswith(sid) for f in os.listdir(rex_link.PARTS)))

    def test_orphan_part_after_restart(self):
        os.makedirs(rex_link.PARTS, exist_ok=True)
        orphan = os.path.join(rex_link.PARTS, "20261014-080000-abcdef.m4a.part")
        half_up = os.path.join(rex_link.PARTS, "up-1234.part")
        for p in (orphan, half_up):
            with open(p, "wb") as fh:
                fh.write(b"X")
            os.utime(p, (1, 1))
        moved = rex_link.salvage(idle=0)
        self.assertEqual(len(moved), 1)
        self.assertTrue(os.path.basename(moved[0]).startswith("手机录音-未收尾-0800"))
        self.assertFalse(os.path.exists(orphan) or os.path.exists(half_up))

    def test_live_recording_not_salvaged(self):
        sid = self.post("/api/begin?ext=m4a")[1]["id"]
        self.post("/api/chunk?id=%s&seq=0" % sid, b"LIVE")
        os.utime(rex_link.SESSIONS[sid]["path"], (1, 1))
        self.assertEqual(rex_link.salvage(), [])
        self.assertEqual(self.post("/api/end?id=%s" % sid)[0], 200)

    def test_empty_recording_not_kept(self):
        sid = self.post("/api/begin?ext=webm")[1]["id"]
        self.assertEqual(self.post("/api/end?id=%s" % sid)[0], 400)

    def test_unknown_format_refused(self):
        self.assertEqual(self.post("/api/begin?ext=exe")[0], 400)

    def test_inbox_on_another_disk(self):
        # REX_DIR 在外置硬盘上：缓存改名进收件箱跨不了盘，要拷过去；收件箱里不能留下拷了一半的文件
        real = os.replace

        def replace(src, dst):
            if str(src).startswith(rex_link.PARTS):
                raise OSError(errno.EXDEV, "Cross-device link")
            return real(src, dst)
        rex_link.os.replace = replace
        try:
            sid = self.post("/api/begin?ext=m4a")[1]["id"]
            self.post("/api/chunk?id=%s&seq=0" % sid, b"DISK")
            st, j = self.post("/api/end?id=%s" % sid)
        finally:
            rex_link.os.replace = real
        self.assertEqual(st, 200, j)
        with open(os.path.join(rex_link.INBOX, j["name"]), "rb") as fh:
            self.assertEqual(fh.read(), b"DISK")
        self.assertFalse([f for f in os.listdir(rex_link.INBOX) if f.startswith(".link-")])
        self.assertFalse(any(f.startswith(sid) for f in os.listdir(rex_link.PARTS)))

    def test_upload_name_cannot_escape_inbox(self):
        st, j = self.post("/api/upload?name=" + "..%2F..%2Fx.m4a", b"DATA")
        self.assertEqual(st, 200, j)
        self.assertTrue(os.path.exists(os.path.join(rex_link.INBOX, j["name"])))
        self.assertNotIn("/", j["name"])
        self.assertEqual(self.post("/api/upload?name=a.sh", b"DATA")[0], 400)

    def test_upload_keeps_name_and_time(self):
        # 和拖进收件箱、录音台上传一样：原名进去，修改时间用原文件的（收件箱按它给录音起日期）
        when = 1760000000.0
        name = "Main St 4.m4a"
        st, j = self.post("/api/upload?name=" + urllib.parse.quote(name), b"ONE", headers={"X-Rex-Mtime": str(when)})
        self.assertEqual((st, j["name"]), (200, name))
        self.assertEqual(int(os.path.getmtime(os.path.join(rex_link.INBOX, name))), int(when))
        self.assertEqual(self.post("/api/upload?name=" + urllib.parse.quote(name), b"TWO")[1]["name"], "Main St 4-2.m4a")
        self.assertEqual(self.post("/api/upload?name=.dotted.m4a", b"X")[1]["name"], "dotted.m4a")   # 点开头收件箱不认
        self.assertEqual(self.post("/api/upload?name=x.amr", b"X")[0], 400)    # 收件箱不认的格式当场说不行

    def test_stalled_upload_is_not_swept(self):
        # 手机网慢、一个文件传了很久：收拾残留的时候不能把正在传的当成半截删掉
        c = self.slow_post("/api/upload?name=memo.m4a", 6)
        c.send(b"ABC")
        for _ in range(60):
            if rex_link.UPLOADING:
                break
            time.sleep(0.05)
        tmp = next(iter(rex_link.UPLOADING))
        os.utime(tmp, (1, 1))
        rex_link.salvage()
        self.assertTrue(os.path.exists(tmp))
        c.send(b"DEF")
        r = c.getresponse()
        j = json.loads(r.read())
        c.close()
        self.assertEqual(r.status, 200, j)
        with open(os.path.join(rex_link.INBOX, j["name"]), "rb") as fh:
            self.assertEqual(fh.read(), b"ABCDEF")

    def test_recent_and_download(self):
        key = "2026-10-14_120000_both_投资"
        with open(os.path.join(REXDIR, key + ".txt"), "w", encoding="utf-8") as fh:
            fh.write("[00:00:01] 我：你好 <b>\n\n[00:00:05] 对方：你好\n")
        with open(os.path.join(REXDIR, key + ".srt"), "w", encoding="utf-8") as fh:
            fh.write("1\n00:00:01,000 --> 00:00:02,000\n我：你好\n")
        st, j = self.req("GET", "/api/recent", headers={"X-Rex-Token": self.tok})
        self.assertEqual(j["items"][0]["key"], key)
        self.assertEqual(j["items"][0]["title"], "投资")
        st, data = self.req("GET", "/api/file?fmt=docx&k=%s&t=%s" % (urllib.parse.quote(key), self.tok))
        self.assertEqual(st, 200)
        self.assertEqual(data[:2], b"PK")
        st, _ = self.req("GET", "/api/file?fmt=docx&k=..%2Fetc&t=" + self.tok)
        self.assertEqual(st, 400)


class Export(unittest.TestCase):
    def test_docx_has_turns_and_escapes(self):
        d = tempfile.mkdtemp()
        prefix = os.path.join(d, "2026-10-14_093000_mic_课堂")
        with open(prefix + ".txt", "w", encoding="utf-8") as fh:
            fh.write("[00:01:02] 我：A & B <c>\n\n[00:01:09] 老师：第二轮\n第二行\n")
        out = rex_export.export(prefix + ".m4a", "docx")
        self.assertEqual(out, prefix + ".docx")
        with zipfile.ZipFile(out) as z:
            self.assertEqual(sorted(z.namelist()), ["[Content_Types].xml", "_rels/.rels", "word/document.xml"])
            doc = z.read("word/document.xml").decode("utf-8")
        self.assertIn("A &amp; B &lt;c&gt;", doc)
        self.assertIn("老师：", doc)
        self.assertIn("[00:01:02] ", doc)
        self.assertIn(">课堂<", doc)                     # 标题取文件名里的关键词
        shutil.rmtree(d)

    def test_docx_line_breaks_and_control_chars(self):
        # 一轮里的换行要成为 Word 里的换行；控制字符会让整份 Word 打不开，要去掉
        d = tempfile.mkdtemp()
        prefix = os.path.join(d, "2026-10-14_093000_mic")
        with open(prefix + ".txt", "w", encoding="utf-8") as fh:
            fh.write("[00:00:01] 我：第一行\n第二\x0c行\x01\n")
        with zipfile.ZipFile(rex_export.export(prefix + ".txt", "docx")) as z:
            doc = z.read("word/document.xml").decode("utf-8")
        ET.fromstring(doc)
        self.assertIn("第一行</w:t><w:br/><w:t", doc)
        self.assertIn(">第二行<", doc)
        shutil.rmtree(d)

    def test_title_is_what_the_desk_shows(self):
        # 手机录的进收件箱后叫「日期_时刻_drop-手机录音-1430」：标题是「手机录音 1430」，不是整个文件名
        self.assertEqual(rex_export.title_of("/x/2026-10-14_1430_drop-手机录音-1430"),
                         ("手机录音 1430", "2026-10-14 14:30"))
        self.assertEqual(rex_export.title_of("2026-08-14_1609_phone_Projection-GUI-Session")[0],
                         "Projection · GUI · Session")
        self.assertEqual(rex_export.title_of("notes"), ("notes", ""))

    def test_plain_transcript(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "x.txt")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("第一句\n第二句\n")
        self.assertEqual(rex_export.read_turns(p), [(None, None, "第一句"), (None, None, "第二句")])
        shutil.rmtree(d)

    def test_srt_is_the_existing_file(self):
        d = tempfile.mkdtemp()
        prefix = os.path.join(d, "2026-10-14_093000_mic")
        open(prefix + ".srt", "w").close()
        self.assertEqual(rex_export.export(prefix + "-mic.m4a", "srt"), prefix + ".srt")
        with self.assertRaises(FileNotFoundError):
            rex_export.export(os.path.join(d, "nothing"), "docx")
        shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
