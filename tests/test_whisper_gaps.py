"""whisper_gaps.py：转写完查「有人声、却没出字」的地方，逐处报出来、补转回去。

不跑 whisper。装了 whisper-vad-speech-segments 和 VAD 模型的话，再拿 `say` 现念两句话验一下真的 VAD。

    python3 -m unittest discover -s tests
"""
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

os.environ["REX_LANG"] = "zh"
TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
sys.path.insert(0, TOOLS)
import whisper_gaps as wg  # noqa: E402
import whisper_run as wr  # noqa: E402

# 别的测试会把 HOME 换成临时目录，真模型按真的家目录找
REAL_VAD = os.environ.get("WHISPER_VAD_MODEL") or os.path.join(
    pwd.getpwuid(os.getuid()).pw_dir, ".cache/whisper/ggml-silero-v5.1.2.bin")
HAVE_VAD = bool(shutil.which("whisper-vad-speech-segments") and os.path.exists(REAL_VAD)
                and shutil.which("say") and shutil.which("ffmpeg"))

FULL = "我们这一段说了很多很多的话所以字幕里字也很多"      # 22 个字


def talk(a, z, step=2.0, gap=0.5):
    """[a, z] 里断断续续的人声：说 step 秒、停 gap 秒。"""
    out, t = [], a
    while t < z:
        out.append((t, min(z, t + step)))
        t += step + gap
    return out


def said(a, z):
    """一条正常的字幕：[a, z] 里要是全是 talk 那样的人声，每秒人声差不多 3.7 个字。"""
    return (a, z, (FULL * (int((z - a) * 3 / 22) + 1)))


