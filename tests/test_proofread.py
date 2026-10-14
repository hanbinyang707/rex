"""proofread.py 的回归测试：把 Claude 的修改清单落到稿子上、采纳 / 撤销、失败区间。不调 Claude，不读真实录音。

    python3 -m unittest discover -s tests
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

# 测试不碰真的家目录：锁文件、缓存、~/.config/rex 里的个人词表都按 HOME 找
os.environ["HOME"] = tempfile.mkdtemp()
os.environ["REX_LANG"] = "zh"            # 断言的是中文提示；英文另有 test_i18n.py
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import proofread as pf  # noqa: E402

SRT = ("1\n00:00:00,000 --> 00:00:01,000\n我：期中考试和起中的安排\n\n"
       "2\n00:00:01,000 --> 00:00:02,000\n对方：我觉得嗯，这样可以\n\n")


def fix(i, old, new, sure=True, why=""):
    return {"id": i, "old": old, "new": new, "sure": sure, "why": why}


class PureFunctions(unittest.TestCase):
    def test_to_ranges_merges_and_dedupes(self):
        self.assertEqual(pf.to_ranges([1, 2, 3, 5, 7, 8]), [[1, 3], [5, 5], [7, 8]])
        self.assertEqual(pf.to_ranges([241, 242, 241]), [[241, 242]])

    def test_locate(self):
        self.assertEqual(pf.locate("我们一起学", "学"), 4)
        self.assertEqual(pf.locate("期中和起中", "中"), -2)      # 出现不止一次：不知道改哪个
        self.assertEqual(pf.locate("abc", "x"), -1)

    def test_rewrite_guard(self):
        self.assertFalse(pf.looks_like_rewrite("真本", "真格"))
        self.assertFalse(pf.looks_like_rewrite("背头", "被投"))
        self.assertTrue(pf.looks_like_rewrite("签学校", "我们打算明天一起去学校签那份新的合同"))

    def test_has_labels(self):
        self.assertFalse(pf.has_labels([{"text": "他说：我们明天去"}, {"text": "然后呢"}, {"text": "好的"}]))
        self.assertTrue(pf.has_labels([{"text": "我：a"}, {"text": "对方：b"}, {"text": "我：c"}]))


class ApplyFixes(unittest.TestCase):
    def test_same_line_duplicates_noop_and_missed(self):
        e = {"id": 1, "a": 0.0, "z": 1.0, "text": "我：期中考试和起中的安排，我们一起学"}
        state = pf.new_state()
        n_applied, _ = pf.apply_fixes(state, [
            fix(1, "起中", "期中"), fix(1, "起中", "期中"),            # 同一条给了两遍
            fix(1, "学", "学习"), fix(1, "中考试", "中考察"),
            fix(1, "安排", "安排"),                                  # 没改动
            fix(1, "没有的", "x"),                                   # 原文里找不到
        ], {1: e}, labeled=True)
        self.assertEqual(e["text"], "我：期中考察和期中的安排，我们一起学习")
        self.assertEqual(n_applied, 3)
        self.assertEqual(len(state["missed"]), 1)
        _, text = pf.split_label(e["text"], True)
        for r in state["applied"]:                                   # 记下的位置真的指着改过的字
            self.assertEqual(text[r["pos"]:r["pos"] + len(r["new"])], r["new"])

    def test_overlapping_fixes_second_goes_unsure(self):
        e = {"id": 2, "a": 1.0, "z": 2.0, "text": "期中考试"}
        state = pf.new_state()
        n_applied, n_unsure = pf.apply_fixes(state, [fix(2, "期中考", "期终考"), fix(2, "中考试", "中考察")],
                                             {2: e}, labeled=False)
        self.assertEqual((n_applied, n_unsure, e["text"]), (1, 1, "期终考试"))


class Decide(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.prefix = os.path.join(self.dir, "t")
        with open(self.prefix + ".srt", "w", encoding="utf-8") as fh:
            fh.write(SRT)
        st = pf.new_state()
        pf.add_row(st, "unsure", {"id": 1, "t": 0.0, "who": "我", "old": "起中", "new": "期中", "why": "", "by": ""})
        pf.add_row(st, "unsure", {"id": 2, "t": 1.0, "who": "对方", "old": "嗯，", "new": "", "why": "", "by": ""})
        pf.save_state(self.prefix, st)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def srt(self):
        with open(self.prefix + ".srt", encoding="utf-8") as fh:
            return fh.read()

    def test_accept_then_undo_restores_exact_positions(self):
        self.assertTrue(pf.decide(self.prefix, 1, "accept")[0])
        self.assertTrue(pf.decide(self.prefix, 2, "accept")[0])
        self.assertIn("期中考试和期中的安排", self.srt())
        self.assertIn("我觉得这样可以", self.srt())
        with open(self.prefix + ".校对.json", encoding="utf-8") as fh:
            st = json.load(fh)
        rids = {r["old"]: r["rid"] for r in st["applied"]}
        # 撤销「起中→期中」不能把本来就对的那个「期中」改坏；撤销删字不能把原文插到行首
        self.assertTrue(pf.decide(self.prefix, rids["起中"], "undo")[0])
        self.assertTrue(pf.decide(self.prefix, rids["嗯，"], "undo")[0])
        self.assertIn("期中考试和起中的安排", self.srt())
        self.assertIn("我觉得嗯，这样可以", self.srt())

    def test_ambiguous_accept_is_refused(self):
        st = pf.load_state(self.prefix, pf.read_entries(self.prefix))
        r = pf.add_row(st, "unsure", {"id": 1, "t": 0.0, "who": "我", "old": "中", "new": "钟", "why": "", "by": ""})
        pf.save_state(self.prefix, st)
        ok, msg = pf.decide(self.prefix, r["rid"], "accept")
        self.assertFalse(ok)
        self.assertIn("不止一次", msg)


class DecideAll(unittest.TestCase):
    """「全部采纳」：一次收下剩下的建议；同一行连着改几处，之后每一条都能精确撤销。"""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.prefix = os.path.join(self.dir, "t")
        with open(self.prefix + ".srt", "w", encoding="utf-8") as fh:
            fh.write("1\n00:00:00,000 --> 00:00:01,000\n我：起中考试和真本的安排\n\n"
                     "2\n00:00:01,000 --> 00:00:02,000\n对方：中间的中间\n\n")
        st = pf.new_state()
        row = lambda i, t, old, new: {"id": i, "t": t, "who": "", "old": old, "new": new, "why": "", "by": ""}
        pf.add_row(st, "unsure", row(1, 0.0, "起中", "期中"))       # 同一行两条：前一条长度不变
        pf.add_row(st, "unsure", row(1, 0.0, "真本", "真格基金"))   # 后一条变长
        pf.add_row(st, "unsure", row(2, 1.0, "中间", "终点"))       # 在那一行出现两次：跳过
        pf.add_row(st, "unsure", row(2, 1.0, "不存在", "x"))        # 原文找不到：跳过
        pf.save_state(self.prefix, st)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def srt(self):
        with open(self.prefix + ".srt", encoding="utf-8") as fh:
            return fh.read()

    def state(self):
        with open(self.prefix + ".校对.json", encoding="utf-8") as fh:
            return json.load(fh)

    def test_accepts_what_it_can_and_keeps_the_rest(self):
        ok, msg, done, skipped = pf.decide_all(self.prefix)
        self.assertTrue(ok, msg)
        self.assertEqual((done, skipped), (2, 2))
        self.assertIn("期中考试和真格基金的安排", self.srt())
        self.assertIn("中间的中间", self.srt())
        st = self.state()
        self.assertEqual(sorted(r["old"] for r in st["unsure"]), ["不存在", "中间"])
        self.assertTrue(all(r["by"] == "你" for r in st["applied"]))

    def test_every_accepted_item_undoes_exactly(self):
        pf.decide_all(self.prefix)
        rids = {r["old"]: r["rid"] for r in self.state()["applied"]}
        self.assertTrue(pf.decide(self.prefix, rids["起中"], "undo")[0])     # 先撤前面那条：后面那条的位置要跟着挪
        self.assertIn("起中考试和真格基金的安排", self.srt())
        self.assertTrue(pf.decide(self.prefix, rids["真本"], "undo")[0])
        self.assertIn("起中考试和真本的安排", self.srt())

    def test_undo_needs_the_shifted_position(self):
        # 「甲乙和丙丁」两处都改成「好」，改完是「好和好」：按文字找「好」有两处，只有挪对了的位置能撤销对
        prefix = os.path.join(self.dir, "u")
        with open(prefix + ".srt", "w", encoding="utf-8") as fh:
            fh.write("1\n00:00:00,000 --> 00:00:01,000\n甲乙和丙丁\n\n")
        st = pf.new_state()
        late = pf.add_row(st, "unsure", {"id": 1, "t": 0.0, "who": "", "old": "丙丁", "new": "好", "why": "", "by": ""})
        early = pf.add_row(st, "unsure", {"id": 1, "t": 0.0, "who": "", "old": "甲乙", "new": "好", "why": "", "by": ""})
        pf.save_state(prefix, st)
        self.assertTrue(pf.decide(prefix, late["rid"], "accept")[0])     # 先改后面的
        self.assertTrue(pf.decide(prefix, early["rid"], "accept")[0])    # 再改前面的：后面那条的位置 3 → 2
        read = lambda: open(prefix + ".srt", encoding="utf-8").read()
        self.assertIn("好和好", read())
        self.assertTrue(pf.decide(prefix, late["rid"], "undo")[0])
        self.assertIn("好和丙丁", read())
        self.assertTrue(pf.decide(prefix, early["rid"], "undo")[0])
        self.assertIn("甲乙和丙丁", read())

    def test_nothing_pending(self):
        pf.decide_all(self.prefix)
        st = self.state()
        st["unsure"] = []
        pf.save_state(self.prefix, st)
        ok, msg, done, skipped = pf.decide_all(self.prefix)
        self.assertFalse(ok)
        self.assertEqual(done, 0)


if __name__ == "__main__":
    unittest.main()
