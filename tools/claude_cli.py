#!/usr/bin/env python3
"""rex go 怎么调本机的 claude 命令行。proofread.py 和 analyze.py 共用，判据只写这一份。

## 为什么要清掉 ANTHROPIC_* 环境变量

不少人在 ~/.zshrc 里 export 了 ANTHROPIC_BASE_URL（指向别家的 Anthropic 兼容接口）、
ANTHROPIC_AUTH_TOKEN 和一组模型名：这时在终端里敲 claude，回话的其实是那一家。
作者 2026-10-12 第一次真跑就撞上了：从终端起的 `rex go` 31 份校对全部 `API Error: 402 Insufficient
Balance`——那是那一家账户的余额；同一时刻收件箱（launchd 不读 ~/.zshrc）走的是命令行
自己的 Claude 登录。**同一条命令，从哪儿起决定了稿子发给谁**，而且不报错。

要的是「拿 Claude 校对」，手册和隐私说明写的也是 Claude，所以默认把这些变量清掉，
让 claude 命令行用它自己的登录。真想沿用终端里的设置：REX_CLAUDE_ENV=inherit。

## 在空目录里跑：别把工作目录的 CLAUDE.md 带进去

命令行会把工作目录（一路往上）的 CLAUDE.md 自动塞进上下文。作者从自己的仓库里起 `rex go` 时，那是 87 KB 的交接
说明，每一份校对都背着：2026-10-12 同样 20 行实测，送进去 43306 token；换到空目录、规则改用
--system-prompt 之后是 1716。所以校对在 `neutral_dir()` 里跑。分析在 ~/Recordings 里跑（会话存在那儿，
`claude --resume` 要在那个目录），那里没有 CLAUDE.md。

## 用量记账

每次调用的 usage 都记下来，`usage_note()` 给报告写一行：几次调用、送进去多少、输出多少、折合 API 价。
Max 订阅不按这个价收钱，它只是一把衡量「这次用了多少额度」的尺子。

## 账户层面的失败要立刻停

没登录、没余额、到了用量上限：一份撞上，其余的份也一样。命令行自己会先重试好几分钟才放弃，
第一次真跑时 31 份就这么一份份白等。所以认出这类错误就抛 AccountError，调用方杀掉还在跑的
那几份、不再发新的。
"""

import json
import os
import re
import subprocess
import threading

from i18n import EN, L

STRIP_PREFIX = "ANTHROPIC_"
STRIP = {"CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_SUBAGENT_MODEL",
         "CLAUDE_CODE_EFFORT_LEVEL"}

# (正则, 给人看的说明)。只在命令行报错时才拿来认，正常的回答里出现这些词不算
# 登录要用 `rex login`，不能叫人「跑 claude 再 /login」：终端里的 claude 带着别家接口的设置
# 起来，根本不会让你登 Claude 账号（实测 `claude auth status` 清掉那些变量之后才是 loggedIn: false）
# 状态码只认紧跟在「API Error:」后面的：崩溃栈里的 cli.js:402:15、「401 ms」都曾被当成账户错误（2026-10-13
# 复核实测）。429（rate limit）和 Context limit 不算账户级：那是可以重试的单份失败
ACCOUNT = [
    (r"Not logged in|Please run /login|Invalid API key",
     L("claude 命令行还没登录 Claude 账号：终端里跑 rex login",
       "The claude CLI isn't logged in to a Claude account: run rex login in a terminal")),
    (r"API Error: 402\b|Insufficient Balance|credit balance is too low",
     L("账户余额不足", "Account balance too low")),
    (r"usage limit reached|hit your (session|usage|weekly|monthly) limit|out of extra usage",
     L("到了用量上限", "Usage limit reached")),
    (r"API Error: 401\b|invalid x-api-key|authentication_error",
     L("登录失效：终端里跑 rex login 重新登录", "Login expired: run rex login in a terminal to log in again")),
]


class AccountError(Exception):
    """Claude 这边整体用不了。args[0] 是给人看的一句话。"""


_live = set()
_lock = threading.Lock()
_abort = threading.Event()
_used = {"calls": 0, "in": 0, "out": 0, "cost": 0.0, "models": set()}
NEUTRAL = os.path.expanduser("~/.cache/rex/claude")


def neutral_dir():
    """一个不带 CLAUDE.md 的空目录（往上到家目录也没有），校对在这里跑。"""
    os.makedirs(NEUTRAL, exist_ok=True)
    return NEUTRAL


