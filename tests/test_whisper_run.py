"""whisper_run.py 怎么把词表交给 whisper：数 token、定 -mc。不跑 whisper；真模型在本机时多对几个数。

    python3 -m unittest discover -s tests
"""
import os
import pwd
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

os.environ["REX_LANG"] = "zh"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import whisper_run as wr  # noqa: E402

# 别的测试会把 HOME 换成临时目录，真模型按真的家目录找
REAL_MODEL = os.environ.get("WHISPER_MODEL") or os.path.join(
    pwd.getpwuid(os.getuid()).pw_dir, ".cache/whisper/ggml-large-v3-turbo-q5_0.bin")


def fake_model(tokens, n_text_ctx=448):
    """和 ggml 模型文件开头一样的布局：magic、11 个超参、梅尔滤波器、词表。后面的权重用不着。"""
    fd, path = tempfile.mkstemp(suffix=".bin")
    with os.fdopen(fd, "wb") as fh:
        fh.write(struct.pack("<I", 0x67676d6c))
        fh.write(struct.pack("<11i", len(tokens), 1500, 384, 6, 4, n_text_ctx, 384, 6, 4, 80, 1))
        fh.write(struct.pack("<ii", 2, 3) + struct.pack("<6f", *([0.0] * 6)))
        fh.write(struct.pack("<i", len(tokens)))
        for t in tokens:
            fh.write(struct.pack("<I", len(t)) + t)
    return path


class Fake(object):
    """顶替 subprocess.Popen，只记下命令行"""
    cmds = []

    def __init__(self, cmd, **kw):
        Fake.cmds.append(cmd)
        self.stdout = iter([])

    def wait(self):
        return 0


class Tokens(unittest.TestCase):
    def setUp(self):
        wr.prompt_tokens.cache_clear()
        singles = [bytes([b]) for b in range(256)]
        self.model = fake_model(singles + [b"ab", b"abc", b" c", "你".encode("utf-8")])

    def tearDown(self):
        os.remove(self.model)

    def test_longest_match_within_each_word(self):
        self.assertEqual(wr.prompt_tokens(self.model, "abc"), (1, 223))   # abc 整个在词表里
        self.assertEqual(wr.prompt_tokens(self.model, "abcd")[0], 2)      # abc + d
        # 空格跟着后面的词走：「ab」「 cd」两个词，后一个是「 c」+「d」
        self.assertEqual(wr.prompt_tokens(self.model, "ab cd")[0], 3)

    def test_chinese_falls_back_to_bytes(self):
        # 「你」在词表里，「好」不在，拆成 3 个字节
        self.assertEqual(wr.prompt_tokens(self.model, "你好")[0], 4)

    def test_not_a_ggml_model(self):
        fd, path = tempfile.mkstemp()
        os.write(fd, b"GGUF" + b"\0" * 100)
        os.close(fd)
        try:
            self.assertEqual(wr.prompt_tokens(path, "abc"), (None, None))
        finally:
            os.remove(path)
        self.assertEqual(wr.prompt_tokens("/nonexistent/model.bin", "abc"), (None, None))

    def test_broken_token_table(self):
        empty = fake_model([])
        cut = fake_model([b"a", b"b"])
        with open(cut, "r+b") as fh:
            fh.truncate(os.path.getsize(cut) - 3)
        try:
            self.assertEqual(wr.prompt_tokens(empty, "abc"), (None, None))
            self.assertEqual(wr.prompt_tokens(cut, "abc"), (None, None))
        finally:
            os.remove(empty)
            os.remove(cut)

    @unittest.skipUnless(os.path.exists(REAL_MODEL), "本机没有 large-v3-turbo 模型")
    def test_matches_whisper_cli_on_the_real_model(self):
        # 这几个数是 whisper-cli 1.9.2 自己报的（-mc 2 --carry-initial-prompt 时打印的「too long (N tokens)」）
        for text, n in [("以下是普通话内容，可能夹杂英文术语。", 23),
                        ("Hello world, this is a test of the tokenizer's behavior. It's 2026.", 19),
                        ("  multiple   spaces\ttab and 123 numbers 4567 v1.9.2 don't I'll we're", 25)]:
            self.assertEqual(wr.prompt_tokens(REAL_MODEL, text), (n, 223), text)


