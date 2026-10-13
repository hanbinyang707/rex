#!/usr/bin/env bash
# rex —— 一行开始、一行结束的录音器。麦克风、系统声音、或者两个一起。
#
#   rex                 录麦克风（正在录的时候再跑一次 = 停，方便绑成一个快捷键）
#   rex sys             录系统声音：播客、视频、网页里正在放的任何东西
#   rex both            麦克风 + 系统声音。一个文件，听的是混音，里面两路各存一条轨
#   rex both --split    同上，但存成两个文件
#   rex stop            停
#   rex text            把最近一次录音转写成文字（whisper，全程本地）
#                       rex both 录的出对话稿：「我」= 麦克风，「对方」= 系统声音
#   rex text <文件>     转写指定的音频文件
#   rex phone           列出 iPhone 语音备忘录（iCloud 同步过来的）
#   rex phone 1         取第 1 条，拷进 ~/Recordings/ 并转写
#   rex in              列出 ~/Downloads / ~/Desktop 里可转的音视频（AirDrop 落点）
#   rex in 1 / rex in all   转其中一个 / 全部。只拷贝，绝不动原件
#   rex url <链接>      下播客单集音频（小宇宙等）并转写。只认页面里公开的音频地址
#   rex trim [文件]     切掉末尾的空白（忘了停的那段）。原件进废纸篓，不删
#   rex go [文件]       一条龙：转写 → 分人 → Claude 校对（报告改了哪里）→ Claude 分析
#                       （留一个 claude --resume 能接着聊的会话）。不给文件就是最近一条
#   rex auto install    盯着 ~/Recordings/收件箱，丢进去的录音自动走 rex go
#   rex auto [status|open|uninstall]     （rex inbox 是 rex in 的别名，不是这个）
#   rex login [status]  登录 Claude 账号，rex go 的校对和分析用它（终端里的 claude 设置不受影响）；status 看登上没有
#   rex chat [文件]     接着和那条录音的分析会话聊（不给就是最近一条有分析的）
#   rex app             打开录音台：本地网页界面，录音、处理、逐条确认校对、接着问都在里面
#   rex app stop|status|restart
#   rex who [文件] [人数]   按声纹分人：一个麦克风录的多人谈话、2026-10-11 之前的 rex both。
#                       已经转写过的不重转；不给文件就是最近一条。人数不给就自动判
#   rex trim 文件 --to 49:30   手动指定只保留到哪里
#   rex check           用麦克风录 3 秒扔掉，只看有没有真的收到信号（怀疑录空时先跑这个；
#                       第一次会弹麦克风授权框，点允许）
#   rex check sys       放一声测试音，用系统音频接口录；收到了就把它设成录电脑声音的默认
#                       （不改输出设备，AirPods 自动切换也不断；第一次弹「仅系统录音」授权框，点允许。
#                       接口不通就再用 BlackHole 那条老路放一次测试音）
#   rex status          在录吗？录了多久？真的收到声音了吗？
#   rex ls              最近十次录音
#   rex find <词>       在转写稿和登记过的文档里找；不给词就列出全部稿子
#                       （额外的文档目录一行一个写在 ~/.config/rex/text-dirs）
#   rex open            在访达里打开录音文件夹
#   rex devices         有哪些麦克风和输出设备，现在默认用的是哪个
#
#   --wav               录成 24bit WAV（默认 AAC/m4a）。要拿去做音频分析时用
#   --device "名字"     指定麦克风，比如 --device "AirPods Pro"
#   --lang zh|en|auto   转写语言，默认 auto
#   --no-vad            关掉人声检测。默认开着，用来挡 whisper 在静音上的幻觉
#   --no-rename         转写完不按关键词改名，保持时间戳名字
#   --names 我,老师     对话稿里两边叫什么（前一个是麦克风那边），默认「我,对方」
#   --who [人数]        （text）转写完顺手按声纹分人，同 rex who
#   --to 49:30          （trim）只保留到这个时间
#   --dry-run           （trim）只报告会切多少，不动文件
#
#   REX_WATCH=秒数      看门狗逐路自查的间隔，默认 180；设 0 关掉（录音自己停了的收尾关不掉）
#   REX_NAMES=我,老师   --names 的默认值
#   REX_MAX=秒数        最长录多久，默认 21600（6 小时）
#   REX_DIR=目录        录音存哪，默认 ~/Recordings
#   REX_SYS=tap|blackhole   录电脑声音走哪条路，临时覆盖 rex check sys 的结果
#   REX_APP_PORT=端口   录音台的端口，默认 8790
#
# 文件一律落在 ~/Recordings/，名字形如 2026-08-16_143052_sys.m4a。
# 转写结果就放在音频旁边，同名的 .txt 和 .srt。
#
# ------------------------------------------------------------------ 几条踩过的事
#
# · 耳机得能一直用。录系统声音必须让声音同时进 BlackHole 和你的耳机，办法是
#   走「多输出设备」。但「音频 MIDI 设置」里手建的那个是**写死成员**的，换一副
#   耳机就失效、声音会突然从笔记本喇叭出来。所以这里按**你此刻正在用的输出设备**
#   现建一个，停止时删掉。如果你当前输出本来就是个含 BlackHole 的多输出设备，
#   那就一个字都不动，直接录。
#
# · avfoundation 要的是设备**索引号**，而索引会随着插拔耳机、开关虚拟设备而变。
#   所以每次录之前都重新枚举、按名字匹配，绝不硬编码。
#
# · 蓝牙耳机的麦克风一被打开，耳机就整个掉进 HFP 免提模式：采样率从 48k 掉到
#   24k，播放质量当场变糊。所以 `rex mic` 跟随你在系统里选的输入设备（你选了
#   耳机就用耳机），但 `rex both` 默认改用内建麦克风——那个模式下正在录的
#   系统声音会被一起拖糊，代价太大。想坚持用耳机麦克风就显式 --device。
#
# · m4a 的索引（moov）是在文件末尾写的。所以 stop 用 SIGINT 让 ffmpeg 自己收尾，
#   并且**等它真的退出**。硬杀会得到一个打不开的文件。
#
# · 起录之后不靠 sleep 猜设备开没开，盯 ffmpeg 的进度输出等第一行 size=。
#   等不到多半是权限。授权记在 audiocap 自己头上，不是终端（audiocap.swift「权限：自己负责」一节）。
#
# · 判「什么都没录到」看**峰值**不看均值：安静房间里麦克风均值 -68 dB 很正常，
#   拿均值当判据会天天误报；链路真断了是数字静音，峰值和均值一起趴到 -91。
#
# · 【改这个文件必看】变量后面紧跟中文字符，一定要写成 ${var}。
#   macOS 只有 bash 3.2，它判断变量名结尾用的是 isalnum()，而 isalnum() 认
#   locale——在 UTF-8 locale 下会把「）」「」」这类全角字符的字节吞进变量名：
#
#     $ LANG=en_US.UTF-8 bash -c 'set -u; x=hi; echo "（$x）"'
#     bash: x<0xef>: unbound variable        ← 报的是 x 加半个全角括号
#     $ LC_CTYPE=C       bash -c 'set -u; x=hi; echo "（$x）"'   # 同一句
#     （hi）                                  ← 一切正常
#
#   这条真踩过：写完自测全过，作者一跑就崩，因为我的 shell 是 LC_CTYPE=C，
#   而正常终端是 UTF-8。**改完至少在 UTF-8 locale 下跑一遍。**
#   扫全文的办法：grep -nP '\$(?!\{)[A-Za-z_]\w*[^\x00-\x7F]' rex.sh（-P 要 ugrep 或 GNU grep，系统自带的没有）

set -uo pipefail

REX_DIR="${REX_DIR:-$HOME/Recordings}"
STATE="$REX_DIR/.current"
LOG="$REX_DIR/.ffmpeg.log"
CAP_DIR="$REX_DIR/.cap"     # audiocap → ffmpeg 的命名管道放这里
MAX_SECONDS="${REX_MAX:-21600}"   # 6 小时保险丝，防止忘了停把盘写满；用 REX_MAX 改

# 顺着符号链接找到真身，因为 ~/.local/bin/rex 只是个软链，
# 而 audiodev 的源码和二进制在仓库里。
SELF="${BASH_SOURCE[0]}"
if [ -L "$SELF" ]; then
  SELF=$(readlink -f "$SELF" 2>/dev/null) \
    || SELF=$(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")
fi
TOOLS_DIR=$(cd "$(dirname "$SELF")" && pwd)
AD_SRC="$TOOLS_DIR/audiodev.swift"
AD="$TOOLS_DIR/.bin/audiodev"
CAP_SRC="$TOOLS_DIR/audiocap.swift"
CAP_PLIST="$TOOLS_DIR/audiocap-Info.plist"   # 程序名和麦克风/系统声音的用途说明，链接进二进制，弹授权框要用
CAP="$TOOLS_DIR/.bin/audiocap"

# whisper。模型不进仓库（547 MB），放缓存目录，缺了就现下。
# large-v3-turbo 是蒸馏过解码器的版本：比 large-v3 快好几倍，中文识别几乎没退步。
WMODEL="${WHISPER_MODEL:-$HOME/.cache/whisper/ggml-large-v3-turbo-q5_0.bin}"
WURL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin"
# 词表和确定性替换是每个人自己的：放 ~/.config/rex/ 下（不进仓库，git pull 也冲不掉），没有才用仓库里的空模板
WPROMPT="$HOME/.config/rex/whisper-prompt.txt"; [ -f "$WPROMPT" ] || WPROMPT="$TOOLS_DIR/whisper-prompt.txt"
WFIX="$HOME/.config/rex/whisper-fix.txt"; [ -f "$WFIX" ] || WFIX="$TOOLS_DIR/whisper-fix.txt"
# VAD（人声检测，864 KB）。默认开着，因为 whisper 在近似静音上会**编**东西：
# 实测一条只有环境底噪的轨被转成「中文字幕:王智英 李宗盛」——训练数据里混了
# 带字幕的视频，模型学会了在没内容的时候吐片尾字幕。空轨产出自信的垃圾比
# 什么都不产出更糟，所以宁可先用 VAD 把没人说话的段落整段跳过。
VMODEL="${WHISPER_VAD_MODEL:-$HOME/.cache/whisper/ggml-silero-v5.1.2.bin}"
VURL="https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin"
# 边缘留白。VAD 切静音会啃掉词尾——实测默认 30ms 时「对照着看」变成
# 「对照者看」，给到 200ms 就和不开 VAD 的结果完全一致了。
VPAD=200

C_R=$'\033[31m'; C_Y=$'\033[33m'; C_G=$'\033[32m'; C_D=$'\033[2m'; C_0=$'\033[0m'
if [ ! -t 1 ]; then C_R=""; C_Y=""; C_G=""; C_D=""; C_0=""; fi

say()  { printf '%s\n' "$*"; }
warn() { printf '%s%s%s\n' "$C_Y" "$*" "$C_0"; }
die()  { printf '%s错误：%s%s\n' "$C_R" "$*" "$C_0" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "找不到 $1。安装：$2"; }

# audiodev 是本仓库的 Swift 小工具，源码比二进制新就重编。
ensure_ad() {
  if [ ! -x "$AD" ] || [ "$AD_SRC" -nt "$AD" ]; then
    need swiftc "装 Xcode 命令行工具：xcode-select --install"
    mkdir -p "$(dirname "$AD")"
    say "${C_D}编译 audiodev…${C_0}"
    swiftc -O -o "$AD" "$AD_SRC" || die "编译 audiodev 失败"
  fi
}

ensure_cap() {
  if [ ! -x "$CAP" ] || [ "$CAP_SRC" -nt "$CAP" ] || [ "$CAP_PLIST" -nt "$CAP" ]; then
    need swiftc "装 Xcode 命令行工具：xcode-select --install"
    mkdir -p "$(dirname "$CAP")"
    say "${C_D}编译 audiocap…${C_0}"
    # Info.plist 链接进二进制，再用 codesign 重签一次把它绑进签名：macOS 弹授权框时从签名里读程序名
    # 和用途说明，链接器自带的 ad-hoc 签名不绑 Info.plist（codesign -dvvv 看到 Info.plist=not bound）。
    # 重编之后 cdhash 变了，系统会把它当新程序，麦克风/系统声音要重新授权一次（audiocap.swift「权限」一节）
    # 编到临时文件、签完再原子换上：中途失败不留一个「比源码新、却没绑 Info.plist」的半成品（那样不会再重编，
    # 系统也不弹授权框）；录音中 rex check 触发重编也不会把正在跑的二进制换掉
    swiftc -O -o "$CAP.tmp.$$" "$CAP_SRC" \
      -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$CAP_PLIST" || { rm -f "$CAP.tmp.$$"; die "编译 audiocap 失败"; }
    codesign -s - -f "$CAP.tmp.$$" 2>/dev/null || { rm -f "$CAP.tmp.$$"; die "签名 audiocap 失败"; }
    mv -f "$CAP.tmp.$$" "$CAP"
    warn "audiocap 重编了：下次录音 / rex check 会再问一次麦克风和系统声音的授权（授权记在它自己头上）"
  fi
}

# 起一路采集：audiocap 用 CoreAudio 直读设备 → 命名管道 → ffmpeg。
# **采集不交给 ffmpeg 的 avfoundation**——它会静默丢掉约 14% 的采样（2026-09-22
# 查出来的，对照数据和来龙去脉在 audiocap.swift 文件头）。
# 往 in_args 追加对应的 ffmpeg 输入参数，PID 记进 caps，实际录的设备名记进 CAPNAME_<tag>。
add_capture() {
  pat="$1"; tag="$2"
  if [ "$pat" = "--system" ] && [ -n "${SYS_INFO:-}" ]; then
    info="$SYS_INFO"                      # sys_setup 刚探过
  else
    # stderr 单独收：audiocap 的「等你点允许」「被拒绝了」都写在那儿，混进 info 的话 ffmpeg 的 -ar 就成了一句中文
    # （重编 audiocap 之后第一次开录必然撞上）。出错把它原样报出来，成功也打给人看
    ie="$CAP_DIR/$tag.info.err"
    if ! info=$("$CAP" "$pat" --info 2>"$ie"); then
      msg=$(cat "$ie" 2>/dev/null); stop_caps; teardown_passthru "$PT_RESTORE" "$PT_UID"; die "${msg:-audiocap --info 失败}"
    fi
    [ -s "$ie" ] && cat "$ie" >&2
  fi
  info=$(printf '%s\n' "$info" | grep -E '^[0-9]+ [0-9]+ ' | head -1)
  [ -n "$info" ] || { stop_caps; teardown_passthru "$PT_RESTORE" "$PT_UID"; die "audiocap 没报出「采样率 声道 名字」（$(cat "${ie:-/dev/null}" 2>/dev/null | tail -1)）"; }
  r=$(printf '%s' "$info" | awk '{print $1}')
  c=$(printf '%s' "$info" | awk '{print $2}')
  eval "CAPNAME_${tag}=\$(printf '%s' \"\$info\" | cut -d' ' -f3-)"
  fifo="$CAP_DIR/$tag.f32"
  mkfifo "$fifo" || { stop_caps; teardown_passthru "$PT_RESTORE" "$PT_UID"; die "建不了命名管道 $fifo"; }
  # 打开 FIFO 的写端会阻塞到 ffmpeg 来读，所以放后台；$! 在 exec 之后就是 audiocap 本身
  nohup "$CAP" "$pat" --level "$CAP_DIR/$tag.level" > "$fifo" 2>>"$LOG" &
  caps="$caps $!"
  in_args+=( -f f32le -ar "$r" -ac "$c" -i "$fifo" )
}

stop_caps() {
  # 发 TERM 不发 INT：还卡在打开命名管道那一步、没 exec 成 audiocap 的后台子 shell 忽略 INT（非交互 bash 的后台作业
  # 都这样），TERM 才收得掉；audiocap 对 TERM 和 INT 一样处理（写完缓冲再退）
  for c in ${caps:-} $(getf caps 2>/dev/null); do kill -TERM "$c" 2>/dev/null; done
  rm -rf "$CAP_DIR"
}

# ------------------------------------------------------------------ 设备

# 在 avfoundation 的音频设备表里按名字（当正则用）找索引号。
avf_index() {
  ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 | awk -v want="$1" '
    /AVFoundation audio devices/ { a=1; next }
    /AVFoundation video devices/ { a=0 }
    a && match($0, /\[[0-9]+\] /) {
      idx  = substr($0, RSTART+1, RLENGTH-3)
      name = substr($0, RSTART+RLENGTH)
      if (tolower(name) ~ tolower(want)) { print idx; exit }
    }'
}

avf_name() {
  ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 | awk -v want="$1" '
    /AVFoundation audio devices/ { a=1; next }
    /AVFoundation video devices/ { a=0 }
    a && match($0, /\[[0-9]+\] /) {
      idx  = substr($0, RSTART+1, RLENGTH-3)
      if (idx == want) { print substr($0, RSTART+RLENGTH); exit }
    }'
}

is_bluetooth_in() { "$AD" list-in | awk -F'\t' -v n="$1" '$3==n && $2=="bluetooth" {f=1} END{exit !f}'; }

# 笔记本合着盖吗。台式机没有这个键，找不到就当没合。
# **不能写成 ioreg | grep -q**：本文件开着 pipefail，grep -q 一匹配就退出，ioreg 的输出
# 比管道缓冲大、还在写，吃一个 SIGPIPE，整条管道就判失败——永远报「没合盖」。
# 第一版就是这么写的，交互式 shell 里试是好的（那里没开 pipefail），进了脚本就哑了。
lid_closed() {
  case "$(ioreg -r -k AppleClamshellState -d 4 2>/dev/null)" in
    *'"AppleClamshellState" = Yes'*) return 0 ;;
  esac
  return 1
}

# 选麦克风。mode 决定默认值，理由见文件头第三条。
mic_pattern() {
  mode="$1"; want="${MIC_DEV:-}"

  if [ -z "$want" ]; then
    if [ "$mode" = "both" ]; then
      want="MacBook.*Microph"
      [ -n "$(avf_index "$want")" ] || want="Built-in Microph"
      [ -n "$(avf_index "$want")" ] || want=$("$AD" default-in)
    else
      want=$("$AD" default-in)      # 跟随你在系统里选的那个
    fi
  fi
  printf '%s' "$want"
}

pick_mic() {
  want=$(mic_pattern "$1")
  i=$(avf_index "$want")
  [ -n "$i" ] || die "找不到叫「${want}」的麦克风。跑 rex devices 看看有哪些。"
  printf '%s' "$i"
}

# ------------------------------------------------------------------ 输出直通

# 让系统声音同时进 BlackHole 和你正在用的那个耳机/喇叭。
# 回声两行：restore_uid（要切回去的设备）和 passthru_uid（临时建的，要删掉）。
setup_passthru() {
  bh=$("$AD" list | awk -F'\t' 'tolower($3) ~ /blackhole/ { print $1; exit }')
  [ -n "$bh" ] || die "系统里没有 BlackHole。装：brew install blackhole-2ch（装完要重启一次）"

  cur=$("$AD" default) || die "读不到当前输出设备"

  # 当前输出本来就带着 BlackHole（比如你手建的 Multi-Output Device 正在用），
  # 那就什么都别动——不动是最好的，音量键、耳机、一切照旧。
  if "$AD" members "$cur" 2>/dev/null | grep -qx "$bh"; then
    PT_RESTORE=""; PT_UID=""
    PT_NOTE="当前输出已经带 BlackHole，不动任何设置"
    return 0
  fi

  curname=$("$AD" name "$cur" 2>/dev/null)
  # 主时钟固定 BlackHole：蓝牙当主时钟会把自己的抖动写进录音，其余成员自动开漂移校正。
  PT_UID=$("$AD" make "录音直通（${curname}）" "$bh" "$bh" "$cur") \
    || die "建不出直通设备。如果你当前输出本身就是个聚合设备，先在菜单栏切回普通的耳机/喇叭。"
  "$AD" use "$PT_UID" || { "$AD" destroy "$PT_UID"; die "切不到直通设备"; }
  PT_RESTORE="$cur"
  PT_NOTE="声音继续走「${curname}」，同时抄一份给 BlackHole"
}

