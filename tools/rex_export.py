#!/usr/bin/env python3
"""把一条录音的稿子导出成 Word（.docx）或字幕（.srt）。只用标准库。

    python3 tools/rex_export.py <录音或稿子> docx       # 在录音旁边写 <前缀>.docx
    python3 tools/rex_export.py <录音或稿子> srt        # 字幕本来就有（<前缀>.srt），打印它的路径
    python3 tools/rex_export.py <录音或稿子> docx --out ~/Desktop

由 `rex export` 和录音台的「下载」按钮调用。

- Word 里每一轮一段：灰色的时刻、加粗的名字、说的话。稿子不是对话稿（单人录音）就一行一段。
- 字幕用的就是 rex 一路写好的 <前缀>.srt：分轨对齐过、带名字、校对过（proofread.py 两份一起改）。
  这里不另做一份，免得两份字幕不一致。
- 只读稿子，不改稿子。
"""
import argparse
import io
import os
import re
import shutil
import sys
import zipfile
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from i18n import L  # noqa: E402

MIME = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "srt": "application/x-subrip; charset=utf-8"}
TURN = re.compile(r"^\[([0-9:]+)\] ([^：]{1,12})：(.*)$", re.S)
AUDIO = re.compile(r"(-mic|-sys)?\.(m4a|wav|mp3|aac|flac|ogg|opus|caf|aiff?|qta|mp4|m4v|mov|webm)$", re.I)
# 本工具起的名字：日期_时刻_来源[-分轨][_关键词]。录音台的列表（rex_app.py）、手机页、Word 的标题都按它认
NAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})?_(mic|sys|both|phone|drop-[^_]*)"
                  r"(?:-(mic|sys))?(?:_(.+))?$")
# 来源只是显示用的标签，跟着界面语言走。app.js 拿它比较时用同一对中英文（T('导入', 'Imported')），别在一边单改
SOURCE = {"mic": L("麦克风", "Microphone"), "sys": L("电脑声音", "Computer audio"), "both": L("通话", "Call"),
          "phone": L("手机", "Phone")}
# XML 1.0 不许出现的控制字符：稿子里混进一个，整份 Word 就打不开
XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def prefix_of(path):
    """录音文件、.txt、.srt 或者前缀本身 → 前缀（不带扩展名）。"""
    p = AUDIO.sub("", path)
    for ext in (".whisper.srt", ".srt", ".txt", ".docx"):
        if p.endswith(ext):
            return p[: -len(ext)]
    return p


def read_turns(txt_path):
    """→ [(时刻或 None, 名字或 None, 文字)]。对话稿按「[时刻] 名字：」拆，别的一段一行。"""
    with open(txt_path, encoding="utf-8") as fh:
        raw = fh.read()
    out = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        block = block.strip()
        if not block:
            continue
        m = TURN.match(block)
        if m:
            out.append((m.group(1), m.group(2), m.group(3).strip()))
        else:
            out.extend((None, None, ln.strip()) for ln in block.splitlines() if ln.strip())
    return out


def _run(text, bold=False, grey=False, size=None):
    props = ""
    if bold:
        props += "<w:b/>"
    if grey:
        props += '<w:color w:val="808080"/>'
    if size:
        props += '<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (size, size)
    rpr = "<w:rPr>%s</w:rPr>" % props if props else ""
    # 一轮里的换行要写成 <w:br/>：直接留在 <w:t> 里，Word 当它是空格
    lines = XML_BAD.sub("", text).split("\n")
    return "<w:r>%s%s</w:r>" % (rpr, "<w:br/>".join('<w:t xml:space="preserve">%s</w:t>' % escape(ln) for ln in lines))


def _para(runs, after=120):
    return '<w:p><w:pPr><w:spacing w:after="%d"/></w:pPr>%s</w:p>' % (after, "".join(runs))


def docx_bytes(title, subtitle, turns):
    body = [_para([_run(title, bold=True, size=32)], 60)]
    if subtitle:
        body.append(_para([_run(subtitle, grey=True, size=20)], 240))
    for t, who, text in turns:
        runs = []
        if t:
            runs.append(_run("[%s] " % t, grey=True, size=18))
        if who:
            runs.append(_run(who + "：", bold=True))
        runs.append(_run(text))
        body.append(_para(runs))
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body>%s<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
           '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
           '</w:sectPr></w:body></w:document>') % "".join(body)
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/word/document.xml" '
             'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def parse_name(key):
    m = NAME.match(key)
    if not m:
        return None
    y, mo, d, hh, mm, ss, src, track, kw = m.groups()
    if src.startswith("drop-"):
        source, origin = L("导入", "Imported"), src[5:]
    else:
        source, origin = SOURCE.get(src, src), ""
    kw = (kw or "").replace("-", " · ")
    # 导入的文件用原名当标题：那是用户自己起的（比如「某某项目介绍会」），比自动抽的关键词有用
    return {"when": "%s-%s-%s %s:%s" % (y, mo, d, hh, mm), "source": source, "origin": origin, "kw": kw,
            "title": (origin.replace("-", " ") if origin and origin != "drop" else "") or kw or source}


def title_of(prefix):
    """→（标题, 录音时间）：和录音台列表里显示的一样（手机录的是「手机录音 1430」，不是整个文件名）。
    不是本工具起的名字就用文件名。"""
    name = os.path.basename(prefix)
    info = parse_name(name)
    return (info["title"], info["when"]) if info else (name, "")


def disposition(filename):
    """下载用的 Content-Disposition。中文文件名按 RFC 5987 编码，旧浏览器退回一个 ASCII 名字。"""
    import urllib.parse
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename) or "transcript"
    return "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (ascii_name, urllib.parse.quote(filename))


def export(path, fmt, out_dir=None):
    """→ 导出文件的路径。没有稿子就抛 FileNotFoundError。"""
    prefix = prefix_of(path)
    if fmt == "srt":
        src = prefix + ".srt"
        if not os.path.exists(src):
            raise FileNotFoundError(src)
        if out_dir:
            dest = os.path.join(out_dir, os.path.basename(src))
            shutil.copyfile(src, dest)
            return dest
        return src
    if fmt != "docx":
        raise ValueError(fmt)
    txt = prefix + ".txt"
    if not os.path.exists(txt):
        raise FileNotFoundError(txt)
    title, sub = title_of(prefix)
    data = docx_bytes(title, sub, read_turns(txt))
    dest = os.path.join(out_dir or os.path.dirname(prefix) or ".", os.path.basename(prefix) + ".docx")
    tmp = dest + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, dest)
    return dest


def main():
    ap = argparse.ArgumentParser(description=L("把稿子导出成 Word 或字幕", "Export a transcript as Word or subtitles"))
    ap.add_argument("path")
    ap.add_argument("fmt", nargs="?", default="docx", choices=["docx", "srt"])
    ap.add_argument("--out", help=L("写到哪个文件夹（默认录音旁边）", "Folder to write to (default: next to the recording)"))
    a = ap.parse_args()
    try:
        dest = export(a.path, a.fmt, os.path.expanduser(a.out) if a.out else None)
    except FileNotFoundError as e:
        print(L("没有稿子：%s。先 rex text 或 rex go。", "No transcript: %s. Run rex text or rex go first.") % e.args[0])
        return 1
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