class Command(unittest.TestCase):
    def setUp(self):
        wr.prompt_tokens.cache_clear()
        self.model = fake_model([bytes([b]) for b in range(256)], n_text_ctx=16)   # 上限 16/2-1 = 7
        Fake.cmds = []

    def tearDown(self):
        os.remove(self.model)

    def run_it(self, prompt):
        with mock.patch.object(wr.subprocess, "Popen", Fake):
            wr.run_whisper(self.model, "a.wav", "out", "zh", prompt, False, "200", "", lambda s: None, 0.0)
        return Fake.cmds[-1]

    def arg(self, cmd, flag):
        return cmd[cmd.index(flag) + 1]

    def test_no_prompt_keeps_context_off(self):
        cmd = self.run_it("")
        self.assertEqual(self.arg(cmd, "-mc"), "0")
        self.assertNotIn("--prompt", cmd)
        self.assertNotIn("--carry-initial-prompt", cmd)

    def test_prompt_is_carried_and_context_fits_it_exactly(self):
        cmd = self.run_it("abcd")                    # 4 个单字节 token
        self.assertEqual(self.arg(cmd, "-mc"), "5")  # 词表 4 + [PREV] 1，前文的份额是 0
        self.assertIn("--carry-initial-prompt", cmd)
        self.assertEqual(self.arg(cmd, "--prompt"), "abcd")

    def test_too_long_prompt_is_capped(self):
        cmd = self.run_it("abcdefghij")              # 10 个 token，上限 7
        self.assertEqual(self.arg(cmd, "-mc"), "8")