teardown_passthru() {
  r="$1"; p="$2"
  [ -n "$r" ] && { "$AD" use "$r" >/dev/null 2>&1 || warn "切不回原来的输出设备，去菜单栏手动选一下。"; }
  [ -n "$p" ] && "$AD" destroy "$p" >/dev/null 2>&1
}

# 录系统声音走哪条路：tap（系统音频接口，audiocap --system）还是 blackhole（录音直通）。
# tap 不改系统输出，AirPods 怎么自动切换都录得到、音量键照常用——2026-10-13 那次 47 分钟静音就是
# 直通被 AirPods 自动切换绕开了（见 audiocap.swift 头部）。但 tap 没授权时交出来的是全零，和
# 「这会儿没放声音」分不出来，所以不盲开：`rex check sys` 放一声测试音、tap 真收到了，才写进
# $SYS_CFG 换成默认。REX_SYS=tap|blackhole 可以临时指定
SYS_CFG="$HOME/.config/rex/system-audio"
sys_path() {
  case "${REX_SYS:-}" in tap|blackhole) printf '%s' "$REX_SYS"; return ;; esac
  if [ "$(cat "$SYS_CFG" 2>/dev/null)" = tap ]; then printf tap; else printf blackhole; fi
}

# 开录时准备系统声音那一路：设 SYSPAT（给 audiocap 的参数）、sysidx（非空 = 有这一路）
sys_setup() {
  if [ "$(sys_path)" = tap ]; then
    # 先探一下接口还在不在手里：授权被收回、audiocap 重编过（签名变了，系统当它是新程序）都会让
    # tap 只交全零。探不通就这一次退回 BlackHole 直通，录音不能因为这个开不了
    ensure_cap
    # 探一次就把「采样率 声道 名字」留给 add_capture 用，省得再建一次 tap（每建一次约一秒）
    if SYS_INFO=$("$CAP" --system --info 2>"$REX_DIR/.taperr" | grep -E '^[0-9]+ [0-9]+ ' | head -1) && [ -n "$SYS_INFO" ]; then
      rm -f "$REX_DIR/.taperr"
      SYSPAT="--system"; sysidx="tap"
      PT_NOTE="系统声音走系统音频接口，输出设备不动（AirPods 自动切换也不影响）"
      return
    fi
    taperr=$(tail -1 "$REX_DIR/.taperr" 2>/dev/null); rm -f "$REX_DIR/.taperr"
    warn "系统音频接口这会儿用不了：${taperr:-audiocap 没说原因}"
    warn "这次先走 BlackHole 直通（输出被切走会自动接回）；跑一次 rex check sys 能把接口要回来。"
  fi
  setup_passthru; SYSPAT="BlackHole"; sysidx=$(avf_index "BlackHole")
}

# 读 audiocap 写的电平文件：回声「峰值dB 数字零起点 更新时刻」，没有就返回 1
level_of() {
  f="$CAP_DIR/$1.level"
  [ -f "$f" ] || return 1
  sed -nE 's/.*"db": ([-0-9.]+), "zero_since": ([0-9]+), "t": ([0-9]+).*/\1 \2 \3/p' "$f"
}

# 上次留下的直通设备（UID 以 rex.passthru. 开头的都是 rex 建的）。没有在录的时候它们都不该在：
# 正被用作输出的，先切回它里面那个真设备，再拆。
#
# 2026-10-13 撞上的：两秒内开了两次录音，第二次看见第一次刚建的直通设备「已经带 BlackHole」，
# 就记成「什么都没动」，停的时候既不切回也不拆。下一次戴着 AirPods 开录，又看见它「已经带
# BlackHole」，于是声音走的是那个设备里的笔记本扬声器，耳机里没声音——接着 AirPods 的自动切换
# 把输出抢过去，录音那一路从第 6 秒起全是静音。
clean_stale_passthru() {
  cur=$("$AD" default 2>/dev/null)
  for u in $("$AD" list 2>/dev/null | awk -F'\t' '$1 ~ /^rex\.passthru\./ { print $1 }'); do
    if [ "$u" = "$cur" ]; then
      real=$("$AD" members "$u" 2>/dev/null | grep -vi blackhole | head -1)
      [ -n "$real" ] && "$AD" use "$real" >/dev/null 2>&1
      say "  ${C_D}上次留下的「$("$AD" name "$u" 2>/dev/null)」还占着输出，切回「$("$AD" name "$real" 2>/dev/null)」${C_0}"
    fi
    "$AD" destroy "$u" >/dev/null 2>&1
  done
}

# 状态文件里没登记、却还在跑的录音：读 $REX_DIR/.cap/ 管道的 ffmpeg。只有 rex 会起它，所以
# 「没有在录」的时候看见的就是孤儿（2026-10-13 那个录了 53 分钟才被发现）。回声：pid 文件
orphan_recs() {
  tracked=" $(getf pid 2>/dev/null) $(getf pid "$STATE.stopping" 2>/dev/null) "
  for p in $(pgrep -f "ffmpeg .*$REX_DIR/\\.cap/" 2>/dev/null); do
    case "$tracked" in *" $p "*) continue ;; esac
    printf '%s %s\n' "$p" "$(ps -o command= -p "$p" 2>/dev/null | grep -oE "$REX_DIR/[^ ]+\\.(m4a|wav)" | tail -1)"
  done
}

# 收掉孤儿：给 ffmpeg 发 SIGINT，它停读、写完文件尾（m4a 的索引在末尾，硬杀就打不开）；
# 它那个 audiocap 下次往管道里写会收到 EPIPE，自己退。
reap_orphans() {
  orphan_recs | while read -r p f; do
    warn "  后台有一条没停掉的录音还在跑：$(basename "${f:-?}")，先把它停下、收好尾"
    kill -INT "$p" 2>/dev/null
    for _ in $(seq 1 150); do kill -0 "$p" 2>/dev/null || break; sleep 0.1; done
    kill -0 "$p" 2>/dev/null && kill -TERM "$p" 2>/dev/null
  done
}

# 改状态文件里的一行（路由修好后换了直通设备，停录时要按新的切回、拆掉）。先写临时文件再换
set_state() {
  [ -f "$STATE" ] || return 0
  awk -F= -v k="$1" -v v="$2" '$1 == k { print k "=" v; done = 1; next } { print }
    END { if (!done) print k "=" v }' "$STATE" > "$STATE.tmp" && mv "$STATE.tmp" "$STATE"
}

# 录系统声音时每两秒看一眼路由。输出被切走——戴上 AirPods、AirPods 自动切换、别的 App 抢输出——
# 就按现在的输出设备重搭直通、切回去，停录时切回的也换成这个新设备。
#
# 2026-10-13：开录 6.5 秒后 AirPods 的「自动切换」把 Mac 的输出直接改成了耳机（系统日志：Tipi
# device hijack → Route changed from Speaker to Bluetooth），后面 47 分钟全是数字静音。看门狗三分钟
# 才查一次，查到了也只会报警。一分钟里被切走三次以上就不跟它抢了，大声报警，免得来回拉锯。
ROUTE_EVERY="${REX_ROUTE_EVERY:-2}"
route_loop() {
  ffpid="$1"; fixes=""
  bh=$("$AD" list 2>/dev/null | awk -F'\t' 'tolower($3) ~ /blackhole/ { print $1; exit }')
  while kill -0 "$ffpid" 2>/dev/null; do
    sleep "$ROUTE_EVERY"
    kill -0 "$ffpid" 2>/dev/null || break
    sys_route_ok && continue
    now=$(date +%s)
    n=$(printf '%s\n' $fixes | awk -v t="$now" 'NF && $1 > t - 60' | wc -l | tr -d ' ')
    cur=$("$AD" default 2>/dev/null)
    curname=$("$AD" name "$cur" 2>/dev/null)
    if [ "$n" -ge 3 ]; then
      m="输出一分钟里被切走了 3 次以上（现在是「${curname:-?}」），不再自动接回，系统声音从现在起录不进来"
      printf '%s  %s\n' "$(date +%H:%M:%S)" "$m" >> "$WATCH_LOG"
      osascript -e "display notification \"${m}\" with title \"rex 录音警告\" sound name \"Basso\"" 2>/dev/null
      break
    fi
    new=$("$AD" make "录音直通（${curname}）" "$bh" "$bh" "$cur" 2>/dev/null)
    if [ -n "$new" ] && "$AD" use "$new" >/dev/null 2>&1; then
      old=$(getf passthru)
      [ -n "$old" ] && [ "$old" != "$new" ] && "$AD" destroy "$old" >/dev/null 2>&1
      set_state restore "$cur"
      set_state passthru "$new"
      fixes="$fixes $now"
      m="输出被切到「${curname}」，已经重新接上，系统声音接着录"
      printf '%s  %s\n' "$(date +%H:%M:%S)" "$m" >> "$WATCH_LOG"
      osascript -e "display notification \"${m}\" with title \"rex\"" 2>/dev/null
    else
      [ -n "$new" ] && "$AD" destroy "$new" >/dev/null 2>&1
      m="输出被切到「${curname:-?}」，接不回去（它可能本身是个聚合设备），系统声音录不进来"
      printf '%s  %s\n' "$(date +%H:%M:%S)" "$m" >> "$WATCH_LOG"
      osascript -e "display notification \"${m}\" with title \"rex 录音警告\" sound name \"Basso\"" 2>/dev/null
      sleep 20
    fi
  done
}

# ------------------------------------------------------------------ 看门狗

# 每隔几分钟采一次各路输入，发现某一路变成数字静音就当场弹通知。
#
# 这个东西是一次真实事故换来的：开腾讯会议录了 128 分钟，麦克风在**第 2 分钟**
# 就被会议 App 抢走，之后 126 分钟全是 -91.0 dB，而这件事直到散会、转写完、
# 看见 173 字的稿子才发现。rex status 查得出来，但那要人主动去查——
# 两小时的会里没人会想起来查。所以改成它自己查。
#
# 代价：每次检查会开一下输入设备（1 秒）。REX_WATCH=0 可以整个关掉。
WATCH_EVERY="${REX_WATCH:-180}"
WATCH_LOG="$REX_DIR/.watch.log"

# 系统声音这一路还通不通——**看路由，不看电平**。
#
# 这条是踩出来的（2026-08-19）。原来 mic 和 sys 共用一套「峰值 < -70 dB 就是断了」
# 的判据，对麦克风成立（真麦克风再安静也有本底噪声，安静房间实测 -68 dB 上下），
# 对 BlackHole **不成立**：虚拟设备上没有信号就是真正的数字零。实测当前什么都不放：
#
#     mean_volume: -91.0 dB      max_volume: -91.0 dB
#
# 和「断了」的读数一模一样。于是一场 16 分钟的会里，对方每停下来喘口气，
# 看门狗就报一次「系统声音断了」，中间还报「又恢复了」——**而链路一秒都没断过。**
# 反过来说这也是个提示：断掉的音频路由不会自己好，报了「恢复」基本就说明是误报。
#
# 真正会断的是**路由**：耳机断连 → macOS 把默认输出切走 → 直通设备不再是输出 →
# BlackHole 收不到东西。这个是结构性的、能直接查的，而且不会有假阳性。
sys_route_ok() {
  bh=$("$AD" list 2>/dev/null | awk -F'\t' 'tolower($3) ~ /blackhole/ { print $1; exit }')
  [ -n "$bh" ] || return 1
  cur=$("$AD" default 2>/dev/null) || return 1
  [ "$cur" = "$bh" ] && return 0
  "$AD" members "$cur" 2>/dev/null | grep -qx "$bh"
}

# 每一路都看 audiocap 写的电平文件（半秒一次），不再另开一路采样去猜：
#   十秒没有新帧 = 采集停了；两次检查之间 frames 没涨 = 卡住；麦克风数字零 ≥ 3 秒 = 没信号。
# 走 BlackHole 的系统声音另查路由——输出被切走时 BlackHole 收到的是全零，frames 照样涨，光看文件看不出来。
# 以前「找不到设备就跳过」「只看 t 不看帧」都把「不知道」当成了「正常」。
watch_track() {
  label="$1"; tag="$2"; kind="${3:-mic}"
  dead=0; p=""
  now=$(date +%s)
  if lv=$(level_of "$tag"); then
    set -- $lv            # 峰值dB 数字零起点 更新时刻
    lf=$(sed -nE 's/.*"last_frame_t": ([0-9]+).*/\1/p' "$CAP_DIR/$tag.level" 2>/dev/null)
    fr=$(sed -nE 's/.*"frames": ([0-9]+).*/\1/p' "$CAP_DIR/$tag.level" 2>/dev/null)
    pf="$REX_DIR/.watch-frames-$tag"; prev=$(cat "$pf" 2>/dev/null); printf '%s' "${fr:-0}" > "$pf"
    if [ $((now - ${3:-0})) -gt 10 ]; then dead=1; p="${label}的采集停了（电平文件 $((now - ${3:-0})) 秒没更新）"
    elif [ -n "$lf" ] && [ $((now - lf)) -gt 10 ]; then dead=1; p="${label}的采集停了（$((now - lf)) 秒没有新帧）"
    elif [ -n "$prev" ] && [ "${fr:-0}" = "$prev" ]; then dead=1; p="${label}的采集卡住了（帧数不涨）"
    elif [ "$kind" = mic ] && [ "${2:-0}" -gt 0 ] && [ $((now - $2)) -ge 3 ]; then dead=1; p="${label}没信号（数字零 $((now - $2)) 秒）"
    fi
  else
    dead=1; p="${label}的采集没在出数据（没有电平文件）"
  fi
  if [ "$dead" = 0 ] && [ "$kind" = sys ] && [ "$(getf sys)" != tap ] && ! sys_route_ok; then
    cn=$("$AD" name "$("$AD" default 2>/dev/null)" 2>/dev/null)
    dead=1; p="${label}断了：当前输出「${cn:-?}」里没有 BlackHole"
  fi
  watch_report "$label" "$tag" "$dead" "$p" "$kind"
}

# 只在「由通到断」那一刻报一次，别每三分钟刷一次屏。
watch_report() {
  label="$1"; idx="$2"; dead="$3"; detail="$4"; kind="$5"
  sf="$REX_DIR/.watch-$idx"
  was=$(cat "$sf" 2>/dev/null || echo 0)
  printf '%s' "$dead" > "$sf"

  if [ "$dead" = 1 ] && [ "$was" != 1 ]; then
    m="${detail}，从现在起这一路录不进东西"
    printf '%s  %s\n' "$(date +%H:%M:%S)" "$m" >> "$WATCH_LOG"
    # 故意不加提示音——正在录系统声音的话，提示音会被录进去
    osascript -e "display notification \"${m}\" with title \"rex 录音警告\"" 2>/dev/null
  elif [ "$dead" = 0 ] && [ "$was" = 1 ]; then
    printf '%s  %s\n' "$(date +%H:%M:%S)" "${label}又恢复了" >> "$WATCH_LOG"
  fi
}

watch_loop() {
  ffpid="$1"; mode="$2"; n=0
  while kill -0 "$ffpid" 2>/dev/null; do
    sleep 2; n=$((n + 2))
    kill -0 "$ffpid" 2>/dev/null || break
    { [ "$WATCH_EVERY" -gt 0 ] 2>/dev/null && [ "$n" -ge "$WATCH_EVERY" ]; } || continue
    n=0
    case "$mode" in
      mic)  watch_track "麦克风" mic mic ;;
      sys)  watch_track "系统声音" sys sys ;;
      both) watch_track "麦克风" mic mic
            watch_track "系统声音" sys sys ;;
    esac
  done
  # ffmpeg 没了而状态文件还指着它：不是 rex stop 停的（stop 一进来就把状态文件改名认领了）。到了时长上限、
  # 设备断了、磁盘满了都走到这里——不收尾的话直通设备一直占着输出、状态文件带着死 PID 留着、没人知道录音停了
  if [ "$(getf pid)" = "$ffpid" ]; then
    why=$(grep 'audiocap' "$LOG" 2>/dev/null | grep -v '在读「' | tail -1)   # 「在读」是开工那行，不是原因
    "$SELF" stop > "$REX_DIR/.laststop.log" 2>&1
    m="录音自己停了：${why:-可能到了时长上限}。文件已收尾，rex ls 看结果"
    printf '%s  %s\n' "$(date +%H:%M:%S)" "$m" >> "$REX_DIR/.laststop.log"
    osascript -e "display notification \"${m}\" with title \"rex 录音停了\" sound name \"Basso\"" 2>/dev/null
  fi
}

# ------------------------------------------------------------------ 状态文件

getf() { f="${2:-$STATE}"; [ -f "$f" ] && awk -F= -v k="$1" '$1==k { sub(/^[^=]*=/, ""); print; exit }' "$f"; }
# PID 会被复用：重启过、或者状态文件是很久以前留下的，同一个号可能已经是别的程序。活着 + 命令行确实是 ffmpeg 才算
alive() { p=$(getf pid); [ -n "$p" ] && kill -0 "$p" 2>/dev/null && ps -o command= -p "$p" 2>/dev/null | grep -q '^ffmpeg'; }

# ------------------------------------------------------------------ 开始

# start 退出时的收尾。没开成（die、Ctrl-C、录音台等不及把它停掉）就把已经起的收掉、输出切回、状态文件删掉——
# 直通建好之后任何一步失败都不能让输出停在多输出设备上。开成了（STARTED=1）只删锁，录音不受影响
start_cleanup() {
  if [ -z "${STARTED:-}" ]; then
    [ -n "${pid:-}" ] && kill -INT "$pid" 2>/dev/null
    stop_caps
    teardown_passthru "${PT_RESTORE:-}" "${PT_UID:-}"
    [ -n "${pid:-}" ] && rm -f "$STATE"
    [ -n "${pid:-}" ] && warn "没开成，已经收拾干净（输出切回、状态文件删掉）。"
  fi
  rm -rf "$REX_DIR/.starting"
}

