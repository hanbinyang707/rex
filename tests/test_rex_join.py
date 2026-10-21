"""几段录音合成一条（rex_join.py）。用 ffmpeg 现做几秒的测试音，不碰真的录音文件夹和家目录。没有 ffmpeg 就跳过。

    python3 -m unittest discover -s tests
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HOME = os.environ["HOME"] = tempfile.mkdtemp()
os.environ["REX_LANG"] = "zh"
REXDIR = tempfile.mkdtemp()
os.environ["REX_DIR"] = REXDIR
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import analyze  # noqa: E402
import proofread  # noqa: E402
import rex_join  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def tearDownModule():
    shutil.rmtree(REXDIR, ignore_errors=True)
    shutil.rmtree(HOME, ignore_errors=True)


def tone(path, seconds, both=False):
    if both:     # 和 rex both 一样的三路：混音（立体声）、麦克风、电脑声音，各带 handler_name
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "lavfi", "-i", "sine=frequency=300:duration=%s" % seconds,
               "-f", "lavfi", "-i", "sine=frequency=500:duration=%s" % seconds,
               "-f", "lavfi", "-i", "sine=frequency=700:duration=%s" % seconds,
               "-map", "0:a", "-map", "1:a", "-map", "2:a", "-c:a", "aac", "-ac:a:0", "2", "-ac:a:1", "1", "-ac:a:2", "1",
               "-metadata:s:a:0", "handler_name=mix", "-metadata:s:a:1", "handler_name=mic",
               "-metadata:s:a:2", "handler_name=sys", path]
    else:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
               "-i", "sine=frequency=440:duration=%s" % seconds, "-ac", "1", "-c:a", "aac", path]
    subprocess.run(cmd, check=True)


def jload(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def srt(path, lines):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join("%d\n00:00:%02d,000 --> 00:00:%02d,500\n%s\n\n" % (i, a, a, t) for i, (a, t) in enumerate(lines, 1)))


@unittest.skipUnless(HAVE_FFMPEG, "要 ffmpeg")
class Join(unittest.TestCase):
    def setUp(self):
        for f in os.listdir(REXDIR):
            p = os.path.join(REXDIR, f)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        self.err, sys.stderr = sys.stderr, io.StringIO()      # 合并时给人看的那几行别混进测试输出

    def tearDown(self):
        sys.stderr = self.err

    def p(self, key):
        return os.path.join(REXDIR, key)

    def test_plain_recordings_end_to_end(self):
        tone(self.p("2026-10-19_033200_drop-会谈-1.m4a"), 2)
        tone(self.p("2026-10-19_035000_drop-会谈-2.m4a"), 3)
        out = rex_join.join(["2026-10-19_033200_drop-会谈-1", "2026-10-19_035000_drop-会谈-2"])
        # 第一段的时刻和名字。和第一段同名也不要紧：第一段先挪进了 已合并/，不用加 -2
        self.assertEqual(os.path.basename(out), "2026-10-19_033200_drop-会谈-1.m4a")
        dur, chans, tracks = rex_join.probe(out)
        self.assertAlmostEqual(dur, 5, delta=0.3)
        self.assertEqual(len(chans), 1)
        seg = jload(out[:-4] + ".分段.json")
        self.assertEqual([s["name"] for s in seg["segments"]], ["2026-10-19_033200_drop-会谈-1.m4a", "2026-10-19_035000_drop-会谈-2.m4a"])
        self.assertAlmostEqual(seg["segments"][1]["start"], 2, delta=0.2)
        self.assertFalse(seg["reused_transcripts"])
        self.assertFalse(os.path.exists(out[:-4] + ".srt"))                 # 没转写过：交给 rex go 整条转
        moved = os.path.join(REXDIR, "已合并", "2026-10-19_033200_drop-会谈-1")
        self.assertEqual(sorted(os.listdir(moved)), ["2026-10-19_033200_drop-会谈-1.m4a", "2026-10-19_035000_drop-会谈-2.m4a"])
        self.assertAlmostEqual(rex_join.probe(os.path.join(moved, "2026-10-19_033200_drop-会谈-1.m4a"))[0], 2, delta=0.2)
        self.assertFalse(os.path.exists(self.p("2026-10-19_035000_drop-会谈-2.m4a")))
        self.assertEqual(os.listdir(rex_join.STAGE_DIR), [])                 # 工作目录收掉了

    def test_call_tracks_are_kept(self):
        tone(self.p("2026-10-19_090000_both.m4a"), 2, both=True)
        tone(self.p("2026-10-19_093000_both.m4a"), 2, both=True)
        out = rex_join.join(["2026-10-19_090000_both", "2026-10-19_093000_both"], name="周会")
        self.assertEqual(os.path.basename(out), "2026-10-19_090000_both_周会.m4a")
        dur, chans, tracks = rex_join.probe(out)
        self.assertEqual(tracks, {"mix": 0, "mic": 1, "sys": 2})             # rex.sh 的 speaker_tracks 靠它认出分轨
        self.assertEqual(chans, [2, 1, 1])
        self.assertAlmostEqual(dur, 4, delta=0.3)

    def test_transcripts_and_proofreading_carry_over(self):
        a, b = self.p("2026-10-19_100000_drop-访谈-1"), self.p("2026-10-19_110000_drop-访谈-2")
        tone(a + ".m4a", 4)
        tone(b + ".m4a", 3)
        srt(a + ".srt", [(0, "我：第一句"), (2, "对方：第二句")])
        srt(b + ".srt", [(0, "我：第三句"), (1, "对方：第四句")])
        st = proofread.new_state()
        proofread.add_row(st, "applied", {"id": 1, "t": 0.0, "who": "我", "old": "地一", "new": "第一", "why": "", "by": "claude", "pos": 0})
        proofread.add_row(st, "unsure", {"id": 2, "t": 2.0, "who": "对方", "old": "第二", "new": "第贰", "why": "", "by": ""})
        proofread.save_state(a, st)
        out = rex_join.join([a + ".m4a", b + ".m4a"])
        prefix = out[:-4]
        lines = proofread.read_entries(prefix)
        self.assertEqual([e["text"] for e in lines], ["我：第一句", "对方：第二句", "我：第三句", "对方：第四句"])
        self.assertAlmostEqual(lines[2]["a"], 4, delta=0.3)                 # 第二段的时间接在第一段后面
        merged = jload(prefix + ".校对.json")
        self.assertEqual([r["id"] for r in merged["applied"]], [1])
        self.assertEqual([r["id"] for r in merged["unsure"]], [2])
        self.assertEqual(merged["failed"], [[3, 4]])                       # 第二段没校对过：rex go 只补校这两行
        rids = [r["rid"] for k in ("applied", "unsure") for r in merged[k]]
        self.assertEqual(len(set(rids)), len(rids))
        self.assertTrue(merged["next_rid"] > max(rids))
        with open(prefix + ".txt", encoding="utf-8") as fh:
            txt = fh.read()
        self.assertIn("对方：第四句", txt)                                     # 对话稿照常重排
        self.assertTrue(os.path.exists(prefix + ".whisper.srt"))
        self.assertTrue(jload(prefix + ".分段.json")["reused_transcripts"])

    def test_analysis_is_told_about_the_parts(self):
        a, b = self.p("2026-10-19_190000_drop-课-1"), self.p("2026-10-19_191000_drop-课-2")
        tone(a + ".m4a", 2)
        tone(b + ".m4a", 2)
        srt(a + ".srt", [(0, "说话人1：开始")])
        srt(b + ".srt", [(0, "说话人1：接着")])
        note = analyze.parts_note(rex_join.join([a, b])[:-4])
        self.assertIn("由 2 段录音", note)
        self.assertIn("分开判断", note)            # 各段分开判的说话人：提醒一句，别当成同一个人
        self.assertIn("课-2", note)
        self.assertEqual(analyze.parts_note(self.p("没合成过的")), "")

    def test_keep_and_outside_files_stay(self):
        tone(self.p("2026-10-19_120000_mic.m4a"), 1)
        outside = tempfile.mkdtemp()
        tone(os.path.join(outside, "外面.m4a"), 1)
        out = rex_join.join(["2026-10-19_120000_mic", os.path.join(outside, "外面.m4a")], keep=True)
        self.assertTrue(os.path.exists(self.p("2026-10-19_120000_mic.m4a")))
        self.assertTrue(os.path.exists(os.path.join(outside, "外面.m4a")))
        self.assertTrue(os.path.exists(out))
        shutil.rmtree(outside)

    def test_refuses_what_it_should(self):
        tone(self.p("2026-10-19_130000_mic.m4a"), 1)
        tone(self.p("2026-10-19_131000_mic.m4a"), 1)
        with self.assertRaises(rex_join.JoinError):
            rex_join.join(["2026-10-19_130000_mic"])                          # 一段不叫合并
        with self.assertRaises(rex_join.JoinError):
            rex_join.join(["2026-10-19_130000_mic", "2026-10-19_130000_mic"])
        with self.assertRaises(rex_join.JoinError):
            rex_join.join(["2026-10-19_130000_mic", "不存在的录音"])
        with open(self.p(".current"), "w", encoding="utf-8") as fh:
            fh.write("pid=1\nfiles=%s\n" % self.p("2026-10-19_131000_mic.m4a"))
        with self.assertRaises(rex_join.JoinError):                       # 正在录的不动
            rex_join.join(["2026-10-19_130000_mic", "2026-10-19_131000_mic"])
        self.assertFalse([f for f in os.listdir(REXDIR) if "_drop-" in f])   # 失败时什么都没留下

    def test_name_is_cleaned_and_unique(self):
        for k in ("2026-10-19_140000_mic", "2026-10-19_141000_mic", "2026-10-19_142000_mic", "2026-10-19_143000_mic"):
            tone(self.p(k + ".m4a"), 1)
        one = rex_join.join(["2026-10-19_140000_mic", "2026-10-19_141000_mic"], name="季度 复盘_会议", keep=True)
        # 都是麦克风录的：来源沿用 mic，名字放在关键词的位置。下划线是字段分隔符，换掉
        self.assertEqual(os.path.basename(one), "2026-10-19_140000_mic_季度-复盘-会议.m4a")
        two = rex_join.join(["2026-10-19_140000_mic", "2026-10-19_142000_mic"], name="季度 复盘_会议", keep=True)
        self.assertEqual(os.path.basename(two), "2026-10-19_140000_mic_季度-复盘-会议-2.m4a")

    def test_unnamed_waits_for_keywords(self):
        for k in ("2026-10-19_150000_mic", "2026-10-19_151000_mic"):
            tone(self.p(k + ".m4a"), 1)
        kept = rex_join.join(["2026-10-19_150000_mic", "2026-10-19_151000_mic"], keep=True)
        self.assertEqual(os.path.basename(kept), "2026-10-19_150000_mic_合并.m4a")   # 原来那条还在：起个名分开
        out = rex_join.join(["2026-10-19_150000_mic", "2026-10-19_151000_mic"])
        # 还没转写、没有名字：先叫 X_mic（rex go 转写完按关键词改名），第一段挪走了，名字让出来
        self.assertEqual(os.path.basename(out), "2026-10-19_150000_mic.m4a")
        self.assertEqual(len(jload(out[:-4] + ".分段.json")["segments"]), 2)

    def test_mixed_sources_are_imports(self):
        tone(self.p("2026-10-19_160000_mic.m4a"), 1)
        tone(self.p("2026-10-19_161000_phone.m4a"), 1)
        out = rex_join.join(["2026-10-19_160000_mic", "2026-10-19_161000_phone"])
        self.assertEqual(os.path.basename(out), "2026-10-19_160000_drop-drop.m4a")   # 没有原名的导入就这么写

    def test_staged_uploads_are_kept_in_joined(self):
        group = os.path.join(rex_join.STAGE_DIR, "ab12cd34")
        os.makedirs(group)
        a, b = os.path.join(group, "新录音 3.m4a"), os.path.join(group, "新录音 4.m4a")
        tone(a, 1)
        tone(b, 1)
        t = 1760850000          # 拖进来的文件按修改时间定开录时刻（上传时带过来的）
        os.utime(a, (t, t))
        os.utime(b, (t + 600, t + 600))
        out = rex_join.join([a, b])
        stamp = rex_join.datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d_%H%M%S")
        self.assertEqual(os.path.basename(out), stamp + "_drop-新录音-3.m4a")
        self.assertEqual(sorted(os.listdir(os.path.join(REXDIR, "已合并", stamp + "_drop-新录音-3"))),
                         ["新录音 3.m4a", "新录音 4.m4a"])
        self.assertEqual(os.listdir(rex_join.STAGE_DIR), [])                 # 那一组空了，收掉
        self.assertEqual([p["key"] for p in jload(out[:-4] + ".分段.json")["segments"]], [None, None])

    def test_joining_a_joined_one_lists_every_part(self):
        for k in ("2026-10-19_170000_mic", "2026-10-19_171000_mic", "2026-10-19_172000_mic"):
            tone(self.p(k + ".m4a"), 1)
        ab = rex_join.join(["2026-10-19_170000_mic", "2026-10-19_171000_mic"], name="上午")
        abc = rex_join.join([ab, self.p("2026-10-19_172000_mic.m4a")], name="全天")
        parts = jload(abc[:-4] + ".分段.json")["segments"]
        self.assertEqual([p["key"] for p in parts], ["2026-10-19_170000_mic", "2026-10-19_171000_mic", "2026-10-19_172000_mic"])
        self.assertAlmostEqual(parts[2]["start"], 2, delta=0.3)
        self.assertEqual(parts[0]["via"], [os.path.basename(ab)[:-4]])     # 中间那条：录音台靠它跟过来

    def test_split_recording_in_current_counts_as_recording(self):
        tone(self.p("2026-10-19_180000_mic.m4a"), 1)
        tone(self.p("2026-10-19_181000_mic.m4a"), 1)
        with open(self.p(".current"), "w", encoding="utf-8") as fh:      # 老的 --split：两条用 | 隔开
            fh.write("pid=1\nfiles=%s|%s\n" % (self.p("x-mic.m4a"), self.p("2026-10-19_181000_mic.m4a")))
        with self.assertRaises(rex_join.JoinError):
            rex_join.join(["2026-10-19_180000_mic", "2026-10-19_181000_mic"])


if __name__ == "__main__":
    unittest.main()