class Main(unittest.TestCase):
    """main() 读 --prompt-file、决定带不带词表。whisper-cli 和 ffprobe 都是假的。"""

    def setUp(self):
        wr.prompt_tokens.cache_clear()
        wr.can_carry.cache_clear()
        self.model = fake_model([bytes([b]) for b in range(256)])
        self.dir = tempfile.mkdtemp()
        self.pfile = os.path.join(self.dir, "whisper-prompt.txt")
        with open(self.pfile, "w", encoding="utf-8") as fh:
            fh.write("# 注释不算\nabcd\n")
        Fake.cmds = []

    def tearDown(self):
        os.remove(self.model)
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_main(self, help_text, lang="zh"):
        said = []
        argv = ["whisper_run.py", "--model", self.model, "--audio", "a.wav", "--out",
                os.path.join(self.dir, "out"), "--lang", lang, "--prompt-file", self.pfile, "--no-vad"]

        def sh(cmd, quiet=True):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=help_text)
        with mock.patch.object(sys, "argv", argv), mock.patch.object(wr, "sh", sh), \
                mock.patch.object(wr.subprocess, "Popen", Fake), \
                mock.patch("builtins.print", lambda s="", **kw: said.append(s)):
            wr.main()
        return Fake.cmds[-1], "\n".join(said)

    def test_prompt_file_is_carried(self):
        cmd, said = self.run_main("  --carry-initial-prompt [false  ] always prepend initial prompt")
        self.assertEqual(cmd[cmd.index("-mc") + 1], "5")
        self.assertEqual(cmd[cmd.index("--prompt") + 1], "abcd")
        self.assertIn("词表 4 token", said)

    def write_list(self, text):
        with open(self.pfile, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")

    def test_sentence_punctuation_gets_a_hint(self):
        carry = "  --carry-initial-prompt [false  ] always prepend initial prompt"
        for text in ["以下是普通话。常见词：网文", "网文，爽文", "a, b", "a、b.", "Node.js is. fine"]:
            self.write_list(text)
            self.assertIn("句号或逗号", self.run_main(carry)[1], text)

    def test_bare_list_gets_no_hint(self):
        carry = "  --carry-initial-prompt [false  ] always prepend initial prompt"
        for text in ["网文、爽文、neo-soul", "网文 爽文 Node.js", "常见词：网文、爽文"]:
            self.write_list(text)
            self.assertNotIn("句号或逗号", self.run_main(carry)[1], text)

    def test_english_segments_never_get_the_prompt(self):
        cmd, _ = self.run_main("  --carry-initial-prompt [false  ] always prepend initial prompt", lang="en")
        self.assertEqual(cmd[cmd.index("-mc") + 1], "0")
        self.assertNotIn("--prompt", cmd)
        self.assertNotIn("--carry-initial-prompt", cmd)

    def run_probed(self, points):
        """--lang auto：探测结果是假的，切 wav 也是假的，看每一段各拿到什么参数"""
        argv = ["whisper_run.py", "--model", self.model, "--audio", "a.wav", "--out",
                os.path.join(self.dir, "out"), "--lang", "auto", "--prompt-file", self.pfile, "--no-vad"]

        def sh(cmd, quiet=True):
            out = "300.0" if cmd[0] == "ffprobe" else ""
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="--carry-initial-prompt")
        with mock.patch.object(sys, "argv", argv), mock.patch.object(wr, "sh", sh), \
                mock.patch.object(wr, "probe_map", lambda *a: points), \
                mock.patch.object(wr, "slice_wav", lambda *a: True), \
                mock.patch.object(wr.subprocess, "Popen", Fake), \
                mock.patch("builtins.print", lambda s="", **kw: None):
            wr.main()
        return {c[c.index("-l") + 1]: c for c in Fake.cmds}

    def test_mixed_recording_gives_the_list_to_chinese_segments_only(self):
        cmds = self.run_probed([(50.0, "en"), (100.0, "en"), (200.0, "zh"), (280.0, "zh")])
        self.assertEqual(sorted(cmds), ["en", "zh"])
        self.assertEqual(cmds["en"][cmds["en"].index("-mc") + 1], "0")
        self.assertNotIn("--prompt", cmds["en"])
        self.assertEqual(cmds["zh"][cmds["zh"].index("-mc") + 1], "5")
        self.assertIn("--carry-initial-prompt", cmds["zh"])

    def test_single_language_recording_after_probing(self):
        cmds = self.run_probed([(50.0, "zh"), (280.0, "zh")])
        self.assertEqual(cmds["zh"][cmds["zh"].index("-mc") + 1], "5")
        Fake.cmds = []
        cmds = self.run_probed([(50.0, "en"), (280.0, "en")])
        self.assertEqual(cmds["en"][cmds["en"].index("-mc") + 1], "0")
        self.assertNotIn("--prompt", cmds["en"])

    def test_the_shipped_template_changes_nothing(self):
        # 没加过词的人走的就是这份模板。里面要是有一行生效的句子，所有人的稿子都会变成 30 秒一段
        template = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "whisper-prompt.txt")
        shutil.copy(template, self.pfile)
        cmd, said = self.run_main("  --carry-initial-prompt [false  ] always prepend initial prompt")
        self.assertEqual(cmd[cmd.index("-mc") + 1], "0")
        self.assertNotIn("--prompt", cmd)
        self.assertEqual(said, "")

    def test_unreadable_model_gets_no_prompt_instead_of_crashing(self):
        with open(self.model, "wb") as fh:
            fh.write(b"GGUF" + b"\0" * 100)
        cmd, said = self.run_main("  --carry-initial-prompt [false  ] always prepend initial prompt")
        self.assertEqual(cmd[cmd.index("-mc") + 1], "0")
        self.assertNotIn("--prompt", cmd)
        self.assertIn("这次不带它转", said)

    def test_old_whisper_cli_gets_no_prompt_instead_of_failing(self):
        # 1.8.0 及更早不认 --carry-initial-prompt：硬塞进去它会打用法退出、什么都不转
        cmd, said = self.run_main("usage: whisper-cli [options] file0 file1 ...")
        self.assertEqual(cmd[cmd.index("-mc") + 1], "0")
        self.assertNotIn("--carry-initial-prompt", cmd)
        self.assertNotIn("--prompt", cmd)
        self.assertIn("太旧", said)


if __name__ == "__main__":
    unittest.main()