start() {
  mode="$1"
  ensure_ad
  mkdir -p "$REX_DIR"

  # 开录这一段加锁。录音台里连点两下、或者两个终端几乎同时开：第二次进来时第一次还没写状态
  # 文件，于是两次都开了，第一次那个成了没人管的孤儿（2026-10-13 两秒内开了两次，孤儿录了 53 分钟）
  if ! mkdir "$REX_DIR/.starting" 2>/dev/null; then
    # 锁里记着持有者：它还活着就是真的在开（授权框最多等两分钟，开录可能很慢）；死了才算残留
    hp=$(cat "$REX_DIR/.starting/pid" 2>/dev/null)
    if [ -n "$hp" ] && kill -0 "$hp" 2>/dev/null; then
      die "正在开始录音（刚刚已经按过一次），等几秒看 rex status。"
    fi
    if [ -z "$hp" ] && [ -n "$(find "$REX_DIR/.starting" -maxdepth 0 -mmin -2 2>/dev/null)" ]; then
      die "正在开始录音（刚刚已经按过一次），等几秒看 rex status。"
    fi
    rm -rf "$REX_DIR/.starting"; mkdir "$REX_DIR/.starting" || die "建不了开录锁 ${REX_DIR}/.starting"
  fi
  echo $$ > "$REX_DIR/.starting/pid"
  pid=""; caps=""; PT_RESTORE=""; PT_UID=""; STARTED=""
  trap 'start_cleanup' EXIT
  trap 'exit 130' INT TERM
  if [ -f "$STATE.stopping" ]; then
    # 上一条正在收尾（rex stop 一进来就把状态文件改名认领）。它的 rm 要是落在我们写完状态文件之后，新录音就成了孤儿
    if [ -n "$(find "$STATE.stopping" -maxdepth 0 -mmin -2 2>/dev/null)" ]; then
      die "上一条正在收尾（rex stop 还没跑完），等几秒再开。"
    fi
    rm -f "$STATE.stopping"          # 两分钟以上没收完尾，是 stop 崩掉留下的；下面的清场会收拾残留
  fi

  if [ -f "$STATE" ]; then
    if alive; then die "已经在录了（$(getf mode)）。先 rex stop，或者直接跑 rex 停掉。"; fi
    warn "上次的状态文件是死的（进程没了），清掉重来。"
    stop_caps
    rm -f "$STATE"                   # 它的直通设备（还占着输出的话）由下面的 clean_stale_passthru 切回、拆掉
  fi
  # 没有在录：后台不该有录音进程，也不该有 rex 建的直通设备。有就是上次留下的，先收拾
  reap_orphans
  clean_stale_passthru
  ext="m4a"; [ -n "${WAV:-}" ] && ext="wav"
  base="$REX_DIR/$(date +%Y-%m-%d_%H%M%S)_${mode}"

  micidx=""; sysidx=""; SYS_INFO=""
  PT_RESTORE=""; PT_UID=""; PT_NOTE=""

  SYSPAT=""
  case "$mode" in
    mic)  micidx=$(pick_mic mic) || exit 1; micpat=$(mic_pattern mic) ;;
    sys)  sys_setup ;;
    both) micidx=$(pick_mic both) || exit 1; micpat=$(mic_pattern both)
          sys_setup ;;
  esac
  if [ -n "$sysidx" ]; then :; elif [ "$mode" != "mic" ]; then
    teardown_passthru "$PT_RESTORE" "$PT_UID"; die "avfoundation 里找不到 BlackHole"
  fi

  # 输入顺序不能变：麦克风在前（输入 0）、系统声音在后（输入 1），--split 的 -map 靠它。
  ensure_cap
  : > "$LOG"
  rm -rf "$CAP_DIR"; mkdir -p "$CAP_DIR"
  caps=""; in_args=()
  [ -n "$micidx" ] && add_capture "$micpat" mic
  [ -n "$sysidx" ] && add_capture "$SYSPAT" sys
  args=( -hide_banner -loglevel warning -stats -y "${in_args[@]}" )

  # -rf64 auto：WAV 的 RIFF 头装不下 4 GiB（立体声 24 bit 约 4 小时就到），不开 RF64 录超了文件头就是错的
  if [ -n "${WAV:-}" ]; then enc_mic=( -c:a pcm_s24le -rf64 auto ); enc_sys=( -c:a pcm_s24le -rf64 auto )
  else enc_mic=( -c:a aac -b:a 96k ); enc_sys=( -c:a aac -b:a 160k ); fi

  files=""
  case "$mode" in
    mic)
      out="$base.$ext"; files="$out"
      args+=( -t "$MAX_SECONDS" -ac 1 -ar 48000 "${enc_mic[@]}" "$out" ) ;;
    sys)
      out="$base.$ext"; files="$out"
      args+=( -t "$MAX_SECONDS" -ac 2 -ar 48000 "${enc_sys[@]}" "$out" ) ;;
    both)
      if [ -n "${SPLIT:-}" ]; then
        o1="${base}-mic.$ext"; o2="${base}-sys.$ext"; files="$o1|$o2"
        args+=( -t "$MAX_SECONDS" -map 0:a -ac 1 -ar 48000 "${enc_mic[@]}" "$o1"
                -t "$MAX_SECONDS" -map 1:a -ac 2 -ar 48000 "${enc_sys[@]}" "$o2" )
      else
        out="$base.$ext"; files="$out"
        # normalize=0：amix 默认把每一路都除以路数，人声本来就小、再砍一半就听不见了。
        # 以前这里还有 aresample=async=1。它实际干的活是**用静音填 avfoundation 丢掉的洞**——
        # 所以混音的 both 测出来「0% 丢失」，其实样本一样丢了。现在输入是 audiocap 的原始
        # PCM，时间戳由样本数决定、天然连续，没有洞可填。两个设备各有时钟，两小时会漂
        # 零点几秒，对转写无所谓。
        #
        # 除了混音，**两路原始信号也各存一条轨**，在同一个文件里：
        #   0 号轨  混音      播放器只放这条（只有它是 default，别的轨 disabled）
        #   1 号轨  麦克风    handler_name=mic
        #   2 号轨  系统声音  handler_name=sys
        # 「谁在说话」在录的这一刻是知道的，混完就再也分不开了——2026-09-26 那场通话
        # 事后只能靠频谱猜（通话音频 7.5 kHz 以上被砍掉、麦克风是全频带）。分轨存着，
        # rex text 两轨各转各的、按时间合成对话稿，标签是对的（tools/speakers.py）。
        # 顺带解决第九节那个老问题：两路电平差 32 dB 时自己的声音被混音埋掉——
        # 转写不再用混音那条了。
        # 代价是文件大一截（160k + 64k + 64k）。WAV 装不下多条轨，--wav 时只有混音。
        mix="[0:a][1:a]amix=inputs=2:duration=longest:normalize=0[a]"
        if [ -n "${WAV:-}" ]; then
          args+=( -filter_complex "$mix"
                  -map "[a]" -t "$MAX_SECONDS" -ac 2 -ar 48000 "${enc_sys[@]}" "$out" )
        else
          args+=( -filter_complex "$mix"
                  -map "[a]" -map 0:a -map 1:a -t "$MAX_SECONDS" -ar 48000 -c:a aac
                  -ac:a:0 2 -b:a:0 160k -ac:a:1 1 -b:a:1 64k -ac:a:2 1 -b:a:2 64k
                  -disposition:a:0 default -disposition:a:1 0 -disposition:a:2 0
                  -metadata:s:a:0 handler_name=mix -metadata:s:a:1 handler_name=mic
                  -metadata:s:a:2 handler_name=sys "$out" )
        fi
      fi ;;
  esac

  nohup ffmpeg "${args[@]}" >>"$LOG" 2>&1 &
  pid=$!

  {
    echo "pid=$pid"; echo "mode=$mode"; echo "start=$(date +%s)"
    echo "restore=$PT_RESTORE"; echo "passthru=$PT_UID"; echo "files=$files"
    echo "caps=$caps"; echo "sys=$( [ "$SYSPAT" = "--system" ] && echo tap || { [ -n "$SYSPAT" ] && echo blackhole; } )"
  } > "$STATE"
  rm -f "$WATCH_LOG" "$REX_DIR"/.watch-*

  # 不 sleep 猜，盯进度输出：出现 size= 才说明设备真的在吃数据了。最多等 12 秒
  ok=""
  for _ in $(seq 1 120); do
    kill -0 "$pid" 2>/dev/null || break
    grep -q "size=" "$LOG" 2>/dev/null && { ok=1; break; }
    sleep 0.1
  done

  if [ -z "$ok" ]; then
    kill -INT "$pid" 2>/dev/null
    stop_caps
    teardown_passthru "$PT_RESTORE" "$PT_UID"
    rm -f "$STATE"
    printf '%s没能开始采集。ffmpeg 说：%s\n' "$C_R" "$C_0"
    tail -c 900 "$LOG"; say ""
    warn "最常见的原因：麦克风没授权给「rex 录音采集」（audiocap）。"
    say "  跑一次 rex check 会弹授权框；或者 系统设置 → 隐私与安全性 → 麦克风 → 打开「rex 录音采集」"
    say "  （从 BlackHole 抓声音在系统看来也算「用麦克风」，同样要给。）"
    exit 1
  fi
  # ffmpeg 有输出不代表每一路都活着（分轨时一路死了另一路照样写）：再看每一路的电平文件里 frames 有没有涨
  for tag in mic sys; do
    [ -e "$CAP_DIR/$tag.f32" ] || continue
    got=""
    for _ in $(seq 1 50); do
      fr=$(sed -nE 's/.*"frames": ([0-9]+).*/\1/p' "$CAP_DIR/$tag.level" 2>/dev/null)
      [ "${fr:-0}" -gt 0 ] 2>/dev/null && { got=1; break; }
      sleep 0.1
    done
    [ -n "$got" ] && continue
    kill -INT "$pid" 2>/dev/null; stop_caps; teardown_passthru "$PT_RESTORE" "$PT_UID"; rm -f "$STATE"
    case "$tag" in mic) nm="麦克风" ;; *) nm="系统声音" ;; esac
    printf '%s%s这一路起了但不出数据，这次没开录。audiocap 说：%s\n' "$C_R" "$nm" "$C_0"
    grep 'audiocap' "$LOG" | tail -3
    [ "$tag" = sys ] && say "  走系统音频接口的话，跑一次 rex check sys 看它还通不通；REX_SYS=blackhole 可以先走老路。"
    exit 1
  done

  STARTED=1              # 录音开起来了：从这儿起 rex.sh 退出、被停掉都不碰录音
  trap - INT TERM
  say ""
  case "$mode" in
    mic)  say "${C_G}● 在录麦克风${C_0}   ${CAPNAME_mic:-$(avf_name "$micidx")}" ;;
    sys)  say "${C_G}● 在录系统声音${C_0}" ;;
    both) say "${C_G}● 在录 麦克风 + 系统声音${C_0}   ${CAPNAME_mic:-$(avf_name "$micidx")}" ;;
  esac
  printf '%s\n' "$files" | tr '|' '\n' | sed 's/^/  → /'
  [ -n "$PT_NOTE" ] && say "  ${C_D}$PT_NOTE${C_0}"
  [ -n "$PT_UID" ] && say "  ${C_D}（这期间音量键不管用——多输出设备不支持，用 App 自己的音量条）${C_0}"
  # 合着盖时内建麦克风在**硬件上**是断开的（苹果的隐私设计）：系统照样列出这个设备，
  # 读出来却全是 0，和链路断了一模一样。2026-10-11 测试时撞上：录了 14 秒，
  # 麦克风那一轨 −91.0 dB，直接用 audiocap 读也是。开头就说，别等录完才发现。
  builtin_mic=""
  if [ -n "$micidx" ]; then
    case "${CAPNAME_mic:-$(avf_name "$micidx")}" in *[Mm]ac[Bb]ook*) builtin_mic=1 ;; esac
  fi
  if [ -n "$builtin_mic" ] && lid_closed; then
    warn "  ⚠ 笔记本合着盖：内建麦克风在硬件上是断开的，这一路录到的会是数字静音。"
    warn "    开盖再录，或者 --device 换一个麦克风（耳机、iPhone）。"
  fi
  if [ -n "$micidx" ] && is_bluetooth_in "$(avf_name "$micidx")"; then
    warn "  ⚠ 用的是蓝牙耳机的麦克风，耳机会掉进免提模式，播放声音跟着变糊。"
    warn "    介意就加 --device \"MacBook Air Microphone\"。"
  fi
  if [ "$SYSPAT" = BlackHole ] && [ "$ROUTE_EVERY" -gt 0 ] 2>/dev/null; then
    route_loop "$pid" >/dev/null 2>&1 &
    printf 'route=%s\n' "$!" >> "$STATE"
    say "  ${C_D}输出被切走（戴上 AirPods、自动切换）会在两秒内自动接回${C_0}"
    say "  ${C_D}更稳的录法：跑一次 rex check sys，换成系统音频接口（不改输出设备，AirPods 怎么切都不断）${C_0}"
  fi
  # 看门狗总是起：REX_WATCH=0 只关掉逐路自查，「ffmpeg 自己退了要收尾」这一条不能关
  watch_loop "$pid" "$mode" >/dev/null 2>&1 &
  printf 'watch=%s\n' "$!" >> "$STATE"
  if [ "$WATCH_EVERY" -gt 0 ] 2>/dev/null; then
    if [ "$WATCH_EVERY" -ge 60 ]; then ivl="$((WATCH_EVERY / 60)) 分钟"; else ivl="$WATCH_EVERY 秒"; fi
    say "  ${C_D}每 ${ivl}自查一次，某一路断了会弹通知（关掉：REX_WATCH=0）${C_0}"
  fi
  say ""
  say "  停：${C_G}rex stop${C_0}    看状态：rex status"
  say "  ${C_D}最长录 $((MAX_SECONDS / 3600)) 小时会自己停（改：REX_MAX=秒数）${C_0}"
}

# ------------------------------------------------------------------ 停止

report_file() {
  f="$1"
  [ -f "$f" ] || { warn "  ✗ 没生成 $f"; return; }

  dur=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null | cut -d. -f1)
  dur=${dur:-0}
  sz=$(du -h "$f" | cut -f1 | tr -d ' ')

  # 长文件不整条扫，从十分之一处取 60 秒就够判断有没有声音了。
  if [ "$dur" -le 300 ]; then vs=( -i "$f" ); else vs=( -ss "$((dur / 10))" -t 60 -i "$f" ); fi
  vol=$(ffmpeg -hide_banner -nostats "${vs[@]}" -af volumedetect -f null - 2>&1 \
        | awk '/mean_volume/ { m=$(NF-1) } /max_volume/ { p=$(NF-1) } END { print m" "p }')
  mean=$(printf '%s' "$vol" | awk '{print $1}')
  peak=$(printf '%s' "$vol" | awk '{print $2}')

  say "  ${C_G}✓${C_0} $f"
  say "    $((dur / 60)) 分 $((dur % 60)) 秒 · $sz · 平均 ${mean:-?} dB / 峰值 ${peak:-?} dB"

  # 判据看峰值不看均值，理由见文件头最后一条。
  if [ -n "$peak" ] && awk -v p="$peak" 'BEGIN { exit !(p < -70) }'; then
    warn "    ⚠ 几乎是数字静音，多半根本没收到信号。"
    warn "      系统声音录空最常见的原因：源 App 的音量是 0，或者直通设备没建起来。"
  elif [ -n "$peak" ] && awk -v p="$peak" 'BEGIN { exit !(p > -0.5) }'; then
    warn "    ⚠ 峰值顶到满刻度了，可能削了顶。下次把源音量调小一点。"
  fi

  # 分轨各看一眼。混音那条有声音不代表两路都进来了：2026-09-26 系统声音那一轨从第 1
  # 分钟起就是数字静音，混音照样有声音——全是麦克风的。整轨扫，37 分钟约 2 秒；
  # 超过两小时就不在停止这一步扫了，留给 rex text（speakers.py 会量同一个数）。
  st=$(speaker_tracks "$f")
  if [ -n "$st" ]; then
    if [ "$dur" -le 7200 ]; then
      sm=$(silent_seconds "$f" "${st%% *}" "$dur"); ss=$(silent_seconds "$f" "${st##* }" "$dur")
      pm=$(awk -v s="$sm" -v d="$dur" 'BEGIN { printf "%d", (d > 0) ? 100 * s / d : 0 }')
      ps=$(awk -v s="$ss" -v d="$dur" 'BEGIN { printf "%d", (d > 0) ? 100 * s / d : 0 }')
      say "    分轨：麦克风 ${C_D}数字静音 ${pm}%${C_0} · 系统声音 ${C_D}数字静音 ${ps}%${C_0}"
      # 真麦克风有本底噪声，出不了数字静音；出了就是读的那一头被掐断了：
      # 合着盖（内建麦克风硬件断开）或者被会议 App 抢走（使用说明「开会」）。
      # 系统声音的数字静音是正常现象（对方不出声就是 0），只有占了大半才提一句。
      if [ "$pm" -ge 20 ]; then
        warn "    ⚠ 麦克风那一轨 ${pm}% 是数字静音——真麦克风不会这样"
        warn "      要么笔记本合着盖（合盖时内建麦克风在硬件上断开），"
        warn "      要么会议 App 把它抢走了：让会议 App 和 rex 用不同的麦克风（rex-使用说明「开会」）"
      fi
      if [ "$ps" -ge 50 ]; then
        warn "    ⚠ 系统声音那一轨 ${ps}% 是数字静音——要么对方一直没出声，要么中途断了"
        warn "      断了最常见的原因：录到一半戴上蓝牙耳机，声音绕过了 BlackHole（看下面看门狗的记录）"
      fi
    fi
    say "    ${C_D}含分轨，rex text 会按说话人出对话稿（麦克风 = 我，系统声音 = 对方）${C_0}"
  fi

  # 末尾是不是一大段空白——忘了停的典型样子。只看最后 5 分钟，不整条扫
  # （6 小时的文件整条解码要十几秒，停止这一步不该这么慢）。
  # 阈值按音源分，理由见 rex_trim.py 文件头：BlackHole 静音是真数字零，
  # 麦克风有本底噪声，共用一个阈值就是 2026-08-19 看门狗那个坑。
  if [ "$dur" -gt 600 ]; then
    case "$(basename "$f")" in
      *_sys.*|*_both-sys.*) th=-70 ;;
      *) th=-50 ;;
    esac
    tp=$(ffmpeg -hide_banner -nostats -sseof -300 -i "$f" -af volumedetect -f null - 2>&1 \
         | awk '/max_volume/ { print $(NF-1) }')
    if [ -n "$tp" ] && awk -v p="$tp" -v t="$th" 'BEGIN { exit !(p < t) }'; then
      warn "    ⚠ 最后 5 分钟一直没声音（峰值 ${tp} dB），多半是忘了停。"
      warn "      ${C_0}rex trim${C_Y} 切掉末尾空白（中间的停顿不动，原件进废纸篓）"
    fi
  fi
}