class Units(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(wg.units("你好世界"), 4)
        self.assertEqual(wg.units("hello world"), 3)                # 一个词算 1.5 个字
        self.assertEqual(wg.units("我用 Docker 跑了 3 次"), 8)      # 我用跑了次 + Docker、3 各 1.5
        self.assertEqual(wg.units("neo-soul"), 3)
        self.assertEqual(wg.units("，。…  "), 0)
        self.assertEqual(wg.units("こんにちは"), 5)


class Cues(unittest.TestCase):
    def test_round_trip_keeps_times_and_lines(self):
        srt = ("1\n00:09:01,530 --> 00:09:33,040\n第一行\n第二行\n\n"
               "2\n01:02:03,004 --> 01:02:05,000\nsecond\n")
        cues = wg.read_cues(srt)
        self.assertEqual(cues, [(541.53, 573.04, "第一行\n第二行"), (3723.004, 3725.0, "second")])
        self.assertEqual(wg.read_cues(wg.write_cues(cues)), cues)
        self.assertTrue(wg.write_cues(cues).startswith("1\n00:09:01,530 --> 00:09:33,040\n第一行\n第二行\n\n2\n"))

    def test_short(self):
        self.assertEqual(wg.short(541.53), "09:01")
        self.assertEqual(wg.short(3725.9), "1:02:05")

    def test_shifted_times_never_get_a_thousand_milliseconds(self):
        # 分语言转时 srt_shift 加偏移，14.65 + 0.35 这类浮点和原来拼出过 00:00:59,1000，read_cues 读不懂就跳过了
        self.assertEqual(wr.hhmmss(59.9996), "00:01:00.000")
        self.assertEqual(wr.short(3599.9996), "1:00:00")
        block, _ = wr.srt_shift("1\n00:00:00,350 --> 00:00:05,000\nx\n", 59.6496, 1)
        self.assertEqual(wg.read_cues(block), [(60.0, 64.65, "x")])


class Holes(unittest.TestCase):
    def test_gap_between_cues(self):
        # 那段组会：541.5 到 573.5 一条字幕都没有，中间断断续续有 8 秒多人声
        voice = talk(530, 541.5) + [(541.6, 542.4), (550.8, 553.4), (558.2, 563.8), (567.4, 573.2)] + talk(573.6, 580)
        cues = [said(530, 541.53), said(573.53, 580)]
        h = wg.holes(voice, cues)
        self.assertEqual(len(h), 1)
        s, e, v = h[0]
        # 报的是那几段人声的头尾，不是空档的头尾
        self.assertEqual((wg.short(s), wg.short(e)), ("09:02", "09:33"))
        # 紧挨着前后字幕的各 0.5 秒算它们的（SLACK），其余都算漏的
        self.assertAlmostEqual(v, (542.4 - 542.03) + 2.6 + 5.6 + (573.03 - 567.4), places=6)

    def test_silent_gap_is_not_a_hole(self):
        voice = talk(0, 100) + talk(700, 800)
        self.assertEqual(wg.holes(voice, [said(0, 100), said(700, 800)]), [])

    def test_scattered_noises_in_a_break_are_not(self):
        # 课间十分钟：椅子、咳嗽，每 20 秒一下，一下 1 秒——加起来 30 秒，但哪一处都不够
        voice = talk(0, 100) + [(100 + 20 * i, 101 + 20 * i) for i in range(1, 30)] + talk(700, 800)
        self.assertEqual(wg.holes(voice, [said(0, 100), said(700, 800)]), [])

    def test_a_few_words_in_a_break_are_not(self):
        voice = talk(0, 100) + [(400, 401.5), (403, 405)] + talk(700, 800)
        self.assertEqual(wg.holes(voice, [said(0, 100), said(700, 800)]), [])

    def test_pause_shorter_than_join_keeps_it_one_hole(self):
        # 助教那段：中间停了 12.7 秒，还是同一处
        voice = [(204.5, 205.6), (205.6, 208.1), (208.1, 211.0), (211.3, 212.0), (213.0, 214.3),
                 (227.0, 229.5), (229.5, 233.6)]
        h = wg.holes(voice, [said(300, 330)])
        self.assertEqual([(round(s, 1), round(e, 1)) for s, e, _ in h], [(204.5, 233.6)])

    def test_a_solid_cue_in_between_splits_it(self):
        voice = talk(100, 108) + talk(110, 120) + talk(122, 130)
        h = wg.holes(voice, [said(109, 121)])
        self.assertEqual([(s, round(e, 1)) for s, e, _ in h], [(100, 108), (122, 130)])

    def test_long_pause_splits_it(self):
        voice = talk(100, 106) + talk(130, 136)
        self.assertEqual(len(wg.holes(voice, [])), 2)

    def test_thin_cue_does_not_count(self):
        # 那节课：一条 00:01–05:06 的字幕只有「同学们 开始上课」，里面 03:24–03:53 有一段通知
        voice = [(1.8, 3.7), (9.2, 10.6)] + talk(204.5, 214.3) + talk(227, 233.6) + [(304.9, 306.4)] + talk(307.9, 330)
        cues = [(1.78, 306.4, "同学们 开始上课"), said(307.92, 330)]
        h = wg.holes(voice, cues)
        self.assertEqual([(wg.short(s), wg.short(e)) for s, e, _ in h], [("03:24", "03:53")])

    def test_a_cue_that_kept_only_its_last_sentence(self):
        # 组会 02:42：21 秒的字幕里人声 8.8 秒，只剩最后一句 16 个字——每秒 1.8 个，前面的漏了
        voice = [(163.5, 164.9), (169.4, 170.3), (170.7, 171.9), (172.8, 174.2), (177.2, 177.6), (178.3, 178.7),
                 (180.2, 183.1)]
        cues = [said(150, 162.2), (162.2, 183.1, "因为上周他们回复我们的时候说的是"), said(183.1, 200)]
        h = wg.holes(voice, cues)
        self.assertEqual(len(h), 1)
        self.assertAlmostEqual(h[0][0], 163.5)

    def test_made_up_words_over_speech(self):
        # 那节课开头不带词表转：00:01–03:53 一条编出来的，盖住了助教那段（每秒人声 1.1 个字）
        voice = [(1.8, 3.7), (9.2, 10.6)] + talk(204.5, 214.3) + talk(227, 233.6)
        cues = [(1.78, 233.9, "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目"), said(234, 260)]
        self.assertEqual([(wg.short(s), wg.short(e)) for s, e, _ in wg.holes(voice, cues)], [("03:24", "03:53")])

    def test_long_cue_over_silence_is_fine(self):
        # 开了 VAD，一条字幕跨过一大段静音很常见：90 秒，8 个字，里面人声只有 4 秒——不看它薄不薄
        voice = [(7.3, 9.1), (9.1, 10.0), (99.4, 100.8)] + talk(101, 130)
        cues = [(7.3, 100.8, "这个代码也是有的"), said(100.8, 130)]
        self.assertEqual(wg.holes(voice, cues), [])

    def test_normal_speech_is_fine(self):
        # 没漏的字幕里最稀的纯中文：每秒人声 2.95 个字
        voice = talk(0, 7)                                      # 6 秒人声
        self.assertEqual(wg.holes(voice, [(0, 7, "这种隐喻里头就十军东征时代来临了")]), [])   # 16 个字

    def test_english_counts_words(self):
        # 英文一个词算 1.5 个字：每秒人声 2 个词的英文不算薄
        cue = (0, 7, "they suggest us to use their GUI and then we can run it")    # 12 个词
        self.assertEqual(wg.holes(talk(0, 7), [cue]), [])

    def test_before_the_first_and_after_the_last_cue(self):
        voice = talk(0, 10) + talk(20, 40) + talk(60, 70)
        h = wg.holes(voice, [said(20, 40)])
        self.assertEqual([(s, round(e, 1)) for s, e, _ in h], [(0, 9.5), (60, 69.5)])

    def test_no_cues_at_all(self):
        self.assertEqual(len(wg.holes(talk(0, 30), [])), 1)

    def test_language_segments_share_the_file_timeline(self):
        # 分语言转：第二段从 300 秒切出来，段内 50~60 秒没出字。srt_shift 把它加回 300，
        # VAD 量的是整个文件，两边直接比，报在 05:50
        part1 = wg.write_cues([said(0, 300)])
        part2 = wg.write_cues([said(0, 50), said(60, 100)])
        b1, idx = wr.srt_shift(part1, 0.0, 1)
        b2, _ = wr.srt_shift(part2, 300.0, idx)
        voice = talk(0, 300) + talk(300, 400)
        h = wg.holes(voice, wg.read_cues(b1 + "\n\n" + b2))
        self.assertEqual([(wg.short(s), wg.short(e)) for s, e, _ in h], [("05:50", "05:59")])


class Speech(unittest.TestCase):
    def setUp(self):
        fd, self.model = tempfile.mkstemp()
        os.close(fd)

    def tearDown(self):
        os.remove(self.model)

    def run_with(self, stdout, rc=0):
        done = subprocess.CompletedProcess([], rc, stdout=stdout, stderr="")
        with mock.patch.object(wg.shutil, "which", return_value="/x/whisper-vad-speech-segments"), \
                mock.patch.object(wg.subprocess, "run", return_value=done) as run:
            return wg.speech(self.model, "a.wav"), run

    def test_centiseconds(self):
        segs, run = self.run_with("Detected 2 speech segments:\n"
                                  "Speech segment 0: start = 729.00, end = 910.00\n"
                                  "Speech segment 1: start = 54138.00, end = 54242.00\n")
        self.assertEqual(segs, [(7.29, 9.1), (541.38, 542.42)])
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[cmd.index("-vp") + 1], "0")        # 不加留白：量真有声音的时长

    def test_no_speech_is_an_empty_list(self):
        self.assertEqual(self.run_with("Detected 0 speech segments:\n")[0], [])

    def test_unreadable_output_is_none(self):
        self.assertIsNone(self.run_with("Detected 3 speech segments:\nSpeech segment 0: start = 1.00, end = 2.00\n")[0])
        self.assertIsNone(self.run_with("something else\n")[0])
        self.assertIsNone(self.run_with("Detected 0 speech segments:\n", rc=1)[0])

    def test_missing_tool_or_model_is_none(self):
        with mock.patch.object(wg.shutil, "which", return_value=None):
            self.assertIsNone(wg.speech(self.model, "a.wav"))
        with mock.patch.object(wg.shutil, "which", return_value="/x/whisper-vad-speech-segments"):
            self.assertIsNone(wg.speech("/nonexistent/vad.bin", "a.wav"))
            self.assertIsNone(wg.speech("", "a.wav"))


