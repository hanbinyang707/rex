"""rex 的输出语言（中文 / 英文）。

rex.sh 开头已经把 REX_LANG 解析好并导出，从它起的脚本直接拿；单独跑某个脚本时按同样的规矩自己判：
REX_LANG=en|zh → ~/.config/rex/lang → macOS 首选语言（中文 → zh，其余 → en）。

    from i18n import L, EN
    log(L("转写完了", "Transcription finished"))
"""
import os
import subprocess


def _resolve():
    v = os.environ.get("REX_LANG", "")
    if v in ("en", "zh"):
        return v
    try:
        with open(os.path.expanduser("~/.config/rex/lang"), encoding="utf-8") as fh:
            v = fh.read().strip()
        if v in ("en", "zh"):
            return v
    except OSError:
        pass
    try:
        out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True,
                             timeout=5).stdout
        first = out.replace("(", "").replace('"', "").replace(" ", "").replace("\n", "").split(",")[0]
        return "zh" if first.startswith("zh") else "en"
    except (OSError, subprocess.SubprocessError):
        return "en"


LANG = _resolve()
EN = LANG == "en"


def L(zh, en):
    """中文在前、英文在后，按当前语言挑一个。"""
    return en if EN else zh