stop() {
  if [ ! -f "$STATE" ]; then
    if [ -n "$(orphan_recs)" ]; then reap_orphans; ensure_ad; clean_stale_passthru; say "收好了。"
    else say "现在没有在录。"; fi
    return 0
  fi
  ensure_ad
  # 一进来就把状态文件改名认领：收尾要几秒（报告里要 ffprobe、算静音），这期间要是又开了一条新录音，
  # 最后那句 rm 会把新录音的登记删掉、新录音成孤儿。改了名，start 看到 .stopping 就等，看不到 .current 也不会误判
  SF="$STATE.stopping"
  mv "$STATE" "$SF" 2>/dev/null || { say "上一条正在收尾（另一个 rex stop 在跑）。"; return 0; }

  pid=$(getf pid "$SF"); mode=$(getf mode "$SF"); files=$(getf files "$SF")
  t0=$(getf start "$SF"); el=$(( $(date +%s) - ${t0:-$(date +%s)} ))

  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && ps -o command= -p "$pid" 2>/dev/null | grep -q '^ffmpeg'; then
    # 先停采集：audiocap 把缓冲里剩下的写完、关掉管道，ffmpeg 读到 EOF 自己收尾，
    # 最后一秒也不丢。十秒内没退出（或者是这次改动之前开始的录音，没有 caps），
    # 才退回老办法直接给 ffmpeg 发 SIGINT。
    for c in $(getf caps "$SF"); do kill -INT "$c" 2>/dev/null; done
    for _ in $(seq 1 100); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
    kill -0 "$pid" 2>/dev/null && kill -INT "$pid" 2>/dev/null
    # 等它写文件尾。m4a 的索引在末尾，硬杀 = 打不开的文件。
    for _ in $(seq 1 150); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
    if kill -0 "$pid" 2>/dev/null; then
      warn "ffmpeg 15 秒没退出，强制结束。文件可能不完整。"
      kill -TERM "$pid" 2>/dev/null; sleep 1
    fi
  else
    why=$(grep 'audiocap' "$LOG" 2>/dev/null | grep -v '在读「' | tail -1)
    warn "录音进程已经不在了：${why:-日志里没有报错，多半是到了时长上限（REX_MAX，默认 $((MAX_SECONDS / 3600)) 小时）自己停的}"
  fi

  w=$(getf watch "$SF"); [ -n "$w" ] && [ "$w" != "$$" ] && kill "$w" 2>/dev/null
  rt=$(getf route "$SF"); [ -n "$rt" ] && kill "$rt" 2>/dev/null
  rm -f "$REX_DIR"/.watch-*
  # 收尾前把采集进程报的溢出记下来（它在电平文件里）：缓冲溢出 = 文件里少了一段，看着却是完整的
  for tag in mic sys; do
    ov=$(sed -nE 's/.*"overrun": ([0-9]+).*/\1/p' "$CAP_DIR/$tag.level" 2>/dev/null)
    [ "${ov:-0}" -gt 0 ] 2>/dev/null && warn "⚠ ${tag} 这一路缓冲溢出丢过 ${ov} 帧（下游写得太慢），这一段在文件里是缺的"
  done
  for c in $(getf caps "$SF"); do caps="${caps:-} $c"; done
  stop_caps

  r=$(getf restore "$SF"); p=$(getf passthru "$SF")
  teardown_passthru "$r" "$p"
  clean_stale_passthru >/dev/null      # 路由监视被打断在半路时可能多建了一个
  [ -n "$r" ] && say "${C_D}输出切回「$("$AD" name "$r" 2>/dev/null)」${C_0}"

  say ""
  say "录完了 · $mode · $((el / 60)) 分 $((el % 60)) 秒"
  printf '%s\n' "$files" | tr '|' '\n' | while IFS= read -r f; do
    [ -n "$f" ] && report_file "$f"
  done
  if [ -s "$WATCH_LOG" ]; then
    say ""
    warn "录制期间的路由和看门狗记录："
    while IFS= read -r ln; do say "  $ln"; done < "$WATCH_LOG"
  fi
  say ""
  say "  文件夹：$REX_DIR    ${C_D}（rex open 在访达里打开）${C_0}"
  say "  ${C_D}一条龙（转写 → 分人 → Claude 校对 → 分析）：${C_0}rex go"
  rm -f "$SF"
}

# ------------------------------------------------------------------ 手机上录的

# iPhone 的语音备忘录经 iCloud 同步到 Mac，落在这个共享容器里。
# 把它接进同一条转写流水线——手机负责按一下就录，Mac 负责转写，
# 词表和 fix 表都复用，不用在手机上再维护一套。
VM_DIR="$HOME/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"

