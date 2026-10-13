"""录音台「双击移到废纸篓」：只动这一条录音的文件、分轨两条一起走、正在录的不动。不碰真的废纸篓。

    python3 -m unittest discover -s tests
"""
import os
import shutil
import sys
import tempfile
import unittest

# 测试不碰真的家目录：锁文件、缓存、~/.config/rex 里的个人词表都按 HOME 找
os.environ["HOME"] = tempfile.mkdtemp()
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


if __name__ == "__main__":
    unittest.main()