class Check(unittest.TestCase):
    """check()：报、补转、插回去。VAD 和补转都是假的。"""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.out = os.path.join(self.d, "t")
        self.cues = [(530.0, 541.53, "我给他估计一下"), (573.53, 575.84, "然后我会晚点吧"),
                     (575.84, 600.0, FULL * 3)]
        self.write(self.cues)
        # 第一条只有 3 秒人声，不看它薄不薄
        self.voice = [(538.5, 541.5), (541.6, 542.4), (550.8, 553.4), (558.2, 563.8), (567.4, 573.2)] \
            + talk(573.6, 600)
        self.calls = []
        self.logs = []
        self.answer = ""

    def tearDown(self):
        shutil.rmtree(self.d)

    def write(self, cues):
        with open(self.out + ".srt", "w", encoding="utf-8") as fh:
            fh.write(wg.write_cues(cues))
        with open(self.out + ".txt", "w", encoding="utf-8") as fh:      # 和 whisper -otxt 一样：一条一行
            fh.write("\n".join(t for _, _, t in cues) + "\n")

    def read(self, ext):
        with open(self.out + ext, encoding="utf-8") as fh:
            return fh.read()

    def redo(self, lo, hi, lang):
        self.calls.append((lo, hi, lang))
        return self.answer

    def check(self, runs=((0.0, 900.0, "zh"),), voice=None):
        with mock.patch.object(wg, "speech", return_value=self.voice if voice is None else voice):
            return wg.check("a.wav", self.out, "vad.bin", list(runs), self.redo, self.logs.append)

    def test_reports_redoes_and_inserts_in_order(self):
        # 补转出来的时间从切的起点（541.53）算
        self.answer = wg.write_cues([(0.5, 3.0, "做一次 然后把它切开来"), (17.0, 22.0, "想说剩下一个人家做起提"),
                                     (27.0, 29.5, "好的好的好的")])
        srt0 = self.read(".srt")
        self.assertEqual(self.check(), 1)
        self.assertIn("  ⚠️ 09:02–09:33 有声音但没转出字（人声约 14 秒）", self.logs)
        self.assertTrue(any("补回 27 字" in l and "做一次" in l for l in self.logs), self.logs)
        self.assertTrue(any("已按时间插进 .txt 和 .srt" in l for l in self.logs))
        # 前面紧挨着一条实字幕：往前不越过它的结尾；往后多切 EDGE 秒，也不越过下一条的开头
        self.assertEqual(self.calls, [(541.53, 573.53, "zh")])
        cues = wg.read_cues(self.read(".srt"))
        self.assertEqual([t for _, _, t in cues],
                         ["我给他估计一下", "做一次 然后把它切开来", "想说剩下一个人家做起提", "好的好的好的",
                          "然后我会晚点吧", FULL * 3])
        self.assertEqual(cues[1][:2], (542.03, 544.53))
        # 原来的字幕一条不动
        self.assertEqual([c for c in cues if c in self.cues], self.cues)
        self.assertEqual(self.read(".srt").count("-->"), 6)
        self.assertTrue(self.read(".srt").startswith("1\n") and "\n\n6\n" in self.read(".srt"))
        self.assertEqual(self.read(".txt").splitlines(), [t for _, _, t in cues])
        self.assertNotEqual(srt0, self.read(".srt"))

    def test_inside_a_thin_cue_it_goes_before_the_thin_words(self):
        # 那节课开头：00:01–05:06 一条「同学们 开始上课」（05:05 才说），03:24–03:53 的通知没了
        self.cues = [(1.78, 306.4, "同学们 开始上课"), said(307.92, 330.0)]
        self.write(self.cues)
        self.voice = [(1.8, 3.7)] + talk(204.5, 214.3) + talk(227, 233.6) + [(304.9, 306.4)] + talk(307.9, 330)
        self.answer = wg.write_cues([(0.2, 1.4, "各位同学大家好"), (2.0, 6.5, "为了方便以后联络 我们现在面对面进群"),
                                     (26.0, 29.0, "大家把周围没有进群的同学拉进来")])
        self.assertEqual(self.check(), 1)
        self.assertEqual(self.calls, [(204.0, 234.1, "zh")])
        cues = wg.read_cues(self.read(".srt"))
        self.assertEqual(self.read(".txt").splitlines(),
                         ["各位同学大家好", "为了方便以后联络 我们现在面对面进群", "大家把周围没有进群的同学拉进来",
                          "同学们 开始上课", self.cues[1][2]])
        # 薄字幕的字一个不改，只是开头挪到补进来的后面；时间轴照样从前往后
        self.assertEqual(cues[3], (233.0, 306.4, "同学们 开始上课"))
        self.assertEqual([a for a, _, _ in cues], sorted(a for a, _, _ in cues))

    def test_the_same_sentence_in_traditional_characters_is_not_inserted_twice(self):
        # 那节课 1:42:21：一条 31 秒的字幕只剩最后一句。单独重转出来，那一句成了繁体——
        # 按字比只重合三成上下，折成简体六成多，认得出是同一句，不插第二遍
        thin = (6141.0, 6173.0, "我以后在讲科普上跟你们讲百度这个房子做的有多差")
        self.cues = [said(6120.0, 6141.0), thin, said(6173.0, 6190.0)]
        self.write(self.cues)
        self.voice = talk(6120, 6141) + talk(6142, 6172) + talk(6173, 6190)
        self.answer = wg.write_cues([(1.0, 3.0, "所有人都在忙"), (10.0, 13.0, "它是人類的第二座八別塔"),
                                     (26.0, 28.0, "我以後再講科目上跟你們講"), (28.0, 30.0, "百度這個房子做這個獨場")])
        self.assertEqual(self.check(), 1)
        lo = self.calls[0][0]
        cues = wg.read_cues(self.read(".srt"))
        self.assertEqual([t for _, _, t in cues],
                         [self.cues[0][2], "所有人都在忙", "它是人類的第二座八別塔", thin[2], self.cues[2][2]])
        # 那一句在重转里落在哪，薄字幕就挪到哪
        self.assertAlmostEqual(cues[3][0], lo + 26.0)
        self.assertEqual(cues[3][1:], thin[1:])

    def test_a_missing_english_sentence_is_not_mistaken_for_one_already_there(self):
        # 早先按字母两两比，英文哪句都能在前后十几秒的字幕里对上六成多：这一句按字母比 0.63，
        # 真漏了也被当成「已经有了」。按词比是 0.12
        self.cues = [(10.0, 16.0, "So the first thing we need to do is to load the data into the model and then check the results."),
                     (24.5, 30.0, "After that we can compare the results with the ones from last week and see what has changed.")]
        self.write(self.cues)
        self.voice = [(10.5, 15.5), (16.8, 23.8), (25.0, 29.5)]
        lost = "I think there is a problem with the way the files are stored on the server."
        self.answer = wg.write_cues([(0.3, 6.5, lost)])
        self.assertEqual(self.check(runs=[(0.0, 60.0, "en")]), 1)
        self.assertFalse(any("不算漏" in l for l in self.logs), self.logs)
        self.assertIn(lost, self.read(".txt"))

    def test_an_english_sentence_already_there_is_not_inserted(self):
        self.cues = [(10.0, 16.0, "So the first thing we need to do is to load the data into the model and then check the results."),
                     (24.5, 30.0, "After that we can compare the results with the ones from last week and see what has changed.")]
        self.write(self.cues)
        self.voice = [(10.5, 15.5), (16.8, 23.8), (25.0, 29.5)]
        self.answer = wg.write_cues([(0.3, 6.5, "load the data into the model and then check the results")])
        srt0 = self.read(".srt")
        self.assertEqual(self.check(runs=[(0.0, 60.0, "en")]), 0)
        self.assertEqual(self.read(".srt"), srt0)

    def test_old_words_merged_into_a_new_cue_are_cut_out(self):
        # 重转常把几句并成一条：新话后面跟着薄字幕那句。整条比会被新话冲淡、插进去，同一句就出现两遍；
        # 按小句比，只插新的那两句，薄字幕挪到它们后面
        thin = (6141.0, 6173.0, "我以后在讲科普上跟你们讲百度这个房子做的有多差")
        self.cues = [said(6120.0, 6141.0), thin, said(6173.0, 6190.0)]
        self.write(self.cues)
        self.voice = talk(6120, 6141) + talk(6142, 6172) + talk(6173, 6190)
        self.answer = wg.write_cues([(1.0, 30.0, "所有人都在忙 也不知道背后有没有蜂王 我以后在讲科普上跟你们讲百度这个房子做的有多差")])
        self.assertEqual(self.check(), 1)
        cues = wg.read_cues(self.read(".srt"))
        self.assertEqual([t for _, _, t in cues],
                         [self.cues[0][2], "所有人都在忙 也不知道背后有没有蜂王", thin[2], self.cues[2][2]])
        # 新的那两句按字数比例占前面一截，薄字幕从那之后起
        self.assertLess(cues[1][1], 6160)
        self.assertAlmostEqual(cues[2][0], cues[1][1])

    def test_a_name_heard_differently_is_still_the_same_sentence(self):
        # 不带词表重转，人名写法跟带词表的不一样：按两字片段只重合四成多，按连着对得上的算有六成多
        self.cues = [(530.0, 541.53, "卡西莫多爱上了爱斯梅拉达"), (573.53, 575.84, "然后我会晚点吧"),
                     (575.84, 600.0, FULL * 3)]
        self.write(self.cues)
        self.answer = wg.write_cues([(0.0, 2.0, "卡西默多爱上了艾斯美拉达"), (9.0, 12.0, "做一次 然后把它切开来")])
        self.check()
        texts = [t for _, _, t in wg.read_cues(self.read(".srt"))]
        self.assertNotIn("卡西默多爱上了艾斯美拉达", texts)
        self.assertIn("做一次 然后把它切开来", texts)

    def test_a_failed_redo_is_not_called_unintelligible(self):
        srt0 = self.read(".srt")
        with mock.patch.object(wg, "speech", return_value=self.voice):
            n = wg.check("a.wav", self.out, "vad.bin", [(0.0, 900.0, "zh")], lambda lo, hi, l: None, self.logs.append)
        self.assertEqual(n, 1)
        self.assertTrue(any("没成功" in l for l in self.logs), self.logs)
        self.assertFalse(any("听不清" in l for l in self.logs))
        self.assertEqual(self.read(".srt"), srt0)

    def test_no_redo_when_the_language_is_not_settled(self):
        self.assertEqual(self.check(runs=[(0.0, 900.0, "auto")]), 1)
        self.assertEqual(self.calls, [])
        self.assertTrue(any("语言没定下来" in l for l in self.logs), self.logs)

    def test_unreadable_timestamps_stop_the_check(self):
        # 读不懂的那条要是悄悄跳过，它那段就成了「没字」，报成漏转
        with open(self.out + ".srt", "a", encoding="utf-8") as fh:
            fh.write("\n4\n00:10:00,1000 --> 00:10:05,000\n后面还有一句\n")
        self.assertEqual(self.check(), 0)
        self.assertTrue(any("读不懂" in l for l in self.logs), self.logs)
        self.assertEqual(self.calls, [])

    def test_all_clear_is_only_said_when_nothing_was_found(self):
        self.answer = wg.write_cues([(3.0, 6.0, "我给他估计一下")])     # 找到一处，但重转出来的稿子里都有
        self.check()
        self.assertFalse(any("查过漏转：没有" in l for l in self.logs), self.logs)

    def test_what_is_already_there_is_not_inserted_again(self):
        # 补转的头一条是前一条字幕的尾巴，最后一条是后一条字幕——都扔掉，只插中间那条
        self.answer = wg.write_cues([(0.0, 0.8, "估计一下"), (9.0, 12.0, "做一次 然后把它切开来"),
                                     (31.0, 31.9, "然后我会晚点吧")])
        self.check()
        texts = [t for _, _, t in wg.read_cues(self.read(".srt"))]
        self.assertEqual(texts.count("做一次 然后把它切开来"), 1)
        self.assertEqual(texts.count("然后我会晚点吧"), 1)
        self.assertNotIn("估计一下", texts)

    def test_nothing_new_means_the_timeline_was_just_off(self):
        # 重转出来的话前后字幕里全有：字其实在，只是时间轴标偏了。不算漏、不报警、稿子不动
        self.answer = wg.write_cues([(3.0, 6.0, "我给他估计一下")])
        srt0, txt0 = self.read(".srt"), self.read(".txt")
        self.assertEqual(self.check(), 0)
        self.assertFalse(any("⚠️" in l for l in self.logs), self.logs)
        self.assertTrue(any("不算漏" in l for l in self.logs))
        self.assertEqual((self.read(".srt"), self.read(".txt")), (srt0, txt0))

    def test_redo_cues_outside_the_window_are_dropped(self):
        self.answer = wg.write_cues([(5.0, 8.0, "做一次 然后把它切开来"), (40.0, 45.0, "窗口外面的话不要")])
        self.check()
        self.assertNotIn("窗口外面的话不要", self.read(".srt"))
        self.assertIn("做一次 然后把它切开来", self.read(".srt"))

    def test_empty_redo_is_still_reported(self):
        srt0 = self.read(".srt")
        self.assertEqual(self.check(), 1)
        self.assertIn("  ⚠️ 09:02–09:33 有声音但没转出字（人声约 14 秒）", self.logs)
        self.assertTrue(any("也没出字" in l for l in self.logs))
        self.assertEqual(self.read(".srt"), srt0)

    def test_nothing_missing(self):
        voice = [(538.5, 541.5)] + talk(573.6, 600)
        self.assertEqual(self.check(voice=voice), 0)
        self.assertEqual(self.logs, ["  查过漏转：没有「有人声、却没出字」的地方"])
        self.assertEqual(self.calls, [])

    def test_unmeasurable_vad_is_said_out_loud(self):
        with mock.patch.object(wg, "speech", return_value=None):
            self.assertEqual(wg.check("a.wav", self.out, "vad.bin", [], self.redo, self.logs.append), 0)
        self.assertEqual(len(self.logs), 1)
        self.assertIn("⚠️ 这次没查漏转", self.logs[0])

    def test_txt_that_does_not_match_the_srt_is_left_alone(self):
        with open(self.out + ".txt", "w", encoding="utf-8") as fh:
            fh.write("被别的东西改过\n")
        self.answer = wg.write_cues([(5.0, 8.0, "做一次 然后把它切开来")])
        srt0 = self.read(".srt")
        self.check()
        self.assertTrue(any("对不上" in l for l in self.logs))
        self.assertEqual(self.read(".srt"), srt0)
        self.assertEqual(self.read(".txt"), "被别的东西改过\n")

    def test_language_follows_the_segment(self):
        self.check(runs=[(0.0, 300.0, "en"), (300.0, 900.0, "zh")])
        self.assertEqual(self.calls[0][2], "zh")
        self.calls = []
        self.check(runs=[(0.0, 555.0, "zh"), (555.0, 900.0, "en")])
        self.assertEqual(self.calls[0][2], "en")                 # 按这一处的中点（557~558 秒）算，不按起点

    def test_too_many_holes_are_reported_but_not_all_redone(self):
        voice = []
        for i in range(wg.MAX_REDO + 3):
            voice += talk(1000 + 100 * i, 1010 + 100 * i)
        self.assertEqual(self.check(voice=voice), wg.MAX_REDO + 3)
        self.assertEqual(len(self.calls), wg.MAX_REDO)
        self.assertEqual(sum("有声音但没转出字" in l for l in self.logs), wg.MAX_REDO + 3)
        self.assertTrue(any("只补转了前 %d 处" % wg.MAX_REDO in l for l in self.logs))