# 故意**不读** Voice Memos 的数据库。它是 WAL 模式（不连 -wal 一起复制就拿到
# 过期数据，实测会少掉最新那条、时长还显示 0），而实测 193 条全是
# 「20260815 212142」这种默认标题、一条改名的都没有——文件名里就有日期时间，
# 读库唯一的作用是多一个碰坏别人数据的机会。
phone_files() { ls -1t "$VM_DIR"/*.m4a "$VM_DIR"/*.qta "$VM_DIR"/*.wav 2>/dev/null; }

# 20260815 212142-A992F4A3.qta → 2026-08-15_2121。认不出格式就退回文件修改时间。
phone_stamp() {
  b=$(basename "$1"); d=${b%% *}; t=${b#* }; t=${t%%-*}
  case "$d$t" in
    [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9])
      printf '%s-%s-%s_%s%s' "${d:0:4}" "${d:4:2}" "${d:6:2}" "${t:0:2}" "${t:2:2}" ;;
    *) date -r "$1" +%Y-%m-%d_%H%M ;;
  esac
}

# 「目录读不了」和「目录里没东西」是两件完全不同的事，而 `ls … 2>/dev/null`
# 把它们压成同一个空字符串——被吞掉的那行 Operation not permitted 恰恰是
# 唯一能解释问题的东西。所以单独探一次，把两种情况分开报。
#
# 真事：Voice Memos 的容器受 macOS TCC 保护，而**授权是按 App 给的**。
# 有权限的进程能列出 195 条，作者的 Terminal.app 没有，同一个目录在它眼里
# 就是空的，于是工具报「一条录音都没有」——完全误导人。
phone_probe() {
  VM_DIR="$VM_DIR" python3 -c '
import os, sys
d = os.environ["VM_DIR"]
if not os.path.isdir(d):
    print("NODIR"); sys.exit()
try:
    print("OK %d" % len([f for f in os.listdir(d)
                         if f.endswith((".m4a", ".qta", ".wav"))]))
except PermissionError:
    print("DENIED")
except OSError as e:
    print("ERR %s" % e)
'
}

phone() {
  case "$(phone_probe)" in
    NODIR)
      die "找不到语音备忘录的同步目录。iPhone 上「设置 → 你的名字 → iCloud → 语音备忘录」要打开。" ;;
    DENIED)
      printf '%s读不了语音备忘录目录——是权限问题，不是没有文件。%s\n' "$C_R" "$C_0" >&2
      say "  系统设置 → 隐私与安全性 → 完整磁盘访问权限 → 把你的终端 App 加进去，"
      say "  然后**完全退出终端再打开**（改完权限不重启进程不生效）。"
      say ""
      say "  ${C_D}Voice Memos 的容器受 TCC 保护，而授权是按 App 给的——${C_0}"
      say "  ${C_D}访达和「语音备忘录」App 能看见，不代表终端能看见。${C_0}"
      exit 1 ;;
    "OK 0")
      die "${VM_DIR} 里确实一条录音都没有。" ;;
    ERR*)
      die "读不了 ${VM_DIR}" ;;
  esac
  list=$(phone_files)
  [ -n "$list" ] || die "${VM_DIR} 里一条录音都没有。"

  pick="${1:-}"
  if [ -z "$pick" ]; then
    say "iPhone 语音备忘录（最近 10 条）"
    say ""
    i=0
    printf '%s\n' "$list" | head -10 | while IFS= read -r f; do
      i=$((i + 1))
      d=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null | cut -d. -f1)
      d=${d:-0}
      # .qta 是空间音频，里面有一条 ffmpeg 解不了的 apac 轨；标出来免得看着奇怪。
      tag=""; case "$f" in *.qta) tag=" ${C_D}空间音频${C_0}" ;; esac
      printf '  %s%2d%s  %s  %3d 分 %02d 秒  %6s%s\n' \
        "$C_G" "$i" "$C_0" "$(phone_stamp "$f")" \
        "$((d / 60))" "$((d % 60))" "$(du -h "$f" | cut -f1 | tr -d ' ')" "$tag"
    done
    say ""
    say "  转写最新那条：${C_G}rex phone 1${C_0}"
    return 0
  fi

  case "$pick" in
    "$VM_DIR"/*)
      # 录音台（rex app）按文件导入：序号会随新录音变，路径不会
      [ -f "$pick" ] || die "没有这条语音备忘录：$pick"
      src="$pick" ;;
    ''|*[!0-9]*) die "要一个序号，比如 rex phone 1（先跑 rex phone 看列表）" ;;
    *)
      src=$(printf '%s\n' "$list" | sed -n "${pick}p")
      [ -n "$src" ] || die "没有第 $pick 条。跑 rex phone 看看有几条。" ;;
  esac

  need whisper-cli "brew install whisper-cpp"
  ensure_model
  mkdir -p "$REX_DIR"
  stamp=$(phone_stamp "$src")
  # 按前缀找而不是按精确名字：转写完音频会被改成带关键词的名字，
  # 用精确名字判断会认为没取过，于是又抠一份出来，落一个重复文件。
  out=$(ls -1 "$REX_DIR/${stamp}_phone"*.m4a "$REX_DIR/${stamp}_phone"*.wav 2>/dev/null | head -1)

  if [ -n "$out" ]; then
    say "${C_D}已经取过了：$out${C_0}"
  else
    out="$REX_DIR/${stamp}_phone.m4a"
    # 拷成单声道 AAC 再转写，不直接拿原件：一小时空间音频是 287 MB，
    # 转完 30 MB 上下；而且备忘录容器归 Voice Memos 管，删了备忘录原件就没了。
    # -map 0:a:0 显式选第一条音轨：.qta 里还有一条 apac 轨，别赌 ffmpeg 的默认选流。
    say "${C_D}取出来 → $out${C_0}"
    ffmpeg -hide_banner -loglevel error -i "$src" -map 0:a:0 \
           -ac 1 -ar 48000 -c:a aac -b:a 96k -y "$out" \
      || { rm -f "$out"; die "取不出音频。文件可能还没从 iCloud 下完，去手机或访达里打开一次再来。"; }
  fi

  report_file "$out"
  say ""
  transcribe_one "$out"
  say ""
  say "  ${C_D}认错词：whisper-prompt.txt（偏置）→ whisper-fix.txt（确定性替换），放在 ~/.config/rex/（没有就从 ${TOOLS_DIR}/ 拷模板过去）${C_0}"
}

# ------------------------------------------------------------------ 丢进来的文件

# AirDrop 过来的东西默认落在 ~/Downloads。这个命令就是那个「丢进来就能转」的入口：
# 列出可转的文件、按序号挑、走同一条转写流水线。
#
# 一条硬规矩：**只拷贝，绝不移动、绝不删除原件。**~/Downloads 是你的文件夹，
# 这个工具没有资格动里面的东西。
DROP_DIRS="${REX_DROP:-$HOME/Downloads:$HOME/Desktop}"

# 输出 TSV：序号 / 路径 / 目标名 / 秒 / 字节 / 是否已导入
drop_scan() {
  DROP_DIRS="$DROP_DIRS" REX_DIR="$REX_DIR" python3 <<'PY'
import os, re, sys, time, glob, subprocess

EXT = {".m4a",".mp3",".wav",".qta",".mov",".mp4",".m4v",".aac",".caf",
       ".aiff",".aif",".flac",".ogg",".opus",".webm",".mkv",".m4b"}

def stem_for(path):
    """iPhone 按**地点**给语音备忘录命名（Main St 4 / Central Library 7），
    这个名字有信息，不能扔掉换成时间戳。所以保留它，但要压短并且去掉下划线——
    下划线是本工具的字段分隔符，混进来会让「起没起过名」的判据失效。"""
    base = os.path.splitext(os.path.basename(path))[0]
    m = re.search(r"(\d+)\s*$", base)          # 结尾的编号是区分同地点多条的关键
    tail = m.group(1) if m else ""
    head = base[:m.start()] if m else base
    head = re.sub(r"['’]", "", head)
    head = re.sub(r"[^0-9A-Za-z一-鿿]+", "-", head).strip("-")
    segs, out = [s for s in head.split("-") if s], []
    for s in segs:                              # 按词截断，不从中间切断单词
        if out and len("-".join(out + [s])) > 15:
            break
        out.append(s)
    head = "-".join(out)
    return "-".join([p for p in (head, tail) if p]) or "drop"

rex = os.environ["REX_DIR"]
rows = []
for d in os.environ["DROP_DIRS"].split(":"):
    if not os.path.isdir(d):
        continue
    for name in os.listdir(d):
        p = os.path.join(d, name)
        if not os.path.isfile(p) or os.path.splitext(name)[1].lower() not in EXT:
            continue
        rows.append(p)
rows.sort(key=os.path.getmtime, reverse=True)

for i, p in enumerate(rows, 1):
    ts = time.strftime("%Y-%m-%d_%H%M", time.localtime(os.path.getmtime(p)))
    target = "%s_drop-%s" % (ts, stem_for(p))
    done = 1 if glob.glob(os.path.join(rex, target + "*")) else 0
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", p], stderr=subprocess.DEVNULL).decode().strip()
        dur = int(float(out.split(",")[0] or 0))
    except Exception:
        dur = 0
    print("\t".join([str(i), p, target, str(dur), str(os.path.getsize(p)), str(done)]))
PY
}

in_cmd() {
  rows=$(drop_scan)
  if [ -z "$rows" ]; then
    say "$(printf '%s' "$DROP_DIRS" | tr ':' ' ') 里没有可转的音视频文件。"
    say "  ${C_D}AirDrop 过来的东西默认落在 ~/Downloads。${C_0}"
    return 0
  fi

  if [ "$#" -eq 0 ]; then
    say "可以转的文件（改 REX_DROP 换扫描目录）"
    say ""
    printf '%s\n' "$rows" | while IFS=$'\t' read -r i p target dur size done; do
      # 颜色码要放在 %s 里、数字单独用 %2d 补齐——把色码算进 %2s 的宽度，
      # 那一列就会歪掉。
      c="$C_G"; tag=""
      [ "$done" = "1" ] && { c="$C_D"; tag="  ${C_D}已转过${C_0}"; }
      printf '  %s%2d%s  %4d 分  %6s  %s%s\n' "$c" "$i" "$C_0" \
        "$((dur / 60))" "$(du -h "$p" | cut -f1 | tr -d ' ')" "$(basename "$p")" "$tag"
    done
    say ""
    say "  转一个：${C_G}rex in 1${C_0}    转多个：rex in 1 3    全转：${C_G}rex in all${C_0}"
    say "  ${C_D}原件只读不动，只往 $REX_DIR 拷一份。约 8 倍速，先看上面的分钟数估时间。${C_0}"
    return 0
  fi

  need whisper-cli "brew install whisper-cpp"
  ensure_model
  mkdir -p "$REX_DIR"

  picks="$*"
  if [ "$picks" = "all" ]; then
    picks=$(printf '%s\n' "$rows" | awk -F'\t' '$6=="0" { print $1 }')
    [ -n "$picks" ] || { say "全都转过了。"; return 0; }
  fi

  for n in $picks; do
    case "$n" in ''|*[!0-9]*) warn "跳过「${n}」：要序号，比如 rex in 1"; continue ;; esac
    line=$(printf '%s\n' "$rows" | awk -F'\t' -v k="$n" '$1==k')
    [ -n "$line" ] || { warn "没有第 $n 个"; continue; }

    src=$(printf '%s' "$line" | cut -f2)
    target=$(printf '%s' "$line" | cut -f3)
    out="$REX_DIR/$target.m4a"

    have=$(ls -1 "$REX_DIR/$target"*.m4a 2>/dev/null | head -1)
    if [ -n "$have" ]; then
      say "${C_D}已经导过：$have${C_0}"
      out="$have"
    else
      say ""
      say "${C_D}$(basename "$src")  →  $(basename "$out")${C_0}"
      # 先试 -c:a copy：AAC 直接搬进 mp4 容器是无损且瞬时的，一个 130 分钟的
      # 文件不用重编码。源不是 AAC（wav / flac / opus）时 copy 会失败，再退回重编。
      if ! ffmpeg -hide_banner -loglevel error -i "$src" -map 0:a:0 -c:a copy -y "$out" 2>/dev/null; then
        say "  ${C_D}容器不兼容，重编成 AAC…${C_0}"
        ffmpeg -hide_banner -loglevel error -i "$src" -map 0:a:0 \
               -ac 1 -ar 48000 -c:a aac -b:a 96k -y "$out" \
          || { rm -f "$out"; warn "取不出音频：$src"; continue; }
      fi
    fi

    report_file "$out"
    say ""
    transcribe_one "$out"
  done
  say ""
  say "  ${C_D}原件仍在原处，一个字节没动。${C_0}"
}

# ------------------------------------------------------------------ 自检

# 录 3 秒扔掉，只报电平。存在的理由：macOS 在麦克风权限被拒、或者音频链路
# 出问题的时候，是**喂数字静音而不是报错**——ffmpeg 一切正常、文件照常生成、
# 什么提示都没有，等你录完一小时才发现是空的。实测踩过一次（蓝牙耳机掉线之后
# 内建麦克风持续输出 -91 dB，直接调 ffmpeg 也一样）。
# 放一声 880 Hz 的测试音（-14 dB、0.8 秒），同时用 audiocap 按给的参数录 3 秒，回声峰值 dB。
# 自己放声音自己听，不靠用户「这会儿正好在放东西」。起不来回 1。
tone_peak() {
  tmp="${TMPDIR:-/tmp}/rex-tone-$$"
  ffmpeg -hide_banner -loglevel error -f lavfi -i "sine=frequency=880:duration=0.8" \
         -af "volume=-14dB,afade=t=in:d=0.05,afade=t=out:st=0.7:d=0.1" -y "$tmp.wav" 2>/dev/null || return 1
  info=$("$CAP" "$@" --info) || { rm -f "$tmp.wav"; return 1; }
  r=$(printf '%s' "$info" | awk '{print $1}'); c=$(printf '%s' "$info" | awk '{print $2}')
  "$CAP" "$@" --seconds 3 > "$tmp.f32" 2>>"$LOG" &
  cp=$!
  sleep 1
  afplay "$tmp.wav" 2>/dev/null
  wait "$cp" 2>/dev/null
  peak=$(ffmpeg -hide_banner -nostats -f f32le -ar "$r" -ac "$c" -i "$tmp.f32" -af volumedetect -f null - 2>&1 \
         | awk '/max_volume/ { print $(NF-1) }')
  rm -f "$tmp.wav" "$tmp.f32"
  [ -n "$peak" ] || return 1
  printf '%s' "$peak"
}

# 测系统音频接口：先要权限（没问过会弹系统的授权框，等用户点），再放测试音用它录 3 秒。
# 收到了就把它设成录系统声音的默认（见 sys_path）。
check_sys_tap() {
  ensure_cap
  say "${C_D}问系统音频接口的权限……（第一次会弹「rex 录音采集」想录制系统音频的提示，点允许）${C_0}"
  if ! "$CAP" --system --info --request >/dev/null; then
    rm -f "$SYS_CFG"
    warn "✗ 系统音频接口用不了（原因在上面）。在那之前录系统声音照旧走 BlackHole 那条路。"
    return 1
  fi
  say "放一声测试音，同时用系统音频接口录 3 秒……"
  peak=$(tone_peak --system) || peak=""
  if [ -n "$peak" ] && awk -v p="$peak" 'BEGIN { exit !(p > -50) }'; then
    # 接口只在有程序放声音时才出数据（audiocap.swift 文件头）；audiocap 自己写静音顶着。这里验证一下：
    # 什么都不放录 2 秒，必须持续出数据，否则开录时对方还没说话就起不来
    say "再录 2 秒什么都不放的：接口安静时也得持续出数据……"
    n=$("$CAP" --system --seconds 2 2>>"$LOG" | wc -c | tr -d ' ')
    if [ "${n:-0}" -lt 100000 ]; then
      rm -f "$SYS_CFG"
      warn "✗ 什么都不放时系统音频接口不出数据（2 秒只收到 ${n:-0} 字节）。"
      say "  audiocap 往扬声器写静音那一手没生效，看 ${LOG} 里它的输出。在那之前录系统声音照旧走 BlackHole。"
      return 1
    fi
    mkdir -p "$(dirname "$SYS_CFG")"; echo tap > "$SYS_CFG"
    say "${C_G}✓ 系统音频接口收到了测试音（峰值 ${peak} dB）。${C_0}"
    say "  以后录系统声音都走它：不改输出设备，AirPods 怎么自动切换都不断，音量键照常用。"
    return 0
  fi
  rm -f "$SYS_CFG"
  warn "✗ 权限是有的，但系统音频接口没收到测试音（峰值 ${peak:-?} dB）。"
  say "  刚授权完音频服务有时要缓一下：再跑一次 rex check sys。还不行就看 ${LOG} 里 audiocap 的输出。"
  say "  在那之前，录系统声音照旧走 BlackHole 那条路。"
  return 1
}

check() {
  ensure_ad; ensure_cap; mkdir -p "$REX_DIR"
  what="${1:-mic}"
  PT_RESTORE=""; PT_UID=""; PT_NOTE=""
  peak=""
  case "$what" in
    mic)
      pick_mic mic >/dev/null || exit 1
      pat=$(mic_pattern mic)
      # 第一次会弹麦克风授权框，audiocap 等用户点；没给就在这儿停，不录一段全零出来
      info=$("$CAP" "$pat" --info) || exit 1
      r=$(printf '%s' "$info" | awk '{print $1}'); c=$(printf '%s' "$info" | awk '{print $2}')
      say "${C_D}录 3 秒试试：麦克风 $(printf '%s' "$info" | cut -d' ' -f3-)（说句话）${C_0}"
      t="${TMPDIR:-/tmp}/rex-check-$$.f32"
      "$CAP" "$pat" --seconds 3 > "$t" 2>>"$LOG"
      peak=$(ffmpeg -hide_banner -nostats -f f32le -ar "$r" -ac "$c" -i "$t" -af volumedetect -f null - 2>&1 \
             | awk '/max_volume/ { print $(NF-1) }')
      rm -f "$t" ;;
    sys)
      check_sys_tap && return 0
      say ""; say "${C_D}再测 BlackHole 那条老路：建直通、放测试音、从 BlackHole 录 3 秒${C_0}"
      # 要建直通，否则系统声音根本不进 BlackHole，测出来必然是静音
      setup_passthru
      peak=$(tone_peak BlackHole) || peak=""
      teardown_passthru "$PT_RESTORE" "$PT_UID" ;;
    *) die "rex check mic  或  rex check sys" ;;
  esac

  if [ -z "$peak" ] || awk -v p="${peak:--91}" 'BEGIN { exit !(p <= -90) }'; then
    printf '%s✗ 峰值 %s dB —— 精确的数字静音，这条路上没有数据。%s\n' "$C_R" "${peak:-?}" "$C_0"
    if [ "$what" = mic ]; then
      say "  1. 笔记本合着盖？内建麦克风在硬件上是断开的，开盖再试。"
      say "  2. 权限：系统设置 → 隐私与安全性 → 麦克风 → 「rex 录音采集」要开着。"
    else
      say "  1. 权限：系统设置 → 隐私与安全性 → 麦克风 → 「rex 录音采集」要开着"
      say "     （从 BlackHole 抓声音在系统看来也算「用麦克风」）。"
      say "  2. BlackHole 没装或没加载：audiocap --list 里该有「BlackHole 2ch」。"
    fi
    say "  3. 音频链路坏了（蓝牙设备掉线之后常见）。重启音频服务："
    say "     ${C_G}sudo killall coreaudiod${C_0}   ${C_D}（要输密码，声音会断一两秒）${C_0}"
    return 1
  fi
  say "${C_G}✓ 峰值 ${peak} dB，在收数据。${C_0}"
}

# ------------------------------------------------------------------ 转写

# 先下到 .part 再改名：中途断掉不会留下一个「看着像下好了」的半截文件。
fetch_model() {
  path="$1"; url="$2"; what="$3"
  [ -f "$path" ] && return 0
  say "第一次转写，要先下${what}："
  say "  ${C_D}$path${C_0}"
  mkdir -p "$(dirname "$path")"
  curl -fL --progress-bar -o "$path.part" "$url" || { rm -f "$path.part"; die "$what 下载失败"; }
  mv "$path.part" "$path"
}

ensure_model() {
  fetch_model "$WMODEL" "$WURL" "识别模型（约 550 MB，只下这一次）"
  [ -n "${NOVAD:-}" ] || fetch_model "$VMODEL" "$VURL" "VAD 模型（864 KB）"
}

# 转写后处理：先修无效字节，再做确定性替换，最后报字数。
#
# 无效字节这条是真机踩出来的：whisper.cpp 在中文分段边界上偶尔吐半个字，
# 文件里就留下一个不合法的 UTF-8 字节。合成语音的测试样本永远不会触发，
# 一转真实的十几分钟录音就崩——Python 抛 UnicodeDecodeError、tr 报
# Illegal byte sequence，替换那一层整个不执行，而且不容易看出来。
# 处理办法是解码时把坏字节换成 U+FFFD 并**把个数报出来**：不静默丢，
# 让人知道那个位置原本有东西。
#
# 替换本身是无条件字符串替换，中文没有词边界、会误伤，所以每一处都打印。
# 规则和风险说明在 whisper-fix.txt 里。
postprocess() {
  python3 - "$WFIX" "$1.txt" "$1.srt" <<'PY'
import io, os, sys

rules = []
if os.path.exists(sys.argv[1]):
    for line in io.open(sys.argv[1], encoding='utf-8'):
        line = line.strip()
        if line and not line.startswith('#') and '→' in line:
            a, b = line.split('→', 1)
            if a.strip():
                rules.append((a.strip(), b.strip()))

counted, bad, chars = {}, 0, 0
for path in sys.argv[2:]:
    if not os.path.exists(path):
        continue
    s = open(path, 'rb').read().decode('utf-8', 'replace')
    out = s
    for a, b in rules:
        n = out.count(a)
        if n:
            out = out.replace(a, b)
            # 只按 .txt 计数报给人看，.srt 是同一批内容的另一种排版，
            # 两边都报会让人以为改了两倍的地方。
            if path.endswith('.txt'):
                counted[(a, b)] = counted.get((a, b), 0) + n
    if path.endswith('.txt'):
        bad = s.count('�')
        chars = len(''.join(out.split()))
    if out != s or bad:
        io.open(path, 'w', encoding='utf-8').write(out)

for (a, b), n in counted.items():
    print("    替换 %d 处：%s → %s" % (n, a, b))
if bad:
    print("    ! 有 %d 处无效字节（whisper 在分段边界上吐了半个字），已标成 �" % bad)
print("CHARS %d" % chars)
PY
}

# 用稿子里的关键词给文件改名，把 2026-08-14_1609_phone 变成
# 2026-08-14_1609_phone_Projection-GUI-Session。一多了光看时间戳认不出谁是谁。
#
# 词由 tools/keywords.py 抽，纯词频、不联网——为了起个文件名把私人录音稿
# 发给某个 API，是拿「全程本地」这个承诺换便利，不划算。抽不出来就保持原名。
#
# 改名的边界：
#   · 转写稿（.txt/.srt）一律跟着改，那是本工具生成的
#   · 音频只在「本工具生成的、且还没改过名」时才跟着改。rex text 直接指过来的
#     外部文件（~/Downloads 里的播客之类）绝不动——那是别人的文件。
#   · --split 那一对（第三个参数）：两个音频各自保留 -mic / -sys，关键词接在后面，
#     X_both-mic_词.m4a + X_both-sys_词.m4a，对话稿叫 X_both_词.txt。-sys 不能挪到
#     词后面去：rex_trim.py 和 report_file 按「_both-sys」认系统声音、定静音阈值。
NEWBASE=""
rename_by_keywords() {
  base="$1"; audio="$2"; audio2="${3:-}"
  NEWBASE="$base"
  [ -n "${NORENAME:-}" ] && return 0
  [ -f "$TOOLS_DIR/keywords.py" ] || return 0

  # 先判「这份还没起过名吗」，再抽词。判据是文件名严格等于本工具生成的那个格式。
  # 少了这一步，第二次转写同一份就会把关键词接第二遍，变成
  # ..._Projection-GUI-Session_Projection-GUI.txt。
  stem=$(basename "${audio%.*}")
  pristine=""
  printf '%s' "$stem" \
    | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{4,6}_(mic|sys|both|phone|drop-[^_]*)(-mic|-sys)?$' \
    && pristine=1

  if [ "$(dirname "$audio")" = "$REX_DIR" ] && [ -z "$pristine" ]; then
    return 0        # 自己的录音，已经起过名了，别再动
  fi

  kw=$(python3 "$TOOLS_DIR/keywords.py" "$base.txt" --glossary "$WPROMPT" 2>/dev/null)
  [ -n "$kw" ] || { say "  ${C_D}抽不出关键词（稿子太短或没有重复出现的词），保持原名${C_0}"; return 0; }

  new="${base}_${kw}"
  [ "$new" = "$base" ] && return 0
  for ext in txt srt; do
    [ -f "$base.$ext" ] && mv -f "$base.$ext" "$new.$ext"
  done

  # 音频只在「本工具生成的」时候跟着改。rex text 直接指过来的外部文件
  # （~/Downloads 里的播客之类）绝不动——那是别人的文件，只给转写稿起名。
  if [ -n "$pristine" ] && [ "$(dirname "$audio")" = "$REX_DIR" ]; then
    if [ -n "$audio2" ]; then
      for a in "$audio" "$audio2"; do
        mv -f "$a" "${a%.*}_${kw}.${a##*.}"
      done
      say "  ${C_D}两个音频一起改了名${C_0}"
    else
      ext="${audio##*.}"
      mv -f "$audio" "${new}.${ext}" && say "  ${C_D}音频一起改了名${C_0}"
    fi
  fi
  NEWBASE="$new"
}

# ------------------------------------------------------------------ 分轨 / 说话人
#
# 「谁在说话」靠分轨，不靠猜：麦克风那一路只有本机这边的人，系统声音那一路只有
# 电脑放出来的（通话对方、网课）。两轨各转各的，按时间合成对话稿，标签是对的。
# 合并、去回声、空轨报警都在 tools/speakers.py，理由写在那个文件头上。
#
# 分不开的三种：同一轨里的多个人（会议对面三个人都在系统声音里）、一个麦克风录的
# 多人谈话、混成一轨的老录音。那要靠声纹模型。

# 这个文件里有没有 rex both 存的分轨。有就打印「麦克风流号 系统声音流号」。
speaker_tracks() {
  ffprobe -v error -show_entries stream=index:stream_tags=handler_name -of csv=p=0 "$1" 2>/dev/null \
    | awk -F, '$2=="mic" { m=$1 } $2=="sys" { s=$1 } END { if (m != "" && s != "") print m " " s }'
}

# 一条轨里数字静音一共多少秒（只算连续 10 秒以上的）。文件结尾没闭合的那段也算上——
# silencedetect 有的版本在结尾补 silence_end，有的不补（rex_trim.py 同一处）。
silent_seconds() {
  ffmpeg -hide_banner -nostats -i "$1" -map "0:$2" -af silencedetect=noise=-85dB:d=10 \
         -f null - 2>&1 \
    | awk -v D="${3:-0}" '
        /silence_start:/ { s = $NF; open = 1 }
        /silence_duration:/ { split($0, a, "silence_duration: "); t += a[2]; open = 0 }
        END { if (open && D > s) t += D - s; printf "%d", t }'
}

# --split 录的那一对：给一半，打印另一半。名字可能已经被关键词改过
# （X_both-mic_某某.m4a），所以按「_both-mic / _both-sys」前面那截配对。
split_sibling() {
  sd=$(dirname "$1"); sb=$(basename "$1")
  case "$sb" in
    *_both-mic*) spre="${sb%%_both-mic*}"; soth=sys ;;
    *_both-sys*) spre="${sb%%_both-sys*}"; soth=mic ;;
    *) return 0 ;;
  esac
  ls -1 "$sd/${spre}_both-${soth}"*.m4a "$sd/${spre}_both-${soth}"*.wav 2>/dev/null | head -1
}

# whisper 只吃 16 kHz 单声道，而且它内置的解码器不一定认 m4a/AAC，
# 所以一律先用 ffmpeg 转一遍，别赌它能直接读。流要显式选：iPhone 的空间音频
# （.qta）里还有一条 ffmpeg 解不了的 apac 轨，rex both 的文件里有三条轨，
# 别把选流这件事交给默认启发式。
#
# 先按样本原样解码。只有解出来的时长明显短于标称时长——采集时丢过样本、时间戳是对的——
# 才重来一遍，用 aresample=async=1 按**时间戳**把空隙补上静音。不补的话洞会被挤掉：
# 2026-09-22 一条标称 49:55 的录音（avfoundation 采集，丢了 14% 样本）转成 wav
# 只剩 42:53，字幕时间轴越往后越早，到结尾差 7 分钟。
#
# 第一版是**一律**补，以为「没有洞时它什么都不做」。错了：2026-10-12 收件箱进来一条别的 App
# 导出的 65 分钟 AAC，每个包装 1024 个样本，时间戳却按 960 走（20 毫秒一帧的来源转过来的），
# 隔几十个包再跳一次 1408/1472。补空的滤镜追着时间戳每秒删几回样本、塞几回静音，5 分钟里
# 1882 处零值空洞（直接解码只有 8 处）。听着只是一点卡顿，VAD 却判成没人说话——65 分钟转出
# 「这个才是」4 个字，不报错。样本一个没少，时间戳不规整而已，这种文件不能按时间戳去「修」。
to16k() {   # to16k 源文件 流 输出.wav
  ffmpeg -hide_banner -loglevel error -y -i "$1" -map "$2" \
      -ar 16000 -ac 1 -c:a pcm_s16le "$3" || return 1
  want=$(ffprobe -v error -select_streams "${2#0:}" -show_entries stream=duration -of csv=p=0 "$1" 2>/dev/null | head -1)
  case "$want" in ""|N/A) want=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$1" 2>/dev/null) ;; esac
  got=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$3" 2>/dev/null)
  # 少 1% 以上才算有洞：AAC 编码器的填充只有零点几秒
  if awk -v w="$want" -v g="$got" 'BEGIN { exit !(w + 0 > 0 && g + 0 > 0 && g < w * 0.99) }'; then
    say "  ${C_D}采集时丢过样本（解出 ${got%.*} 秒，标称 ${want%.*} 秒），按时间戳补上空隙再转${C_0}" >&2
    ffmpeg -hide_banner -loglevel error -y -i "$1" -map "$2" \
        -af aresample=async=1:min_hard_comp=0.001:first_pts=0 \
        -ar 16000 -ac 1 -c:a pcm_s16le "$3"
  fi
}

whisper_args() {
  wargs=()
  [ -f "$WPROMPT" ] && wargs+=( --prompt-file "$WPROMPT" )
  if [ -z "${NOVAD:-}" ] && [ -f "$VMODEL" ]; then
    wargs+=( --vad-model "$VMODEL" --vad-pad "$VPAD" )
  else
    wargs+=( --no-vad )
  fi
}

# 两轨各转各的，再按时间合成一份对话稿。
# 参数：输出前缀  麦克风源 流  系统声音源 流
# 分轨 m4a 是同一个文件的 1、2 号流；--split 那一对是两个文件各自的 0:a:0。
SPK_CHARS=0
transcribe_speakers() {
  out="$1"; fa="$2"; ma="$3"; fb="$4"; mb="$5"
  work=$(mktemp -d "${TMPDIR:-/tmp}/rex-spk.XXXXXX") || return 1
  whisper_args
  for side in a b; do
    if [ "$side" = a ]; then src="$fa"; map="$ma"; who="$NAME_A"
    else src="$fb"; map="$mb"; who="$NAME_B"; fi
    say "  ${C_D}── ${who}那一轨 ──${C_0}"
    to16k "$src" "$map" "$work/$side.wav" \
      || { warn "  转 16k 单声道失败：${src}（${map}）"; rm -rf "$work"; return 1; }
    python3 "$TOOLS_DIR/whisper_run.py" \
        --model "$WMODEL" --audio "$work/$side.wav" --out "$work/$side" \
        --lang "${LANG_OPT:-auto}" ${wargs[@]+"${wargs[@]}"}
    wrc=$?
    # 崩了要说是崩了。不说的话这一轨按空的处理，下游会报成「VAD 没找到人声」——
    # 把故障说成了安静。
    [ "$wrc" -eq 0 ] || warn "  whisper 在${who}那一轨上出错（退出码 ${wrc}），这一轨按空的处理"
    rm -f "$work/$side.wav"
    [ -f "$work/$side.srt" ] || : > "$work/$side.srt"
    [ -f "$work/$side.txt" ] || : > "$work/$side.txt"
    # whisper-fix 的替换在单轨上先做，合出来的稿子就已经是改过的
    postprocess "$work/$side" | grep -v '^CHARS ' || true
  done
  info=$(python3 "$TOOLS_DIR/speakers.py" --a "$work/a.srt" --b "$work/b.srt" \
           --names "${NAME_A},${NAME_B}" --audio-a "$fa" --map-a "$ma" \
           --audio-b "$fb" --map-b "$mb" --out "$out")
  rc=$?
  rm -rf "$work"
  printf '%s\n' "$info" | grep -v '^CHARS ' || true
  [ "$rc" -eq 0 ] || { warn "  合成对话稿失败（speakers.py 退出码 ${rc}）"; return 1; }
  SPK_CHARS=$(printf '%s\n' "$info" | awk '/^CHARS /{ print $2 }')
  SPK_CHARS=${SPK_CHARS:-0}
  return 0
}

# 对话稿写完之后：起名、报结果。第三个参数是 --split 那一对的另一个音频。
finish_speakers() {
  out="$1"; fa="$2"; fb="${3:-}"
  if [ "${SPK_CHARS:-0}" -eq 0 ]; then
    say "  ${C_Y}○${C_0} 两轨都没转出字 —— VAD 没找到人声"
    return 0
  fi
  rename_by_keywords "$out" "$fa" "$fb"
  say "  ${C_G}✓${C_0} $NEWBASE.txt   ${C_D}${SPK_CHARS} 字 · 对话稿${C_0}"
  say "     ${C_D}$(basename "$NEWBASE").srt（带时间轴，每条前面写着是谁）${C_0}"
}

# --split 那一对：合成一份，以 X_both 为名（去掉 -mic / -sys）。
transcribe_pair() {
  pb=$(basename "$1")
  pout="$(dirname "$1")/${pb%%_both-mic*}_both"
  say "${C_D}转写 $(basename "$1") + $(basename "$2") …（--split 的一对，按说话人合成一份）${C_0}"
  transcribe_speakers "$pout" "$1" 0:a:0 "$2" 0:a:0 || return 1
  finish_speakers "$pout" "$1" "$2"
}

transcribe_one() {
  f="$1"
  [ -f "$f" ] || { warn "没有这个文件：$f"; return 1; }

  out="${f%.*}"

  # rex both 录的文件里存着两路原始信号：按说话人出对话稿，不转混音那条
  st=$(speaker_tracks "$f")
  if [ -n "$st" ]; then
    say "${C_D}转写 $(basename "$f") …（分轨：${NAME_A} = 麦克风，${NAME_B} = 系统声音）${C_0}"
    transcribe_speakers "$out" "$f" "0:${st%% *}" "$f" "0:${st##* }" || return 1
    finish_speakers "$out" "$f"
    return 0
  fi

  tmp="${TMPDIR:-/tmp}/rex-whisper-$$-$(basename "$out").wav"
  to16k "$f" 0:a:0 "$tmp" || { warn "转 16k 单声道失败：$f"; return 1; }
  whisper_args

  say "${C_D}转写 $(basename "$f") …${C_0}"
  # 不直接调 whisper-cli，走 whisper_run.py。理由见那个文件的头部注释：
  # whisper 只在文件开头认一次语言，中英混说的录音后半段会被按第一种语言硬解，
  # 而且不报错——它会掉进重复陷阱，把同一句话打印几百遍。
  # whisper_run.py 负责先探语言、分段、各段用自己的语言转、再把时间轴接回来。
  python3 "$TOOLS_DIR/whisper_run.py" \
      --model "$WMODEL" --audio "$tmp" --out "$out" \
      --lang "${LANG_OPT:-auto}" ${wargs[@]+"${wargs[@]}"}
  rc=$?

  if [ ! -f "$out.txt" ]; then
    rm -f "$tmp"
    warn "whisper 没有写出 $out.txt（退出码 ${rc}）"
    return 1
  fi
  # 字数由 postprocess 直接给：wc -m 数的是字符还是字节要看 locale，
  # 而且遇到无效字节会直接罢工——那个数不能靠 shell 算。
  info=$(postprocess "$out")
  printf '%s\n' "$info" | grep -v '^CHARS ' || true
  n=$(printf '%s\n' "$info" | awk '/^CHARS /{ print $2 }')
  n=${n:-0}
  if [ "$n" -eq 0 ]; then
    rm -f "$tmp"
    # 空不是失败，是 VAD 判定这一轨没人说话。明说出来，别让人对着 0 字发呆。
    say "  ${C_Y}○${C_0} $(basename "$out").txt 是空的 —— 这一轨 VAD 没找到人声"
    return 0
  fi
  # --who：按声纹分人，稿子换成对话稿。要用上面那个 16k wav，所以删 tmp 放在这之后。
  if [ -n "${WHO:-}" ]; then diarize_files "$f" "$out" "$tmp" || true; fi
  rm -f "$tmp"
  rename_by_keywords "$out" "$f"
  say "  ${C_G}✓${C_0} $NEWBASE.txt   ${C_D}$n 字${C_0}"
  say "     ${C_D}$(basename "$NEWBASE").srt（带时间轴）${C_0}"
  return 0
}

# ------------------------------------------------------------------ 声纹分人（rex who）
#
# 给「一路声音里有好几个人」的录音分人：手机录的线下谈话、2026-10-11 之前混成一轨的
# rex both。靠 sherpa-onnx 的声纹模型猜，是推测——新的 rex both 用不着，它录的时候
# 就分轨了。为什么用它、怎么标定的、人数为什么不能全自动判，见 tools/diarize.py 文件头。
DIAR_DIR="${REX_DIAR_DIR:-$HOME/.cache/sherpa-onnx}"   # diarize.py 认同一个变量
DIAR_VER="v1.13.8"
DIAR_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download"

diar_ready() {
  ls "$DIAR_DIR"/sherpa-onnx-v*-osx-*/bin/sherpa-onnx-offline-speaker-diarization >/dev/null 2>&1 \
    && [ -f "$DIAR_DIR/sherpa-onnx-pyannote-segmentation-3-0/model.onnx" ] \
    && [ -f "$DIAR_DIR/campplus_zh_en.onnx" ]
}

