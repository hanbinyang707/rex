"""录音台「双击移到废纸篓」：只动这一条录音的文件、分轨两条一起走、正在录的不动。不碰真的废纸篓。
还有：录音台读不了自己的文件时（起它的程序退出、macOS 收回「文稿」权限），给一页说明，不掉线；
「接着问」从分析重新开始（分叉新会话，原会话不动）。不调 claude。

    python3 -m unittest discover -s tests
"""
import http.client
import http.server
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

# 测试不碰真的家目录：锁文件、缓存、~/.config/rex 里的个人词表都按 HOME 找
os.environ["HOME"] = tempfile.mkdtemp()
os.environ["REX_LANG"] = "zh"            # 断言的是中文提示；英文另有 test_i18n.py
REXDIR = tempfile.mkdtemp()
os.environ["REX_DIR"] = REXDIR           # rex_app 在 import 时读它，必须先设
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import rex_app  # noqa: E402


def tearDownModule():
    shutil.rmtree(REXDIR, ignore_errors=True)


class TrashRecording(unittest.TestCase):
    def setUp(self):
        for f in os.listdir(REXDIR):
            p = os.path.join(REXDIR, f)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        self.bin = tempfile.mkdtemp()
        self.real = rex_app.to_trash
        rex_app.to_trash = lambda p: shutil.move(p, self.bin) and not os.path.exists(p)

    def tearDown(self):
        rex_app.to_trash = self.real
        shutil.rmtree(self.bin)

    def touch(self, *names):
        for n in names:
            open(os.path.join(REXDIR, n), "w").close()

    def test_only_this_recording(self):
        k = "2026-10-14_120000_mic"
        self.touch(k + ".m4a", k + ".txt", k + ".srt", k + ".校对.json",
                   k + "_关键词.m4a", "2026-10-14_120000_sys.m4a")     # 名字相近的另外两条
        ok, msg = rex_app.trash_recording(k)
        self.assertTrue(ok, msg)
        self.assertEqual(sorted(os.listdir(self.bin)), sorted([k + ".m4a", k + ".txt", k + ".srt", k + ".校对.json"]))
        self.assertEqual(sorted(os.listdir(REXDIR)), sorted([k + "_关键词.m4a", "2026-10-14_120000_sys.m4a"]))

    def test_split_pair_goes_together(self):
        k = "2026-10-14_130000_both"
        self.touch("2026-10-14_130000_both-mic.m4a", "2026-10-14_130000_both-sys.m4a", k + ".txt")
        ok, msg = rex_app.trash_recording(k)
        self.assertTrue(ok, msg)
        self.assertEqual(len(os.listdir(self.bin)), 3)

    def test_refuses_while_recording(self):
        k = "2026-10-14_140000_both"
        self.touch(k + ".m4a")
        with open(os.path.join(REXDIR, ".current"), "w") as fh:
            fh.write("pid=%d\nmode=both\nstart=0\nfiles=%s\n" % (os.getpid(), os.path.join(REXDIR, k + ".m4a")))
        ok, msg = rex_app.trash_recording(k)
        self.assertFalse(ok)
        self.assertIn("正在录", msg)
        self.assertTrue(os.path.exists(os.path.join(REXDIR, k + ".m4a")))

    def test_nothing_there(self):
        self.assertFalse(rex_app.trash_recording("2026-01-01_000000_mic")[0])


@unittest.skipIf(os.geteuid() == 0, "root 打得开权限为 0 的文件，模拟不了")
class LostAccess(unittest.TestCase):
    """2026-10-16：起录音台的 Claude 重启了，还在跑的录音台读不了「文稿」里自己的页面，每个请求都掉线，
    rex app status 说「没开」，rex app 又因为端口被占起不来。现在给一页说明，并且不能冒充好着的录音台。"""

    def setUp(self):
        self.static = tempfile.mkdtemp()
        for n in ("index.html", "app.js"):
            p = os.path.join(self.static, n)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("<title>录音台</title>")
            os.chmod(p, 0)                         # 打开时 PermissionError，和权限被收回时一样
        self.real = rex_app.STATIC
        rex_app.STATIC = self.static
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), rex_app.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        rex_app.STATIC = self.real
        for n in os.listdir(self.static):
            os.chmod(os.path.join(self.static, n), 0o600)
        shutil.rmtree(self.static)

    def get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
        c.request("GET", path, headers={"Host": "127.0.0.1:%d" % rex_app.PORT})
        r = c.getresponse()
        body = r.read().decode("utf-8")
        c.close()
        return r.status, body

    def test_explains_instead_of_dropping(self):
        st, body = self.get("/")
        self.assertEqual(st, 503)
        self.assertIn("rex app", body)
        self.assertNotIn("<title>录音台</title>", body)   # rex.sh 的 app_up 认这一串；带上了，rex app 就不会重起它
        self.assertEqual(self.get("/app.js")[0], 503)