class Hook(unittest.TestCase):
    """whisper_run.py 转完调 check；分语言转的稿子拿合并后的时间轴去查。"""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.vad = os.path.join(self.d, "vad.bin")
        open(self.vad, "w").close()
        self.out = os.path.join(self.d, "out")
        self.whisper = []
        self.checked = []

    def tearDown(self):
        shutil.rmtree(self.d)

    def fake_whisper(self, model, wav, out, lang, prompt, vad, vpad, vmodel, echo, offset, hide_paths=False):
        self.whisper.append((wav, out, lang, prompt, vad))
        with open(out + ".srt", "w", encoding="utf-8") as fh:
            fh.write(wg.write_cues([(1.0, 2.0, "说了一句话")]))
        with open(out + ".txt", "w", encoding="utf-8") as fh:
            fh.write("说了一句话\n")
        return 0

    def fake_check(self, audio, out, vmodel, runs, redo, log):
        # 补转得在 check 里调：出了 check，临时目录就没了。.srt 也得在这时候读：查的是这一刻的稿子
        self.whisper = []
        with open(out + ".srt", encoding="utf-8") as fh:
            self.srt_at_check = fh.read()
        self.checked.append((audio, out, vmodel, runs, redo(10.0, 20.0, runs[0][2]), list(self.whisper)))
        return 0

    def main(self, *extra, check=None):
        argv = ["whisper_run.py", "--model", "m.bin", "--audio", "a.wav", "--out", self.out] + list(extra)
        logs = []
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(wr, "run_whisper", self.fake_whisper), \
                mock.patch.object(wr, "slice_wav", return_value=True), \
                mock.patch.object(wr, "duration", return_value=600.0), \
                mock.patch.object(wr.whisper_gaps, "check", check or self.fake_check), \
                mock.patch("builtins.print", lambda *a, **k: logs.append(" ".join(map(str, a)))):
            rc = wr.main()
        return rc, logs

    def test_known_language(self):
        rc, _ = self.main("--lang", "zh", "--vad-model", self.vad)
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.checked), 1)
        audio, out, vmodel, runs, srt, calls = self.checked[0]
        self.assertEqual((audio, out, vmodel, runs), ("a.wav", self.out, self.vad, [(0.0, 600.0, "zh")]))
        # 补转：切那一段，不带词表，VAD 照开，返回转出来的 SRT
        self.assertIn("说了一句话", srt)
        wav, stem, lang, prompt, vad = calls[0]
        self.assertEqual((lang, prompt, vad), ("zh", "", True))
        self.assertNotEqual(stem, self.out)                     # 写在临时目录，不碰正式的稿子

    def test_language_segments_are_checked_after_merging(self):
        with mock.patch.object(wr, "probe_map", return_value=[(15.0, "en"), (300.0, "zh"), (585.0, "zh")]):
            rc, _ = self.main("--lang", "auto", "--vad-model", self.vad)
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.checked), 1)
        self.assertEqual([l for _, _, l in self.checked[0][3]], ["en", "zh"])
        # 查的时候 .srt 已经合并好，时间轴是原文件的：第二段那句在 157.5 + 1 秒
        cues = wg.read_cues(self.srt_at_check)
        self.assertEqual([round(a, 1) for a, _, _ in cues], [1.0, 158.5])

    def test_no_vad_no_check(self):
        rc, logs = self.main("--lang", "zh", "--no-vad")
        self.assertEqual((rc, self.checked), (0, []))
        self.assertIn("  没开 VAD，这次不查漏转", logs)

    def test_a_crash_in_the_check_keeps_the_transcript(self):
        def boom(*a):
            raise ValueError("坏了")
        rc, logs = self.main("--lang", "zh", "--vad-model", self.vad, check=boom)
        self.assertEqual(rc, 0)
        self.assertTrue(any("查漏转时出错" in l and "ValueError: 坏了" in l for l in logs), logs)
        self.assertTrue(os.path.exists(self.out + ".txt"))

    def test_failed_transcription_is_not_checked(self):
        def nothing(model, wav, out, *a, **k):
            return 3
        with mock.patch.object(wr, "run_whisper", nothing), \
                mock.patch.object(sys, "argv", ["x", "--model", "m", "--audio", "a.wav", "--out", self.out,
                                                "--lang", "zh", "--vad-model", self.vad]), \
                mock.patch.object(wr.whisper_gaps, "check", self.fake_check), \
                mock.patch.object(wr, "duration", return_value=600.0), \
                mock.patch("builtins.print"):
            self.assertEqual(wr.main(), 3)
        self.assertEqual(self.checked, [])