# 第一次用时去下程序和两个模型（约 50 MB），放缓存目录，不进仓库。
# --http1.1 和重试是踩出来的：GitHub 的下载走 HTTP/2 时撞过一次 framing error。
diar_get() {   # diar_get 网址 存成
  curl -fL --http1.1 --retry 5 --retry-delay 2 --progress-bar -o "$2.part" "$1" \
    && mv "$2.part" "$2" || { rm -f "$2.part"; return 1; }
}
ensure_diar() {
  diar_ready && return 0
  arch=arm64; [ "$(uname -m)" = arm64 ] || arch=universal2
  say "第一次按声纹分人，要先下 sherpa-onnx 和两个模型（约 50 MB，只下这一次）："
  say "  ${C_D}$DIAR_DIR${C_0}"
  mkdir -p "$DIAR_DIR"
  ( cd "$DIAR_DIR" \
    && diar_get "$DIAR_URL/$DIAR_VER/sherpa-onnx-$DIAR_VER-osx-$arch-shared-no-tts.tar.bz2" sherpa.tar.bz2 \
    && tar -xjf sherpa.tar.bz2 && rm -f sherpa.tar.bz2 \
    && diar_get "$DIAR_URL/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2" seg.tar.bz2 \
    && tar -xjf seg.tar.bz2 && rm -f seg.tar.bz2 \
    && diar_get "$DIAR_URL/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx" campplus_zh_en.onnx ) \
    || { warn "  下载 sherpa-onnx 失败"; return 1; }
  diar_ready || { warn "  sherpa-onnx 下下来了，但找不到程序或模型（${DIAR_DIR}）"; return 1; }
}

# 已经有 .srt 的录音：按声纹分人，把 .txt / .srt 换成对话稿。wav 是 16k 单声道。
diarize_files() {
  df="$1"; dout="$2"; dwav="$3"
  ensure_diar || return 1
  dargs=( --wav "$dwav" --srt "$dout.srt" --out "$dout" )
  case "${WHO:-auto}" in auto) ;; *) dargs+=( --speakers "$WHO" ) ;; esac
  # 混成一轨的老 rex both：两边分别是本机麦克风和通话那头，频谱能对上「我 / 对方」
  case "$(basename "$df")" in *_both.*|*_both_*) dargs+=( --call "$df" ) ;; esac
  say "  ${C_D}按声纹分人…${C_0}"
  dinfo=$(python3 "$TOOLS_DIR/diarize.py" "${dargs[@]}")
  drc=$?
  printf '%s\n' "$dinfo" | grep -v '^CHARS ' || true
  case "$drc" in
    0|5) ;;    # 5 = 只听出一个人，稿子保持原样，不算失败
    *) warn "  分人没成功（diarize.py 退出码 ${drc}），稿子保持原样" ;;
  esac
  return "$drc"
}

# rex who [文件] [人数]：已经转写过的不用重转，只把稿子换成对话稿。不给文件就是最近一条。
who_cmd() {
  wf=""; wn=""
  for x in "$@"; do
    case "$x" in ''|*[!0-9]*) wf="$x" ;; *) wn="$x" ;; esac
  done
  [ -n "$wn" ] && WHO="$wn"
  [ -n "${WHO:-}" ] || WHO=auto
  if [ -z "$wf" ]; then
    wf=$(ls -1t "$REX_DIR"/*.m4a "$REX_DIR"/*.wav 2>/dev/null | head -1)
    [ -n "$wf" ] || die "$REX_DIR 里还没有录音。"
  fi
  [ -f "$wf" ] || die "没有这个文件：$wf"
  if [ -n "$(speaker_tracks "$wf")" ]; then
    say "这条是分轨录的，rex text 出的已经是「${NAME_A} / ${NAME_B}」对话稿，标签是确定的，不用声纹猜。"
    return 0
  fi
  if [ ! -f "${wf%.*}.srt" ]; then
    say "${C_D}$(basename "$wf") 还没转写过，先转写${C_0}"
    need whisper-cli "brew install whisper-cpp"
    ensure_model
    transcribe_one "$wf"
    return $?
  fi
  say "${C_D}给 $(basename "$wf") 分人（用已有的转写，不重转）${C_0}"
  wtmp="${TMPDIR:-/tmp}/rex-who-$$.wav"
  to16k "$wf" 0:a:0 "$wtmp" || { warn "转 16k 单声道失败：$wf"; return 1; }
  diarize_files "$wf" "${wf%.*}" "$wtmp"
  wrc=$?
  rm -f "$wtmp"
  [ "$wrc" -eq 0 ] && say "  ${C_G}✓${C_0} ${wf%.*}.txt   ${C_D}对话稿，.srt 每条也带着名字${C_0}"
  return 0
}

# 不给文件就转最近一次录音。--split 录出来的那一对合成一份对话稿；
# 只给了其中一个文件也一样（另一半在同一个文件夹里就带上）。
text() {
  need whisper-cli "brew install whisper-cpp"
  need ffmpeg "brew install ffmpeg"
  ensure_model

  if [ "$#" -gt 0 ]; then
    targets=$(printf '%s\n' "$@")
  else
    newest=$(ls -1t "$REX_DIR"/*.m4a "$REX_DIR"/*.wav 2>/dev/null | head -1)
    [ -n "$newest" ] || die "$REX_DIR 里还没有录音。先 rex 录一段。"
    stem=$(basename "$newest" | sed -E 's/(-mic|-sys)?\.(m4a|wav)$//')
    targets=$(ls -1 "$REX_DIR/$stem"*.m4a "$REX_DIR/$stem"*.wav 2>/dev/null)
  fi

  # 管道里的 while 跑在子 shell 里，tdone 只在这个循环内有效——够用了。
  tdone="|"
  printf '%s\n' "$targets" | while IFS= read -r tf; do
    [ -n "$tf" ] || continue
    case "$tdone" in *"|$tf|"*) continue ;; esac
    tsib=$(split_sibling "$tf")
    if [ -n "$tsib" ]; then
      case "$(basename "$tf")" in
        *_both-mic*) ta="$tf"; tb="$tsib" ;;
        *)           ta="$tsib"; tb="$tf" ;;
      esac
      tdone="${tdone}${ta}|${tb}|"
      transcribe_pair "$ta" "$tb"
    else
      transcribe_one "$tf"
    fi
  done
  say ""
  say "  ${C_D}认错词：先往 whisper-prompt.txt 里加（偏置，可能不生效）；${C_0}"
  say "  ${C_D}还是错就写进 whisper-fix.txt 做确定性替换。两个都放 ~/.config/rex/（没有就从 ${TOOLS_DIR}/ 拷模板过去）${C_0}"
}

# ------------------------------------------------------------------ 一条龙（rex go / rex auto）
#
# 丢进一条录音，自动走完：转写 → 分人 → Claude 校对 → 校对报告 → Claude 分析（留一个能接着聊
# 的会话）。前两步全在本地；后两步把稿子交给 Claude，走本机 `claude` 命令行的登录。
# 校对为什么只收修改清单、拿不准的为什么不改，见 tools/proofread.py；分析和会话见 tools/analyze.py。
#
# 自动触发靠 launchd 盯着收件箱（rex auto install）。收件箱放在 ~/Recordings 底下，不放
# ~/Downloads、iCloud Drive：那几处受 macOS 隐私保护（TCC），launchd 起的进程读它们会被拦。
INBOX="${REX_INBOX:-$REX_DIR/收件箱}"
INBOX_LABEL="${REX_INBOX_LABEL:-local.rex.inbox}"
INBOX_LOG="${REX_INBOX_LOG:-$HOME/Library/Logs/rex-inbox.log}"
# launchd 起的进程读不了 ~/Documents 里的脚本（macOS 隐私保护，实测 Operation not permitted；
# 换成 /bin/sh -c 起也一样）。所以 rex auto 装的是一份放在家目录下的脚本副本，不在受保护的
# 目录里。仓库里的脚本一改，你下次在终端里跑任何 rex 命令时 sync_runtime 顺手同步过去。
RUNTIME="${REX_RUNTIME:-$HOME/.local/share/rex-runtime}"
MEDIA_GLOB='m4a|mp3|wav|qta|mov|mp4|m4v|aac|caf|aiff|aif|flac|ogg|opus|webm|mkv|m4b'

sync_runtime() {
  [ -d "$RUNTIME/tools" ] || return 0
  case "$TOOLS_DIR" in "$RUNTIME"/*) return 0 ;; esac          # 自己就是那份副本
  if [ -f "$RUNTIME/.synced" ] && [ -z "$(find "$TOOLS_DIR" -type f -newer "$RUNTIME/.synced" \
       -not -path '*/__pycache__/*' -print 2>/dev/null | head -1)" ]; then
    return 0
  fi
  rsync -a --delete --exclude __pycache__ "$TOOLS_DIR/" "$RUNTIME/tools/" 2>/dev/null \
    && touch "$RUNTIME/.synced"
}

# 静默通知（不加提示音：可能正在录别的东西）。双引号会打断 AppleScript，先换掉。
notify() {
  t=$(printf '%s' "$1" | tr '"' "'"); m=$(printf '%s' "$2" | tr '"' "'")
  osascript -e "display notification \"${m}\" with title \"${t}\"" >/dev/null 2>&1 || true
}

is_dialogue() {   # 转写稿已经是「[时间] 名字：」的对话稿了吗
  [ -f "$1" ] && head -1 "$1" | grep -qE '^\[[0-9:]+\] [^：]{1,12}：'
}

# 收件箱里的文件拷进 REX_DIR（命名和 rex in 一样：修改时间_drop-原名）。打印拷进去的路径。
import_drop() {
  src="$1"
  target=$(DROP_DIRS="$(dirname "$src")" drop_scan | awk -F'\t' -v p="$src" '$2==p { print $3; exit }')
  [ -n "$target" ] || return 1
  have=$(ls -1 "$REX_DIR/$target"*.m4a 2>/dev/null | head -1)
  if [ -n "$have" ]; then printf '%s\n' "$have"; return 0; fi
  out="$REX_DIR/$target.m4a"
  if ! ffmpeg -hide_banner -loglevel error -i "$src" -map 0:a:0 -c:a copy -y "$out" 2>/dev/null; then
    ffmpeg -hide_banner -loglevel error -i "$src" -map 0:a:0 -ac 1 -ar 48000 -c:a aac -b:a 96k -y "$out" \
      || { rm -f "$out"; return 1; }
  fi
  printf '%s\n' "$out"
}

# .校对.json 里记着没校成的行吗（一份校对失败了，下次 rex go 只补那几段）
has_failed() {
  [ -f "$1" ] && python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1])).get("failed") else 1)' "$1" 2>/dev/null
}

# 一份录音走完全程。参数是 REX_DIR 里的音频；转写过的不重转，分过人的不重分。
# 同一条录音同一时刻只让一个 rex go 处理：录音台排的、收件箱监视起的、终端里手敲的会撞上——两份 whisper
# 同时转，后完成的 mv -f 盖掉先完成并且已经校对过的稿子。锁按「目录 + 文件名开头的日期时刻」算（转写后按
# 关键词改名不影响），放 ~/.cache/rex/locks，里面记 PID，进程不在了就算残留。录音台按同一个算法查它（rex_app.py
# 的 go_lock_id），所以这里的算法变了那边要跟着变
go_lock_id() {
  b=$(basename "$1"); b="${b%.*}"
  case "$b" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9][0-9][0-9]*)
      k="${b%%_*}_$(printf '%s' "${b#*_}" | cut -c1-6 | tr -cd '0-9')" ;;
    *) k="$b" ;;
  esac
  printf '%s/%s' "$(cd "$(dirname "$1")" && pwd)" "$k" | shasum | cut -c1-16
}

go_one() {
  lk="$HOME/.cache/rex/locks/$(go_lock_id "$1").go"
  mkdir -p "$HOME/.cache/rex/locks"
  if ! mkdir "$lk" 2>/dev/null; then
    op=$(cat "$lk/pid" 2>/dev/null)
    if [ -n "$op" ] && kill -0 "$op" 2>/dev/null; then
      warn "这一条正在被别处处理（进程 ${op}：收件箱监视或另一个终端），这里不重复做"; return 1
    fi
    rm -rf "$lk"; mkdir "$lk" 2>/dev/null || { warn "建不了处理锁 ${lk}"; return 1; }
  fi
  echo $$ > "$lk/pid"
  go_one_inner "$1"; rc=$?
  rm -rf "$lk"
  return $rc
}

go_one_inner() {
  g="$1"
  [ -f "$g" ] || { warn "没有这个文件：$g"; return 1; }
  say ""
  say "${C_G}▶ $(basename "$g")${C_0}"
  gb="${g%.*}"
  if [ ! -f "$gb.srt" ]; then
    # 转写完会按关键词改名，新名字在 NEWBASE。稿子是空的那条路不改名、也不设它——
    # 不先清掉的话，收件箱里连着处理两条时，会把上一条的名字当成这一条
    NEWBASE=""
    transcribe_one "$g" || return 1
    gb="${NEWBASE:-$gb}"
  elif [ -z "$(speaker_tracks "$g")" ] && ! is_dialogue "$gb.txt"; then
    gtmp="${TMPDIR:-/tmp}/rex-go-$$.wav"
    if to16k "$g" 0:a:0 "$gtmp"; then diarize_files "$g" "$gb" "$gtmp" || true; fi
    rm -f "$gtmp"
  fi
  if [ ! -s "$gb.srt" ]; then
    say "  ${C_D}稿子是空的，后面的校对和分析跳过${C_0}"
    notify "rex go：$(basename "$gb")" "没转出字（录音里没有人声？），校对和分析跳过"   # 收件箱先报过「开始处理」，得有个下文
    return 0
  fi
  name=$(basename "$gb")

  [ -f "$g" ] || g=$(ls -1 "$gb".m4a "$gb".wav 2>/dev/null | head -1)     # 转写时可能改了名

  # 稿子短得离谱就别交给 Claude：2026-10-12 那条 65 分钟只转出「这个才是 / Thank you.」
  # （原因见 to16k 的注释），校对和分析只会对着几个字认真地编。每分钟不到约 10 个汉字才拦
  gsec=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$g" 2>/dev/null)
  gbytes=$(wc -c < "$gb.txt" 2>/dev/null | tr -d ' ')
  if awk -v s="$gsec" -v b="${gbytes:-0}" 'BEGIN { exit !(s + 0 >= 300 && b + 0 < s / 2) }'; then
    warn "  $(( ${gsec%.*} / 60 )) 分钟的录音只转出 ${gbytes} 字节，转写多半出了问题，先不交给 Claude"
    notify "rex go：转写可能失败" "${name}：$(( ${gsec%.*} / 60 )) 分钟只转出几个字，没做校对和分析，看一眼稿子"
    return 0
  fi

  # 校对过、分析过的不重做，和转写一样。同一条录音再丢进收件箱一次的话，重校的是已经改过的
  # 稿子，报告会被「改了 0 处」盖掉，第一次改了什么就看不到了；分析也会再开一个会话
  say "  ${C_D}── Claude 校对 ──${C_0}"
  pmode=full
  if [ -f "$gb.校对.md" ]; then
    if has_failed "$gb.校对.json"; then
      say "  ${C_D}上次有几段没校成，这次只补那几段${C_0}"
      pmode=--retry
    else
      say "  ${C_D}校对过了，不重校（要重校先删掉 ${name}.校对.md）${C_0}"
      pmode=""
    fi
  fi
  if [ -z "$pmode" ]; then
    ch=$(sed -n 's/^- 改了 \*\*\([0-9]*\)\*\* 处 · 拿不准、没改 \*\*\([0-9]*\)\*\* 处.*/\1 \2/p' "$gb.校对.md")
  else
    # 两个脚本的进度走 stderr、实时出现；stdout 只有给这里读的一行（CHANGES / ACCOUNT / SESSION）
    if [ "$pmode" = full ]; then pinfo=$(python3 "$TOOLS_DIR/proofread.py" "$gb")
    else pinfo=$(python3 "$TOOLS_DIR/proofread.py" "$gb" --retry); fi
    prc=$?
    if [ "$prc" -eq 3 ]; then
      why=$(printf '%s\n' "$pinfo" | sed -n 's/^ACCOUNT //p' | head -1)
      say "  ${C_Y}之后补做：${C_0}rex go \"${g}\""
      notify "rex go：Claude 用不了" "${why:-Claude 用不了}。${name} 已经转写好了，之后 rex go 补做校对和分析"
      return 0
    fi
    ch=$(printf '%s\n' "$pinfo" | awk '/^CHANGES /{ print $2 " " $3 }')
  fi
  # 一份都没校成时 proofread.py 不写报告、也不给 CHANGES：通知不能说成「改了 0 处」
  if [ -n "$ch" ]; then
    set -- $ch
    ptxt="校对改了 ${1} 处，${2} 处待你确认"
  else
    ptxt="校对没做成（看日志）"
  fi

  say "  ${C_D}── Claude 分析 ──${C_0}"
  arc=0
  if [ -f "$gb.分析.md" ]; then
    say "  ${C_D}分析过了，不重做（要重做先删掉 ${name}.分析.md）${C_0}"
    sid=$(head -20 "$gb.分析.md" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1)
  else
    ainfo=$(python3 "$TOOLS_DIR/analyze.py" "$gb" --cwd "$REX_DIR")
    arc=$?
    sid=$(printf '%s\n' "$ainfo" | awk '/^SESSION /{ print $2 }')
  fi

  say "  ${C_G}✓${C_0} ${gb}.txt   ${C_D}${ptxt}${C_0}"
  [ -f "$gb.校对.md" ] && say "     ${C_D}${name}.校对.md（改了什么、哪些拿不准）${C_0}"
  [ -f "$gb.分析.md" ] && say "     ${C_D}${name}.分析.md${C_0}"
  if [ -n "$sid" ]; then
    say "     接着聊：${C_G}rex chat \"${g}\"${C_0}"
  fi
  case "$arc" in
    0) notify "rex go：${name}" "${ptxt}；分析写好了" ;;
    3) why=$(printf '%s\n' "$ainfo" | sed -n 's/^ACCOUNT //p' | head -1)
       say "  ${C_Y}之后补做：${C_0}rex go \"${g}\""
       notify "rex go：Claude 用不了" "${why:-Claude 用不了}。${name}：${ptxt}，分析没做，之后 rex go 补上" ;;
    *) notify "rex go：${name}" "${ptxt}；分析没做成，看日志" ;;
  esac
}

