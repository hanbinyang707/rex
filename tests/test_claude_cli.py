"""claude_cli：给 claude 命令行准备的环境（清掉别家接口的变量、照系统代理补上代理）和账户层面报错的认法。不调 claude。

2026-10-17 起收件箱和常驻录音台（都是 launchd 起的，环境里没有 HTTPS_PROXY）的校对、分析全部
「Failed to authenticate. API Error: 403 Request not allowed」：claude 不读系统代理，在国内直连被拒。

    python3 -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

os.environ["HOME"] = tempfile.mkdtemp()
os.environ["REX_LANG"] = "zh"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import claude_cli  # noqa: E402

PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy",
              "NO_PROXY", "no_proxy", "REX_CLAUDE_ENV")
SYSTEM = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897", "socks": "http://127.0.0.1:7897"}


class Env(unittest.TestCase):
    def setUp(self):
        self.saved = dict(os.environ)
        for k in PROXY_VARS:
            os.environ.pop(k, None)
        self.req = claude_cli.urllib.request
        self.had = hasattr(self.req, "getproxies_macosx_sysconf")
        self.real = getattr(self.req, "getproxies_macosx_sysconf", None)
        self.system = dict(SYSTEM)
        self.req.getproxies_macosx_sysconf = lambda: self.system

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)
        if self.had:
            self.req.getproxies_macosx_sysconf = self.real
        else:
            del self.req.getproxies_macosx_sysconf

    def test_launchd_like_env_gets_the_system_proxy(self):
        e = claude_cli.env()
        self.assertEqual(e["HTTPS_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(e["HTTP_PROXY"], "http://127.0.0.1:7897")
        self.assertEqual(e["NO_PROXY"], "localhost,127.0.0.1,::1")

    def test_a_proxy_already_in_the_environment_wins(self):
        os.environ["https_proxy"] = "http://10.0.0.2:3128"
        e = claude_cli.env()
        self.assertEqual(e["https_proxy"], "http://10.0.0.2:3128")
        self.assertNotIn("HTTPS_PROXY", e)
        self.assertNotIn("HTTP_PROXY", e)

    def test_no_system_proxy_means_no_proxy_vars(self):
        self.system = {}
        e = claude_cli.env()
        self.assertFalse({"HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"} & set(e))

    def test_own_no_proxy_is_kept(self):
        os.environ["NO_PROXY"] = "corp.example"
        self.assertEqual(claude_cli.env()["NO_PROXY"], "corp.example")

    def test_other_provider_settings_are_still_stripped(self):
        os.environ["ANTHROPIC_BASE_URL"] = "https://other.example"
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "x"
        e = claude_cli.env()
        self.assertFalse([k for k in e if k.startswith("ANTHROPIC_")])
        self.assertIn("HTTPS_PROXY", e)

    def test_inherit_keeps_everything_as_is(self):
        os.environ["REX_CLAUDE_ENV"] = "inherit"
        self.assertIsNone(claude_cli.env())


class Account(unittest.TestCase):
    def test_403_request_not_allowed_stops_at_once_and_says_why(self):
        msg = claude_cli.account_error("Failed to authenticate. API Error: 403 Request not allowed")
        self.assertIsNotNone(msg)
        self.assertIn("代理", msg)

    def test_a_403_inside_normal_text_is_not_an_error_by_itself(self):
        # 「API Error:」后面紧跟的才算；普通回答里出现 403 不算
        self.assertIsNone(claude_cli.account_error("第 403 行改好了"))


if __name__ == "__main__":
    unittest.main()