class Daemon(unittest.TestCase):
    def test_phone_list_does_not_touch_voice_memos(self):
        # 常驻的录音台（launchd 起的）没有读语音备忘录的权限：碰都不碰（免得替 python 弹授权框），告诉人用 rex phone
        real = rex_app.VM_DIR
        rex_app.VM_DIR = "/nonexistent-should-not-be-read"
        os.environ["REX_APP_DAEMON"] = "1"
        try:
            j = rex_app.phone_list()
        finally:
            del os.environ["REX_APP_DAEMON"]
            rex_app.VM_DIR = real
        self.assertFalse(j["ok"])
        self.assertIn("rex phone", j["msg"])


class ChatStartOver(unittest.TestCase):
    """2026-10-19：命令行的自动记忆让「接着问」回来一整段 `Write {"file_path": …}`，那几轮留在会话历史里，
    之后怎么问它都照着学。从分析刚做完的那一刻分叉出新会话再问，原会话一个字不动。"""
    KEY = "2026-10-19_033500_drop-测试"
    BASE = "aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb"
    ANCHOR = "cccccccc-4444-4555-8666-dddddddddddd"

    def setUp(self):
        self.prefix = os.path.join(REXDIR, self.KEY)
        with open(self.prefix + ".分析.md", "w", encoding="utf-8") as fh:
            fh.write("# 分析\n\n- 会话号 `%s`\n" % self.BASE)
        rows = [{"type": "queue-operation"},
                {"type": "user", "uuid": "u1", "message": {"role": "user", "content": "<转写稿>…"}},
                {"type": "assistant", "uuid": "a0", "message": {"role": "assistant", "content": [{"type": "thinking"}]}},
                {"type": "assistant", "uuid": self.ANCHOR, "message": {"role": "assistant", "content": [{"type": "text", "text": "分析"}]}},
                {"type": "user", "uuid": "u2", "message": {"role": "user", "content": "写一个总结"}},
                {"type": "assistant", "uuid": "a2", "message": {"role": "assistant", "content": [{"type": "text", "text": "Write\n\n{\n  \"file_path\": \"x\""}]}}]
        self.sess = rex_app.session_file(self.BASE)
        os.makedirs(os.path.dirname(self.sess), exist_ok=True)
        with open(self.sess, "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        with open(self.prefix + ".对话.json", "w", encoding="utf-8") as fh:
            json.dump({"sid": self.BASE, "turns": [{"q": "写一个总结", "a": "Write\n\n{\n  \"file_path\": \"x\"}"}]}, fh)
        self.calls = []
        self.real = rex_app.claude_cli.run
        self.reply = {"result": "这是总结。", "session_id": "11111111-2222-3333-4444-555555555555", "total_cost_usd": 0.01}
        rex_app.claude_cli.run = lambda args, *a, **k: (self.calls.append(args), dict(self.reply))[1]

    def tearDown(self):
        rex_app.claude_cli.run = self.real
        for ext in (".分析.md", ".对话.json"):
            if os.path.exists(self.prefix + ext):
                os.remove(self.prefix + ext)
        os.remove(self.sess)

    def chatlog(self):
        with open(self.prefix + ".对话.json", encoding="utf-8") as fh:
            return json.load(fh)

    def test_anchor_is_the_analysis_reply(self):
        self.assertEqual(rex_app.analysis_anchor(self.BASE), self.ANCHOR)

    def test_start_over_forks_from_the_analysis(self):
        before = open(self.sess, encoding="utf-8").read()
        j = rex_app.chat(self.KEY, "再写一遍总结", fresh=True)
        self.assertTrue(j["ok"], j)
        self.assertEqual(self.calls[0][:5], ["--resume", self.BASE, "--resume-session-at", self.ANCHOR, "--fork-session"])
        self.assertIn("--tools", self.calls[0])
        c = self.chatlog()
        self.assertEqual(c["sid"], self.reply["session_id"])
        self.assertEqual([t["q"] for t in c["turns"]], ["再写一遍总结"])
        self.assertEqual(c["earlier"][0]["turns"][0]["q"], "写一个总结")
        self.assertEqual(open(self.sess, encoding="utf-8").read(), before)      # 原会话一个字不动
        rex_app.chat(self.KEY, "接着说", fresh=False)                         # 之后接着新会话问
        self.assertEqual(self.calls[1][:2], ["--resume", self.reply["session_id"]])

    def test_a_fake_tool_call_answer_is_flagged(self):
        self.reply["result"] = 'Read\n\n{\n  "file_path": "/x/memory/MEMORY.md"\n}'
        j = rex_app.chat(self.KEY, "继续")
        self.assertIn("从分析重新开始", j.get("warn", ""))
        self.reply["result"] = "Read 这本书时要注意：\n{ 不是代码 }"
        self.assertNotIn("warn", rex_app.chat(self.KEY, "再问"))



class JoinOnTheDesk(unittest.TestCase):
    """录音台的「合成一条」：一起拖进来的几个文件先放暂存区、不进收件箱；排任务之前把不能合的挡下来；
    排上之后那几条都算「正在处理」；列表认得出合成的那条。不真跑 rex join（JOBS 换成假的）。"""

    class FakeJobs:
        def __init__(self):
            self.added = []

        def add(self, kind, key, label, steps, keys=()):
            job = {"id": "j%d" % len(self.added), "kind": kind, "key": key, "label": label, "steps": steps,
                   "keys": list(keys)}
            self.added.append(job)
            return job

        def busy(self, key):
            return key == "2026-10-19_100000_mic"          # 假装这一条正在处理

    def setUp(self):
        for f in os.listdir(REXDIR):
            p = os.path.join(REXDIR, f)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        self.real = rex_app.JOBS
        rex_app.JOBS = self.jobs = self.FakeJobs()

    def tearDown(self):
        rex_app.JOBS = self.real

    def touch(self, *names):
        for n in names:
            with open(os.path.join(REXDIR, n), "w") as fh:
                fh.write("x")

    def test_staged_uploads_stay_out_of_the_inbox(self):
        d = rex_app.stage_dir("ab12cd34")
        a = rex_app.save_upload("新录音.m4a", 3, io.BytesIO(b"abc"), folder=d)
        b = rex_app.save_upload("新录音.m4a", 3, io.BytesIO(b"def"), folder=d)
        self.assertEqual([os.path.basename(a), os.path.basename(b)], ["新录音.m4a", "新录音-2.m4a"])
        self.assertEqual(os.path.dirname(a), os.path.join(REXDIR, ".join", "ab12cd34"))
        self.assertFalse(os.path.exists(rex_app.INBOX))
        for bad in ("../x", "AB12CD34", "ab12", "", "ab12cd34/.."):
            self.assertIsNone(rex_app.stage_dir(bad), bad)

    def test_from_the_list(self):
        self.touch("2026-10-19_090000_mic.m4a", "2026-10-19_093000_mic.m4a")
        ok, msg, job = rex_app.queue_join({"keys": ["2026-10-19_090000_mic", "2026-10-19_093000_mic"], "name": " 周会 "})
        self.assertTrue(ok, msg)
        self.assertEqual(job["steps"][0][2:], ["join", os.path.join(REXDIR, "2026-10-19_090000_mic.m4a"),
                                               os.path.join(REXDIR, "2026-10-19_093000_mic.m4a"), "--name", "周会"])
        self.assertEqual(job["keys"], ["2026-10-19_090000_mic", "2026-10-19_093000_mic"])

    def test_refuses_what_it_should(self):
        self.touch("2026-10-19_090000_mic.m4a", "2026-10-19_100000_mic.m4a", "2026-10-19_110000_mic.m4a",
                   "2026-10-19_120000_both-mic.m4a", "2026-10-19_120000_both-sys.m4a")
        for keys, why in ((["2026-10-19_090000_mic"], "两段以上"),
                          (["2026-10-19_090000_mic", "2026-10-19_090000_mic"], "两遍"),
                          (["2026-10-19_090000_mic", "不存在"], "没有音频"),
                          (["2026-10-19_090000_mic", "../etc"], "没有音频"),
                          (["2026-10-19_090000_mic", "2026-10-19_100000_mic"], "正在处理"),
                          (["2026-10-19_090000_mic", "2026-10-19_120000_both"], "分轨")):
            ok, msg, _ = rex_app.queue_join({"keys": keys})
            self.assertFalse(ok, keys)
            self.assertIn(why, msg)
        with open(os.path.join(REXDIR, ".current"), "w") as fh:
            fh.write("pid=%d\nmode=mic\nstart=0\nfiles=%s\n" % (os.getpid(), os.path.join(REXDIR, "2026-10-19_110000_mic.m4a")))
        ok, msg, _ = rex_app.queue_join({"keys": ["2026-10-19_090000_mic", "2026-10-19_110000_mic"]})
        self.assertFalse(ok)
        self.assertIn("正在录", msg)
        self.assertEqual(self.jobs.added, [])

    def test_uploaded_group_in_the_given_order(self):
        d = rex_app.stage_dir("ab12cd34")
        os.makedirs(d)
        for n in ("a.m4a", "b.m4a"):
            with open(os.path.join(d, n), "w") as fh:
                fh.write("x")
        ok, msg, job = rex_app.queue_join({"group": "ab12cd34", "files": ["b.m4a", "a.m4a"]})
        self.assertTrue(ok, msg)
        self.assertEqual(job["steps"][0][2:], ["join", os.path.join(d, "b.m4a"), os.path.join(d, "a.m4a")])
        for files in (["a.m4a", "../x.m4a"], ["a.m4a", "c.m4a"], ["a.m4a"], ["a.m4a", ".upload-1.part"]):
            self.assertFalse(rex_app.queue_join({"group": "ab12cd34", "files": files})[0], files)
        self.assertFalse(rex_app.queue_join({"group": "nope", "files": ["a.m4a", "b.m4a"]})[0])

    def test_joined_recording_in_the_list(self):
        k = "2026-10-19_090000_mic_周会"
        self.touch(k + ".m4a")
        with open(os.path.join(REXDIR, k + ".分段.json"), "w", encoding="utf-8") as fh:
            json.dump({"segments": [{"name": "2026-10-19_090000_mic.m4a", "key": "2026-10-19_090000_mic", "start": 0,
                                     "duration": 60, "via": ["2026-10-19_090000_mic_上午"]},
                                    {"name": "新录音 3.m4a", "key": None, "start": 60, "duration": 30}]}, fh)
        r = [x for x in rex_app.scan() if x["key"] == k][0]
        self.assertEqual(r["parts"], 2)
        # 录音台按它跟到这一条上：原来的名字、拖进来的文件名，还有中间合成过的那条
        self.assertEqual(r["joined_from"], ["2026-10-19_090000_mic", "2026-10-19_090000_mic_上午", "新录音 3.m4a"])
        self.assertEqual(len(rex_app.detail(k)["parts"]), 2)
        self.assertIn(os.path.join(REXDIR, k + ".分段.json"), rex_app.recording_files(k))   # 删的时候一起走

    def test_busy_covers_every_part(self):
        jobs = rex_app.Jobs.__new__(rex_app.Jobs)          # 不起后台线程
        jobs.items, jobs.lock = [], threading.Lock()
        jobs.items.append({"key": "", "keys": ["2026-10-19_090000_mic", "2026-10-19_093000_mic"], "state": "排队"})
        self.assertTrue(jobs.busy("2026-10-19_093000_mic"))
        self.assertFalse(jobs.busy("2026-10-19_100000_mic"))


if __name__ == "__main__":
    unittest.main()