# 收件箱里的原件挪进子文件夹（已处理 / 转不了）。重名加时间前缀，绝不覆盖。
inbox_move() {
  mkdir -p "$INBOX/$2"
  dest="$INBOX/$2/$(basename "$1")"
  [ -e "$dest" ] && dest="$INBOX/$2/$(date +%Y%m%d-%H%M%S)-$(basename "$1")"
  mv -n "$1" "$dest"
}

# 收件箱里不是音视频的东西：挪走并说一声。第一版只是不理它，结果用户拖进来的是一段文字
# （访达把拖进来的选中文字存成 .textClipping），监视器扫了三遍都没反应，看上去就是「丢进去没用」
inbox_reject() {
  case "$2" in
    textclipping) why="拖进来的是一段文字（文件名），不是文件本身。在访达里拖那个音频文件的图标" ;;
    "")           why="不是音视频文件（没有扩展名）" ;;
    *)            why="不是音视频文件（.${2}）" ;;
  esac
  warn "  $(basename "$1")：${why}。挪进「转不了」"
  notify "rex go：没法处理" "$(basename "$1")：${why}"
  inbox_move "$1" 转不了
}

# 收件箱：等文件写完（AirDrop、iCloud、拷贝都可能还在写），逐个处理，原件挪进「已处理」。
# 加锁：launchd 在拷文件的过程中会被目录变化触发好几次，不能同时跑两个。
go_inbox() {
  mkdir -p "$INBOX/已处理"
  lock="$REX_DIR/.go.lock"
  if ! mkdir "$lock" 2>/dev/null; then
    if [ -n "$(find "$lock" -maxdepth 0 -mmin +360 2>/dev/null)" ]; then
      rm -rf "$lock"; mkdir "$lock" 2>/dev/null || return 0      # 六小时还没删的是崩掉留下的
    else
      say "已经有一个 rex go 在处理收件箱，它做完会再扫一遍。"; return 0
    fi
  fi
  trap 'rm -rf "$lock"' EXIT
  say "$(date '+%Y-%m-%d %H:%M:%S') 扫收件箱 $INBOX"
  # 这一轮试过的不再试。第一版没有这个：取不出音频的文件留在原地，下一圈又被捡起来，死循环
  tried=$'\n'
  while :; do
    picked=""
    for p in "$INBOX"/*; do
      [ -f "$p" ] || continue
      case "$tried" in *$'\n'"$p"$'\n'*) continue ;; esac
      bn=$(basename "$p")
      case "$bn" in *.*) ext=$(printf '%s' "${bn##*.}" | tr 'A-Z' 'a-z') ;; *) ext="" ;; esac
      case "$ext" in crdownload|download|part|partial|tmp) continue ;; esac   # 浏览器还在往里下
      # 最近 15 秒还在变的不碰：写到一半的文件拿去转写，出来是半截稿子，还不报错
      age=$(( $(date +%s) - $(stat -f %m "$p") ))
      if [ "$age" -lt 15 ]; then picked=wait; continue; fi
      tried="$tried$p"$'\n'
      if ! printf '%s' "$ext" | grep -qE "^(${MEDIA_GLOB})\$"; then
        inbox_reject "$p" "$ext"
        continue
      fi
      if g=$(import_drop "$p"); then
        # 一收到就说一声：长录音要跑半小时以上，只在最后通知的话，中间看上去和没反应一样
        mins=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$g" 2>/dev/null \
               | awk '{ m = int($1 / 60 + 0.5); if (m > 0) printf "%d", m }')
        notify "rex go：开始处理" "${bn}${mins:+（${mins} 分钟）}。转写、分人、Claude 校对和分析，做完再通知你"
        # 要处理的是拷进 REX_DIR 的那份，所以原件成不成都挪走；没走完就对那份再 rex go
        go_one "$g" || warn "  ${bn} 没走完（看上面的报错）。拷进来的那份在 ${REX_DIR}，可以再 rex go 它"
        inbox_move "$p" 已处理
      else
        warn "  取不出音频：${bn}，挪进「转不了」"
        notify "rex go：没法处理" "${bn} 里取不出音频，挪进了 收件箱/转不了"
        inbox_move "$p" 转不了
      fi
      picked=1
    done
    case "$picked" in
      "") break ;;
      wait) sleep 5 ;;      # 有文件还在写，等它写完再扫
    esac
  done
}

go_cmd() {
  need whisper-cli "brew install whisper-cpp"
  ensure_model
  [ -n "${WHO:-}" ] || WHO=auto       # 一条龙默认分人；单人录音会自己判成一个人、不改稿子
  if [ -n "${GO_INBOX:-}" ]; then go_inbox; return $?; fi
  if [ "$#" -eq 0 ]; then
    gf=$(ls -1t "$REX_DIR"/*.m4a "$REX_DIR"/*.wav 2>/dev/null | head -1)
    [ -n "$gf" ] || die "$REX_DIR 里还没有录音。"
    set -- "$gf"
  fi
  for gf in "$@"; do
    case "$gf" in
      "$REX_DIR"/*) go_one "$gf" ;;
      *) gi=$(import_drop "$gf") && go_one "$gi" || warn "取不出音频：$gf" ;;
    esac
  done
}

# Claude 命令行自己的登录。终端里的 claude 被 ~/.zshrc 指到了别家接口（ANTHROPIC_BASE_URL、
# ANTHROPIC_AUTH_TOKEN……），带着这些变量起来根本不会让你登 Claude 账号——所以清掉再登。
# 清哪些和 claude_cli.py 的 env() 是同一份名单。登的是 Claude 订阅（--claudeai），只有 rex go
# 这种清掉变量再调 claude 的地方用它；平时在终端里敲 claude 照旧走原来的设置。
claude_uargs() {   # 结果在 uargs：env 用的一串 -u 变量名
  uargs=()
  for v in $(env | sed -n 's/^\(ANTHROPIC_[A-Za-z0-9_]*\)=.*/\1/p') \
           CLAUDE_CODE_USE_BEDROCK CLAUDE_CODE_USE_VERTEX CLAUDE_CODE_SUBAGENT_MODEL CLAUDE_CODE_EFFORT_LEVEL; do
    uargs+=( -u "$v" )
  done
}

login_cmd() {
  need claude "先装 Claude Code 命令行"
  claude_uargs
  if [ "${1:-}" = status ]; then
    env ${uargs[@]+"${uargs[@]}"} claude auth status
    return
  fi
  say "登录 Claude 账号（rex go 的校对和分析用它）。会打开浏览器，在那里确认就好。"
  env ${uargs[@]+"${uargs[@]}"} claude auth login --claudeai
  st=$(env ${uargs[@]+"${uargs[@]}"} claude auth status 2>/dev/null)
  case "$st" in
    *'"loggedIn": true'*)
      say "${C_G}✓ 登好了${C_0}。rex go 和收件箱从现在起用这个账号；你平时在终端里敲 claude 不受影响。" ;;
    *)
      warn "还是没登上。再跑一次 rex login，或者看上面的报错。" ;;
  esac
}

# ------------------------------------------------------------------ 录音台（rex app）
#
# 本地网页界面，tools/rex_app.py。从终端起（nohup，关了终端也接着跑）。录音的权限（麦克风、系统声音）
# 记在 audiocap 自己头上，从哪起都一样；读语音备忘录目录要的「完整磁盘访问权限」还是按终端 App 给的，
# 所以从有那项权限的终端起。只开在 127.0.0.1，口令和防跨站的做法见 rex_app.py 头部。
APP_PORT="${REX_APP_PORT:-8790}"
APP_LOG="${REX_APP_LOG:-$HOME/Library/Logs/rex-app.log}"
APP_PID="$REX_DIR/.app-$APP_PORT.pid"   # 起服务时记下的 PID，停的时候只认它（见 app_pid）。按端口分开：测试用的 8791 别和正式的混
app_up() {   # 端口上答应的是录音台吗（别把别的服务当成它）
  page=$(curl -s --max-time 2 "http://127.0.0.1:$APP_PORT/" 2>/dev/null)
  case "$page" in *"<title>录音台</title>"*) return 0 ;; *) return 1 ;; esac
}

# 录音台服务的 PID：先看起它时记下的，没有就看端口上监听的是谁。两条路都要核对命令行确实是 rex_app.py。
# **只按确切的 PID 停，不用 pkill -f**：2026-10-13 一条 pkill -f 关掉了 Chrome 和所有终端会话
app_pid() {
  p=$(cat "$APP_PID" 2>/dev/null)
  if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
    case "$(ps -o command= -p "$p" 2>/dev/null)" in *rex_app.py*) printf '%s' "$p"; return 0 ;; esac
  fi
  for p in $(lsof -nP -iTCP:"$APP_PORT" -sTCP:LISTEN -t 2>/dev/null); do
    case "$(ps -o command= -p "$p" 2>/dev/null)" in *rex_app.py*) printf '%s' "$p"; return 0 ;; esac
  done
  return 1
}

app_cmd() {
  case "${1:-open}" in
    open|start)
      if ! app_up; then
        mkdir -p "$(dirname "$APP_LOG")" "$REX_DIR"
        REX_DIR="$REX_DIR" REX_APP_PORT="$APP_PORT" nohup python3 "$TOOLS_DIR/rex_app.py" >> "$APP_LOG" 2>&1 &
        echo $! > "$APP_PID"
        for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do app_up && break; sleep 0.5; done
        app_up || die "录音台没起来，看日志：${APP_LOG}（端口 ${APP_PORT} 被占了的话，用 REX_APP_PORT 换一个）"
      fi
      [ "${1:-open}" = start ] || open "http://127.0.0.1:$APP_PORT/"
      say "录音台：${C_G}http://127.0.0.1:$APP_PORT/${C_0}"
      say "  ${C_D}Safari 里「文件 → 添加到程序坞」，以后从程序坞点开就像一个 App。关掉：rex app stop${C_0}"
      ;;
    stop)
      if p=$(app_pid); then
        kill "$p" 2>/dev/null
        for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$p" 2>/dev/null || break; sleep 0.3; done
        kill -0 "$p" 2>/dev/null && kill -KILL "$p" 2>/dev/null
        rm -f "$APP_PID"; say "录音台关了。"
      else say "录音台本来就没开。"; fi ;;
    restart) app_cmd stop; sleep 1; app_cmd open ;;
    status|*)
      if app_up; then say "${C_G}● 开着${C_0} http://127.0.0.1:$APP_PORT/    日志 $APP_LOG"
      else say "○ 没开（打开：rex app）"; fi ;;
  esac
}

# 接着和某条录音的分析会话聊。不能叫人直接在终端里 claude --resume：终端里的 claude 可能被 ~/.zshrc 指到了
# 别家接口，带着那些变量 resume，稿子就发到那边去了（余额不够时还会撞 402）。
# 清掉再起，用的是 rex login 那个 Claude 账号。会话存在 REX_DIR 下（analyze.py 的 --cwd），要在那儿 resume。
chat_cmd() {
  need claude "先装 Claude Code 命令行"
  if [ -z "${1:-}" ]; then
    am=$(ls -1t "$REX_DIR"/*.分析.md 2>/dev/null | head -1)
  else
    case "$1" in *.分析.md) am="$1" ;; *) am="${1%.*}.分析.md" ;; esac
  fi
  [ -n "$am" ] && [ -f "$am" ] || die "找不到分析报告${am:+：$am}。先对那条录音跑 rex go"
  sid=$(head -20 "$am" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1)
  [ -n "$sid" ] || die "${am} 里找不到会话号"
  claude_uargs
  say "接着聊：$(basename "${am%.分析.md}")（稿子、校对报告、第一轮分析都在这个会话里；/exit 退出）"
  cd "$REX_DIR" || die "进不去 $REX_DIR"
  exec env ${uargs[@]+"${uargs[@]}"} claude --resume "$sid"
}

auto_cmd() {
  plist="$HOME/Library/LaunchAgents/$INBOX_LABEL.plist"
  case "${1:-status}" in
    install)
      mkdir -p "$INBOX/已处理" "$HOME/Library/LaunchAgents" "$(dirname "$INBOX_LOG")"
      # 跑的是 $RUNTIME 里的副本，原因见 RUNTIME 那几行注释
      mkdir -p "$RUNTIME/tools"
      rsync -a --delete --exclude __pycache__ "$TOOLS_DIR/" "$RUNTIME/tools/" && touch "$RUNTIME/.synced" \
        || die "拷不出脚本副本到 $RUNTIME"
      # launchd 的 PATH 只有系统目录：装的时候把 ffmpeg / whisper / python3 / claude 所在目录写死
      lp=""
      for b in ffmpeg whisper-cli python3 claude; do
        d=$(dirname "$(command -v "$b" 2>/dev/null || echo /usr/bin/x)")
        case ":$lp:" in *":$d:"*) ;; *) lp="${lp:+$lp:}$d" ;; esac
      done
      lp="$lp:/usr/bin:/bin:/usr/sbin:/sbin"
      command -v claude >/dev/null 2>&1 || warn "  没找到 claude 命令行：转写会照做，校对和分析会跳过"
      cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$INBOX_LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$RUNTIME/tools/rex.sh</string><string>go</string><string>--inbox</string></array>
  <key>WatchPaths</key><array><string>$INBOX</string></array>
  <key>RunAtLoad</key><true/>
  <key>WorkingDirectory</key><string>/tmp</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$lp</string>
    <key>LANG</key><string>en_US.UTF-8</string>
    <key>LC_ALL</key><string>en_US.UTF-8</string>
    <key>REX_DIR</key><string>$REX_DIR</string>
  </dict>
  <key>StandardOutPath</key><string>$INBOX_LOG</string>
  <key>StandardErrorPath</key><string>$INBOX_LOG</string>
</dict>
</plist>
PLIST
      launchctl bootout "gui/$(id -u)/$INBOX_LABEL" 2>/dev/null || true
      launchctl bootstrap "gui/$(id -u)" "$plist" 2>/dev/null || launchctl load "$plist"
      say "${C_G}✓ 装好了${C_0}：往 ${C_G}${INBOX}${C_0} 里丢录音，就自动转写 → 分人 → Claude 校对 → 分析"
      say "  ${C_D}处理完原件挪进「已处理」，结果在 ${REX_DIR}；日志 ${INBOX_LOG}${C_0}"
      say "  ${C_D}访达里把这个文件夹拖到边栏，以后直接往里拖就行。打开它：rex auto open${C_0}"
      ;;
    uninstall|remove)
      launchctl bootout "gui/$(id -u)/$INBOX_LABEL" 2>/dev/null || launchctl unload "$plist" 2>/dev/null || true
      rm -f "$plist"
      case "$RUNTIME" in */rex-runtime) rm -rf "$RUNTIME" ;; esac
      say "收件箱监视已卸掉（收件箱文件夹和里面的东西不动）。"
      ;;
    open) mkdir -p "$INBOX"; open "$INBOX" ;;
    status|*)
      if launchctl print "gui/$(id -u)/$INBOX_LABEL" >/dev/null 2>&1; then
        say "${C_G}● 在盯着${C_0} $INBOX"
      else
        say "○ 没装（装：rex auto install）    收件箱：$INBOX"
      fi
      n=$(ls -1 "$INBOX" 2>/dev/null | grep -ciE "\.(${MEDIA_GLOB})\$" || true)
      d=$(ls -1 "$INBOX/已处理" 2>/dev/null | wc -l | tr -d ' ')
      say "  待处理 ${n:-0} 个 · 已处理 ${d:-0} 个"
      [ -d "$REX_DIR/.go.lock" ] && say "  ${C_Y}正在处理${C_0}（做到哪一步看下面的日志）"
      if [ -s "$INBOX_LOG" ]; then say "  ${C_D}日志最后几行：${C_0}"; tail -n 5 "$INBOX_LOG" | sed 's/^/    /'; fi
      ;;
  esac
}

# ------------------------------------------------------------------ 其它