class English(unittest.TestCase):
    def test_messages(self):
        code = ("import whisper_gaps as g\n"
                "g.check('a.wav', '/nonexistent/x', '', [], None, print)")
        env = dict(os.environ, REX_LANG="en", HOME=tempfile.mkdtemp(), PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r)\n%s" % (TOOLS, code)],
                           capture_output=True, text=True, env=env, timeout=60)
        self.assertIn("Skipped the gap check", r.stdout, r.stderr)


@unittest.skipUnless(HAVE_VAD, "要 whisper-vad-speech-segments、VAD 模型、say 和 ffmpeg")
class RealVAD(unittest.TestCase):
    """拿 say 念两句话，中间空 8 秒，看真的 VAD 量得对不对、只给第一句配字幕时查不查得出第二句。"""

    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.wav = os.path.join(cls.d, "talk.wav")
        a, b = os.path.join(cls.d, "a.aiff"), os.path.join(cls.d, "b.aiff")
        subprocess.run(["say", "-o", a, "This is the first sentence. It goes on for a few seconds, "
                                        "so that there is enough speech to measure."], check=True)
        subprocess.run(["say", "-o", b, "And this is the second sentence, after a long pause. "
                                        "Nobody wrote it down, so it should be reported."], check=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", a,
                        "-f", "lavfi", "-t", "8", "-i", "anullsrc=r=16000:cl=mono", "-i", b,
                        "-filter_complex", "[0:a]aresample=16000[x];[2:a]aresample=16000[y];"
                                           "[x][1:a][y]concat=n=3:v=0:a=1",
                        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", cls.wav], check=True)
        cls.first = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "default=nw=1:nk=1", a], capture_output=True,
                                         text=True).stdout)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d)

    def test_speech_and_the_gap(self):
        segs = wg.speech(REAL_VAD, self.wav)
        self.assertTrue(segs)
        pause = (self.first + 0.5, self.first + 7.5)
        self.assertLess(wg.voiced(segs, [s for s, _ in segs], *pause), 0.5)      # 停顿里没有人声
        self.assertGreater(wg.voiced(segs, [s for s, _ in segs], 0, self.first), 3)
        later = wg.voiced(segs, [s for s, _ in segs], self.first + 8, 1e9)
        self.assertGreater(later, wg.MIN_VOICE)
        # 只给第一句配了字幕：第二句报出来，停顿不报
        h = wg.holes(segs, [(0.0, self.first, "This is the first sentence. It goes on for a few seconds, "
                                              "so that there is enough speech to measure.")])
        self.assertEqual(len(h), 1)
        self.assertGreater(h[0][0], self.first + 7)


if __name__ == "__main__":
    unittest.main()
