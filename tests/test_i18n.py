"""中英两套输出：每种语言起一个子进程（语言在 import 时就定了），看关键输出是不是那种语言。

    python3 -m unittest discover -s tests
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TOOLS = os.path.join(ROOT, "tools")


def run_py(lang, code):
    env = dict(os.environ, REX_LANG=lang, HOME=tempfile.mkdtemp(), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r)\n%s" % (TOOLS, code)],
                       capture_output=True, text=True, env=env, timeout=60)
    if r.returncode:
        raise AssertionError(r.stderr)
    return r.stdout


class Languages(unittest.TestCase):
    def test_helper(self):
        self.assertEqual(run_py("en", "from i18n import L; print(L('中', 'en'))").strip(), "en")
        self.assertEqual(run_py("zh", "from i18n import L; print(L('中', 'en'))").strip(), "中")

    def test_proofreading_report_headings(self):
        code = ("import proofread as pf\n"
                "st = pf.new_state(); pf.add_row(st, 'unsure', {'id': 1, 't': 0.0, 'who': '', 'old': 'a', 'new': 'b', 'why': '', 'by': ''})\n"
                "print(pf.render_md('x', st))")
        en, zh = run_py("en", code), run_py("zh", code)
        self.assertIn("Uncertain", en)
        self.assertNotRegex(en.split("|")[0], r"[一-鿿]{2}")   # 表格之前的标题和说明是英文
        self.assertIn("拿不准", zh)

    def test_report_written_in_one_language_reads_back_in_the_other(self):
        d = tempfile.mkdtemp()
        try:
            prefix = os.path.join(d, "t")
            with open(prefix + ".srt", "w", encoding="utf-8") as fh:
                fh.write("1\n00:00:00,000 --> 00:00:01,000\nabc\n\n")
            write = ("import proofread as pf\nst = pf.new_state()\n"
                     "pf.add_row(st, 'unsure', {'id': 1, 't': 0.0, 'who': '', 'old': 'a', 'new': 'b', 'why': 'w', 'by': ''})\n"
                     "open(%r, 'w', encoding='utf-8').write(pf.render_md('t', st))" % (prefix + ".校对.md"))
            read = ("import proofread as pf\n"
                    "st = pf.bootstrap(%r, pf.read_entries(%r)); print(len(st['unsure']))" % (prefix, prefix))
            for w, r in (("en", "zh"), ("zh", "en")):
                run_py(w, write)
                self.assertEqual(run_py(r, read).strip(), "1", "%s 写的报告 %s 读不回来" % (w, r))
        finally:
            shutil.rmtree(d)

    def test_default_speaker_names(self):
        code = "import speakers, argparse, sys\nsys.argv=['x']\nprint(speakers.L('我,对方', 'Me,Other'))"
        self.assertEqual(run_py("en", code).strip(), "Me,Other")
        self.assertEqual(run_py("zh", code).strip(), "我,对方")

    @unittest.skipUnless(shutil.which("ffmpeg"), "rex.sh 开头要 ffmpeg")
    def test_help_text(self):
        def helptext(lang):
            env = dict(os.environ, REX_LANG=lang, HOME=tempfile.mkdtemp())
            return subprocess.run(["/bin/bash", os.path.join(TOOLS, "rex.sh"), "help"], capture_output=True,
                                  text=True, env=env, timeout=60).stdout
        en, zh = helptext("en"), helptext("zh")
        self.assertIn("rex both", en)
        self.assertNotRegex(en.splitlines()[0], r"[一-鿿]")
        self.assertIn("录", zh.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