# 现场采 1.5 秒，只报峰值。不碰正在录的那个 ffmpeg。
status_level() {
  idx="$1"; label="$2"; kind="${3:-mic}"
  [ -n "$idx" ] || { warn "  ${label}：找不到设备"; return; }
  t="${TMPDIR:-/tmp}/rex-lvl-$$.wav"
  ffmpeg -hide_banner -loglevel error -f avfoundation -i ":$idx" \
         -t 1.5 -ac 1 -ar 48000 -y "$t" 2>/dev/null
  p=""
  [ -f "$t" ] && p=$(ffmpeg -hide_banner -nostats -i "$t" -af volumedetect -f null - 2>&1 \
                     | awk '/max_volume/ { print $(NF-1) }')
  rm -f "$t"
  quiet=0
  if [ -z "$p" ] || awk -v v="${p:--91}" 'BEGIN { exit !(v < -70) }'; then quiet=1; fi

  # 系统声音这一路，安静**不等于**没信号——BlackHole 上没东西放就是 -91.0 dB
  # 的真数字零。所以先看路由，安静只是安静（同 watch_track 的注释）。
  if [ "$kind" = sys ]; then
    if ! sys_route_ok; then
      cn=$("$AD" name "$("$AD" default 2>/dev/null)" 2>/dev/null)
      printf '  %s%s ⚠ 路由断了：当前输出「%s」里没有 BlackHole%s\n' \
        "$C_Y" "$label" "${cn:-?}" "$C_0"
    elif [ "$quiet" = 1 ]; then
      printf '  %s%s 峰值 %s dB  路由正常，此刻没有声音在放%s\n' \
        "$C_D" "$label" "${p:-?}" "$C_0"
    else
      printf '  %s%s 峰值 %s dB  有声音%s\n' "$C_G" "$label" "$p" "$C_0"
    fi
    return
  fi

  if [ "$quiet" = 1 ]; then
    printf '  %s%s 峰值 %s dB  ⚠ 这一路没有信号%s\n' "$C_Y" "$label" "${p:-?}" "$C_0"
  else
    printf '  %s%s 峰值 %s dB  有声音%s\n' "$C_G" "$label" "$p" "$C_0"
  fi
}

status() {
  if [ ! -f "$STATE" ]; then
    o=$(orphan_recs)
    if [ -n "$o" ]; then
      warn "没有登记在录的，但后台有录音进程在跑：$(printf '%s\n' "$o" | awk '{print $2}' | xargs -n1 basename | tr '\n' ' ')"
      say "  跑 rex stop 把它停下、收好尾。"
      return 1
    fi
    say "没有在录。"; return 0
  fi
  if ! alive; then warn "状态文件还在，但进程已经没了。跑一次 rex stop 清掉。"; return 1; fi
  t0=$(getf start); el=$(( $(date +%s) - t0 ))
  say "${C_G}● 在录${C_0} · $(getf mode) · 已 $((el / 60)) 分 $((el % 60)) 秒"

  printf '%s\n' "$(getf files)" | tr '|' '\n' | while IFS= read -r f; do
    [ -n "$f" ] && say "  $f  $( [ -f "$f" ] && du -h "$f" | cut -f1 | tr -d ' ' )"
  done

  # 录制中的那份 m4a **读不出电平**：moov 索引写在文件末尾，没收尾之前
  # ffprobe 打不开它。文件大小也不能当判据——ffmpeg 大块缓冲，实测录了
  # 13 秒、两轨都有声音，中途看文件却一直停在 4K，按增长速率判会把两轨
  # 都误报成「没进来」。会中误报比不报更糟。
  #
  # 正确的做法是**另开一路采样**。同一个输入设备可以被多个进程同时打开
  # （实测两个 ffmpeg 同读内建麦克风都拿到真实信号），所以这里现场录 1.5 秒
  # 单独测一次峰值。开会时这一条最有用：对方的声音到底进没进来，
  # 得在会中就知道，不能等散会才发现录了一小时空气。
  say ""
  # audiocap 每半秒写一次各路的电平（.cap/*.level）：录进文件的是什么，这里显示的就是什么，
  # 不用再另开一路去采样。这次改动之前开始的录音没有电平文件，退回老办法
  shown=""
  for tag in mic sys; do
    lv=$(level_of "$tag") || continue
    shown=1
    set -- $lv
    now=$(date +%s)
    if [ "$tag" = mic ]; then nm="麦克风（你）"; else nm="系统声音（对方）"; fi
    if [ $((now - $3)) -gt 10 ]; then
      warn "  ✗ ${nm}：采集停了（$((now - $3)) 秒没有新数据）"
    elif [ "$2" -gt 0 ]; then
      if [ "$tag" = mic ] && [ $((now - $2)) -ge 3 ]; then warn "  ✗ ${nm}：数字静音已经 $((now - $2)) 秒，麦克风没接上"
      else say "  ○ ${nm}：此刻没声音（$((now - $2)) 秒）——放着东西的话就是没录进来"; fi
    else
      say "  ${C_G}✓${C_0} ${nm}：峰值 ${1} dB"
    fi
  done
  if [ "$(getf sys)" = blackhole ] && ! sys_route_ok; then
    warn "  ✗ 输出被切走了，BlackHole 收不到（路由监视两秒内会接回；一直这样就是接不回）"
  elif [ "$(getf sys)" = tap ]; then
    say "  ${C_D}系统声音走系统音频接口，不受输出设备切换影响${C_0}"
  fi
  if [ -z "$shown" ]; then
    case "$(getf mode)" in
      mic)  status_level "$(pick_mic mic)"     "麦克风（你）" ;;
      sys)  status_level "$(avf_index BlackHole)" "系统声音（对方）" sys ;;
      both) status_level "$(pick_mic both)"    "麦克风（你）" mic
            status_level "$(avf_index BlackHole)" "系统声音（对方）" sys ;;
    esac
  fi
  # ffmpeg 的进度是用 \r 刷新的，整个 log 是一行，取末尾看它还在不在动。
  last=$(tr '\r' '\n' < "$LOG" 2>/dev/null | grep "size=" | tail -1)
  [ -n "$last" ] && say "  ${C_D}ffmpeg: $last${C_0}"
}

list() {
  mkdir -p "$REX_DIR"
  n=$(ls -1 "$REX_DIR" 2>/dev/null | grep -cE '\.(m4a|wav)$')
  say "$REX_DIR  （共 $n 个）"
  # 先收进变量再遍历：直接 ls 两个 glob，缺其中一种后缀时 ls 会报错退非零，
  # 整个脚本跟着返回失败——列个目录不该是「失败」。
  recent=$(ls -1t "$REX_DIR"/*.m4a "$REX_DIR"/*.wav 2>/dev/null | head -10)
  [ -n "$recent" ] || { say "  （还没有录音）"; return 0; }
  printf '%s\n' "$recent" | while IFS= read -r f; do
    d=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null | cut -d. -f1)
    d=${d:-0}
    printf '  %-6s %6s  %s\n' "$(du -h "$f" | cut -f1 | tr -d ' ')" \
      "$((d / 60))'$(printf '%02d' $((d % 60)))\"" "$(basename "$f")"
  done
  return 0
}

# 切掉末尾的空白。只切末尾不切中间——中间的停顿是内容的一部分，切了时间轴就乱了。
# 判据和理由都在 tools/rex_trim.py 的文件头。
trim_cmd() {
  need ffmpeg "brew install ffmpeg"
  if [ "$#" -gt 0 ]; then
    targets=$(printf '%s\n' "$@")
  else
    newest=$(ls -1t "$REX_DIR"/*.m4a "$REX_DIR"/*.wav 2>/dev/null | head -1)
    [ -n "$newest" ] || die "$REX_DIR 里还没有录音。"
    # --split 录出来的是一对，两个都要切，不然两轨长度对不上
    stem=$(basename "$newest" | sed -E 's/(-mic|-sys)?\.(m4a|wav)$//')
    targets=$(ls -1 "$REX_DIR/$stem"*.m4a "$REX_DIR/$stem"*.wav 2>/dev/null)
  fi
  targs=()
  [ -n "${TRIM_TO:-}" ] && targs+=( --to "$TRIM_TO" )
  [ -n "${DRY:-}" ] && targs+=( --dry-run )
  printf '%s\n' "$targets" | while IFS= read -r f; do
    [ -n "$f" ] || continue
    python3 "$TOOLS_DIR/rex_trim.py" "$f" ${targs[@]+"${targs[@]}"}
    say ""
  done
}

# 从一个播客单集网页下音频，然后走同一条转写流水线。
# 取地址那部分在 tools/podcast_url.py——不需要任何第三方下载器，小宇宙这类页面
# 自己就把音频地址摆在 og:audio 里（那是给别的播放器嵌用的标准标签）。
url_cmd() {
  u="${1:-}"
  [ -n "$u" ] || die "要一个链接，比如 rex url https://www.xiaoyuzhoufm.com/episode/xxxx"
  need ffmpeg "brew install ffmpeg"
  mkdir -p "$REX_DIR"

  # 把输出原样透给终端（下载进度要能动），同时抄一份出来取 PATH 那一行
  log="${TMPDIR:-/tmp}/rex-url-$$.log"
  python3 "$TOOLS_DIR/podcast_url.py" "$u" --dir "$REX_DIR" 2>&1 | tee "$log"
  f=$(awk '/^PATH /{ sub(/^PATH /, ""); p=$0 } END { print p }' "$log")
  rm -f "$log"
  [ -n "$f" ] && [ -f "$f" ] || return 1

  need whisper-cli "brew install whisper-cpp"
  ensure_model
  transcribe_one "$f"
}

# 在转写稿里找东西。存在的理由很直接：自动起名之后文件名会变，
# 按记忆里的旧路径去翻必然扑空——那就得有个不依赖记住文件名的入口。
# 既搜文件名也搜正文，因为「那次讲 Docker 的」和「提到过赤心巡天的那段」
# 是两种完全不同的找法。
#
# 除了 REX_DIR，还会搜 ~/.config/rex/text-dirs 里登记的目录（一行一个目录，
# 里面放从别处抽出来的 .txt 文本）。用配置文件而不是写死路径：
# 硬盘会换、卷名会变，写死一次就得改两处。
find_cmd() {
  mkdir -p "$REX_DIR"
  q="${1:-}"
  REX_DIR="$REX_DIR" VM_DIR="$VM_DIR" python3 - "$q" <<'PY'
import os, re, sys, glob, time

q = sys.argv[1] if len(sys.argv) > 1 else ""
d = os.environ["REX_DIR"]
CONF = os.path.expanduser("~/.config/rex/text-dirs")

def read(p):
    # 稿子里可能有 whisper 吐的坏字节，搜索不该因此崩掉
    return open(p, "rb").read().decode("utf-8", "replace")

def when(p):
    # 日期从**文件名**里取，不用 mtime——重转写一次 mtime 就变成今天，
    # 一份 08-14 的录音会显示成 08-16，比不显示还糟。
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})_", os.path.basename(p))
    if m:
        return "%s-%s" % (m.group(2), m.group(3))
    return time.strftime("%m-%d", time.localtime(os.path.getmtime(p)))

def chars(t):
    return len("".join(t.split()))

# ---- 额外的文本目录。列了但不可达（硬盘没插）要**明说**——
#      静默少搜一个目录，结果就是「没找到」而其实是没去找。
extra, gone = [], []
if os.path.exists(CONF):
    for ln in open(CONF, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        p = os.path.expanduser(ln)
        (extra if os.path.isdir(p) else gone).append(p)

txts = sorted(glob.glob(os.path.join(d, "*.txt")), key=os.path.getmtime, reverse=True)
docs = []
for e in extra:
    docs += [(e, p) for p in sorted(glob.glob(os.path.join(e, "*.txt")))
             if not os.path.basename(p).startswith("_")]

if not txts and not docs:
    print("  %s 里还没有转写稿。" % d)
elif not q:
    if txts:
        print("  %s 里的转写稿（%d 份）\n" % (d, len(txts)))
        for p in txts:
            print("  %s  %5d 字  %s" % (when(p), chars(read(p)), os.path.basename(p)))
    else:
        print("  %s 里还没有转写稿。" % d)
    # 文档不逐个列——一千多行刷屏，而且没有时间线可言，只报个数。
    # 要看清单去 _索引.tsv，那里带字数和原始路径。
    for e in extra:
        n = len([1 for r, _ in docs if r == e])
        print("\n  另有 %d 份文档正文可搜：%s" % (n, e))
        print("  （不逐条列了，给个词搜就行；完整清单在 %s/_索引.tsv）" % e)
else:
    ql = q.lower()

    def show(p, t, label=""):
        name = os.path.basename(p)
        in_name = ql in name.lower()
        lines = [ln.strip() for ln in t.splitlines()
                 if ln.strip() and ql in ln.lower()]
        if not in_name and not lines:
            return False
        tag = "  （文件名命中）" if in_name and not lines else ""
        print("\n  %s  %5d 字  %s%s" % (label or when(p), chars(t), name, tag))
        for ln in lines[:3]:
            i = ln.lower().index(ql)
            a, b = max(0, i - 22), min(len(ln), i + len(q) + 22)
            print("     %s%s%s" % ("…" if a else "", ln[a:b], "…" if b < len(ln) else ""))
        if len(lines) > 3:
            print("     （这份里还有 %d 处）" % (len(lines) - 3))
        return True

    hits = sum(1 for p in txts if show(p, read(p)))
    print("\n  录音稿：%d/%d 份命中 · %s" % (hits, len(txts), d))

    for e in extra:
        mine = [p for r, p in docs if r == e]
        dh = 0
        for p in mine:
            t = read(p)
            # 先在整篇上做一次快速判断，命中了才逐行切。三千多万字的语料里
            # 无差别按行 lower() 要慢一个数量级，而绝大多数文件是不命中的。
            if ql not in t.lower() and ql not in os.path.basename(p).lower():
                continue
            # 「文档」显示宽度是 4，而日期「08-14」是 5——补一个空格才和录音稿那列对齐
            if show(p, t, label="文档 "):
                dh += 1
        print("\n  文档：%d/%d 份命中 · %s" % (dh, len(mine), e))
        hits += dh

    if not hits:
        print("\n  都没有「%s」。" % q)

for p in gone:
    print("\n  ⚠️ 登记过的文本目录现在不可达（硬盘没插？）：%s" % p)
    print("     这次搜索**没有**覆盖它。目录名单在 %s" % CONF)

# 没转写的备忘录也报一下，否则「找不到」会被误解成「丢了」
vm = os.environ.get("VM_DIR", "")
if vm and os.path.isdir(vm):
    try:
        n = len([f for f in os.listdir(vm) if f.endswith((".m4a", ".qta", ".wav"))])
    except OSError:
        n = -1
    if n < 0:
        print("\n  （读不了语音备忘录目录，多半是终端缺「完整磁盘访问权限」）")
    elif n:
        print("\n  iPhone 里另有 %d 条语音备忘录**还没转写** —— rex phone 看列表" % n)
PY
}

devices() {
  ensure_ad
  din=$("$AD" default-in); dout=$("$AD" default)
  say "麦克风（--device 用这里的名字）："
  # 不做列对齐：printf 的 %-28s 数的是字节，中文名会把表格排歪。
  "$AD" list-in | while IFS=$'\t' read -r u t n; do
    mark="  "; [ "$n" = "$din" ] && mark="${C_G}→ ${C_0}"
    printf '%s%s  %s\n' "$mark" "$n" "${C_D}($t)${C_0}"
  done
  say ""
  say "输出设备："
  "$AD" list | while IFS=$'\t' read -r u t n; do
    mark="  "; [ "$u" = "$dout" ] && mark="${C_G}→ ${C_0}"
    printf '%s%s  %s\n' "$mark" "$n" "${C_D}($t)${C_0}"
  done
  say ""
  say "${C_D}→ 是现在的默认。rex mic 跟随默认麦克风；rex sys 会按默认输出现建直通设备。${C_0}"
}

# 用头部注释当帮助文本，printf 到第一条分割线为止。这样加了命令改一处就够。
usage() { awk 'NR>1 && /^# ---/ { exit } NR>1 && /^#/ { sub(/^# ?/, ""); print }' "$SELF"; }

# ------------------------------------------------------------------ 入口

need ffmpeg "brew install ffmpeg"
need ffprobe "brew install ffmpeg"
sync_runtime

WAV=""; SPLIT=""; MIC_DEV=""; LANG_OPT="auto"; NOVAD=""; NORENAME=""; TRIM_TO=""; DRY=""; POS=(); WHO=""; GO_INBOX=""
NAMES="${REX_NAMES:-我,对方}"
# rex --device X、rex --wav：选项直接跟在 rex 后面，就是默认命令（开关麦克风录音）带选项。
# 以前这里把 --device 当成了命令名，报「不认识的命令」，手册却一直这么教人写
CMD="${1:-}"
case "$CMD" in -*) CMD="" ;; *) [ $# -gt 0 ] && shift ;; esac

while [ $# -gt 0 ]; do
  case "$1" in
    --wav)    WAV=1 ;;
    --split)  SPLIT=1 ;;
    --device) shift; MIC_DEV="${1:-}" ;;
    --lang)   shift; LANG_OPT="${1:-auto}" ;;
    --no-vad) NOVAD=1 ;;
    --no-rename) NORENAME=1 ;;
    --to)     shift; TRIM_TO="${1:-}" ;;
    --dry-run) DRY=1 ;;
    --names)  shift; NAMES="${1:-}" ;;
    --who)    WHO=auto; case "${2:-}" in ''|*[!0-9]*) ;; *) WHO="$2"; shift ;; esac ;;
    --inbox)  GO_INBOX=1 ;;
    -*)       die "不认识的参数：$1" ;;
    *)        POS+=( "$1" ) ;;
  esac
  shift
done

# 对话稿里两边叫什么。全角逗号也认——中文输入法下顺手打出来的就是它。
NAMES=$(printf '%s' "$NAMES" | sed 's/，/,/g')
case "$NAMES" in
  ?*,?*) NAME_A="${NAMES%%,*}"; NAME_B="${NAMES#*,}" ;;
  *) die "--names 要两个名字、逗号隔开，比如 --names 我,老师（前一个是麦克风那边）" ;;
esac

# 末尾的 exit 必须和 esac 写在同一行。bash 边读边执行：这个 case 跑完，它会回到文件里刚才的位置
# 接着读。跑的过程中 rex.sh 被改过的话（2026-10-12 一次 15 分钟的 rex go 期间改了它），就从旧位置
# 读进新文件的半截——那次是报语法错，运气差会执行到别处的代码。同一行的 exit 在 case 开跑前就已经
# 读进来了，之后不会再碰这个文件。函数都在上面，开跑前就整个解析进了内存，不受影响。
case "$CMD" in
  ""|toggle)
    # 无参数 = 开关。绑快捷键时就绑这个：同一个键按一次开、再按一次停。
    if [ -f "$STATE" ] && alive; then stop; else start mic; fi ;;
  mic)              start mic ;;
  sys|system)       start sys ;;
  both|all)         start both ;;
  stop|s)           stop ;;
  text|t)           text ${POS[@]+"${POS[@]}"} ;;
  check)            check ${POS[@]+"${POS[@]}"} ;;
  phone|iphone)     phone ${POS[@]+"${POS[@]}"} ;;
  in|inbox|drop)    in_cmd ${POS[@]+"${POS[@]}"} ;;
  url|dl|podcast)  url_cmd ${POS[@]+"${POS[@]}"} ;;
  trim|cut)         trim_cmd ${POS[@]+"${POS[@]}"} ;;
  who|speakers)     who_cmd ${POS[@]+"${POS[@]}"} ;;
  go)               go_cmd ${POS[@]+"${POS[@]}"} ;;
  auto)             auto_cmd ${POS[@]+"${POS[@]}"} ;;
  login)            login_cmd ${POS[@]+"${POS[@]}"} ;;
  chat)             chat_cmd ${POS[@]+"${POS[@]}"} ;;
  app)              app_cmd ${POS[@]+"${POS[@]}"} ;;
  status|st)        status ;;
  ls|list)          list ;;
  find|f|search)    find_cmd ${POS[@]+"${POS[@]}"} ;;
  open)             mkdir -p "$REX_DIR"; open "$REX_DIR" ;;
  devices|dev)      devices ;;
  help|-h|--help)   usage ;;
  *) die "不认识的命令：${CMD}（跑 rex help）" ;;
esac; exit $?