def tally(obj):
    u = obj.get("usage") or {}
    with _lock:
        _used["calls"] += 1
        _used["in"] += sum(int(u.get(k) or 0) for k in
                           ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        _used["out"] += int(u.get("output_tokens") or 0)
        _used["cost"] += float(obj.get("total_cost_usd") or 0)
        _used["models"].update((obj.get("modelUsage") or {}).keys())


def models():
    return L("、", ", ").join(sorted(_used["models"])) or L("claude 命令行默认模型", "the claude CLI's default model")


def wan(n):
    if EN:                              # 英文没有「万」：12.3k、1.2M
        if n >= 1000000:
            return "%.1fM" % (n / 1000000.0)
        return "%.1fk" % (n / 1000.0) if n >= 10000 else str(n)
    return "%.1f 万" % (n / 10000.0) if n >= 10000 else str(n)


def usage_numbers():
    """这个进程里所有调用加起来：{calls, in, out, cost}。拿不到 usage 时是空字典。"""
    if not _used["calls"] or not (_used["in"] or _used["out"]):
        return {}
    return {k: _used[k] for k in ("calls", "in", "out", "cost")}


def usage_text(u):
    """{calls, in, out, cost} → 「9 次调用 · 送进去 12.3 万 token · 输出 4.5 万 · 折合 API 价约 $3.20」。
    usage_note() 和校对报告（几次运行加起来）共用这一种写法。"""
    if EN:
        return "%d %s · %s tokens in · %s out · about $%.2f at API prices" % (
            u["calls"], "call" if u["calls"] == 1 else "calls", wan(u["in"]), wan(u["out"]), u["cost"])
    return "%d 次调用 · 送进去 %s token · 输出 %s · 折合 API 价约 $%.2f" % (
        u["calls"], wan(u["in"]), wan(u["out"]), u["cost"])


def usage_note():
    """「9 次调用 · 送进去 12.3 万 token · 输出 4.5 万 · 折合 API 价约 $3.20」，没调用过就是空串。"""
    u = usage_numbers()
    if not u:
        return ""                       # 没拿到 usage 就不写，免得写成「0 token」
    return usage_text(u)


def env():
    if os.environ.get("REX_CLAUDE_ENV") == "inherit":
        return None
    return {k: v for k, v in os.environ.items() if not k.startswith(STRIP_PREFIX) and k not in STRIP}


def account_error(text):
    for pat, msg in ACCOUNT:
        if re.search(pat, text, re.I):
            return L("%s（%s）", "%s (%s)") % (msg, text.strip().splitlines()[0][:100]) if text.strip() else msg
    return None


def kill_all():
    """账户出错时把其余还在跑的 claude 停掉，不然它们各自重试几分钟才退。之后也不再起新的。"""
    _abort.set()
    with _lock:
        for p in list(_live):
            try:
                p.kill()
            except OSError:
                pass


def run(args, text, timeout, cwd=None):
    """跑一次 `claude -p --output-format json …`，返回结果对象。

    账户层面的失败抛 AccountError，别的失败抛 RuntimeError。"""
    if _abort.is_set():
        raise RuntimeError(L("已经停下了", "Already stopped"))
    p = subprocess.Popen(["claude", "-p", "--output-format", "json"] + args, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd, env=env())
    with _lock:
        _live.add(p)
        if _abort.is_set():          # 刚起来就赶上停：别让它跑完一整份
            p.kill()
    try:
        out, err = p.communicate(text, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        raise RuntimeError(L("等了 %d 秒没回来", "No reply after %d seconds") % timeout)
    finally:
        with _lock:
            _live.discard(p)
    try:
        obj = json.loads(out)
    except ValueError:
        # 两边的尾巴都带上：stderr 有东西不等于 stdout 里没有真正的错误
        msg = L("；", "; ").join(t for t in ((err or "").strip()[-300:], (out or "").strip()[-300:]) if t) \
            or L("（被停掉了，没有输出）", "(stopped, no output)")
        why = account_error(msg)
        if why:
            raise AccountError(why)
        raise RuntimeError(L("claude 没返回 JSON：%s", "claude didn't return JSON: %s") % msg)
    res = (obj.get("result") or "").strip()
    if obj.get("is_error") or re.match(r"(API Error|Not logged in|Invalid API key)", res):
        tally(obj)                      # 报错的那次也花了额度，照记
        detail = res or json.dumps({k: obj.get(k) for k in ("subtype", "errors") if obj.get(k)}, ensure_ascii=False)
        why = account_error(detail)
        if why:
            raise AccountError(why)
        raise RuntimeError(L("claude 报错：%s", "claude reported an error: %s")
                           % (detail or L("（没有说明）", "(no details)"))[-300:])
    tally(obj)
    return obj
