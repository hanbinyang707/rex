# `rex` manual

> rex prints its messages and shows the Recording Desk in English or Chinese, following your macOS language (`REX_LANG` in section 10 overrides it). The output samples in this manual were captured in Chinese mode and are reproduced verbatim; in English mode you will see the English equivalents. Some file and folder names, such as the inbox `~/Recordings/收件箱` and the reports `.校对.md` / `.分析.md`, are the same in both languages.

Records the sound on your computer — what you say yourself, what the computer is playing (podcasts, videos, web pages), or both together. Once it's recorded, a single command turns it into text. **Everything runs locally, with no network access** (except for downloading the whisper model the first time).

The code is in `tools/rex.sh`. When you install it, symlink it to `~/.local/bin/rex` (see the README); after that you can type it from any directory.

---

## 1. Command reference

| Command | What it does |
|---|---|
| `rex` | Records the microphone. **Running it again while it's recording stops it** (so a single hotkey is all you need) |
| `rex sys` | Records system audio: anything playing in podcasts, videos or web pages |
| `rex both` | Microphone + system audio. One file: what you hear is the mix, and inside it each of the two sources is stored on a track of its own |
| `rex both --split` | Same as above, but saved as two files |
| `rex stop` | Stops. Reports duration, size and levels |
| `rex trim` | Cuts the blank stretch at the **end** of the latest recording (the part after you forgot to stop). The original goes to the Trash |
| `rex trim 文件 --to 49:30` (文件 = file) | Manually set the point up to which the recording is kept |
| `rex who [文件] [人数]` (人数 = number of speakers) | **Voiceprint speaker diarization**: for multi-person conversations recorded on a phone, and for `rex both` recordings made before 2026-10-11. Anything already transcribed isn't transcribed again |
| `rex go [文件]` | **End-to-end pipeline**: transcription → speaker diarization → Claude proofreading (reports what it changed) → Claude analysis (you can continue the conversation) |
| `rex auto install` | Watches `~/Recordings/收件箱` (the inbox): **any recording dropped into it automatically goes through `rex go`** |
| `rex auto` / `rex auto open` / `rex auto uninstall` | Show the status / open the inbox in Finder / uninstall |
| `rex login` / `rex login status` | Log in to your Claude account (proofreading and analysis use it) / check whether you're logged in |
| `rex chat [文件]` | **Continue the conversation in that recording's analysis session**; with no file, it uses the most recent recording that has an analysis |
| `rex app` | **Recording Desk**: a local web UI where you can record, drag in files, confirm proofreading changes one by one, and ask follow-up questions (see "The Recording Desk" below) |
| `rex app stop` / `rex app status` / `rex app restart` | Shut it down / check whether it's running / restart it |
| `rex text` | Transcribes the latest recording into text. A `rex both` recording produces a **dialogue transcript**: who spoke, when, and what they said |
| `rex text 某文件` (某文件 = a given file) | Transcribes the given audio file (any format ffmpeg recognizes) |
| `rex link` | **Record from your phone**: prints a QR code; open it in the phone's browser and record, and the audio streams back and goes through `rex go` (see section 6) |
| `rex link stop` / `rex link status` / `rex link new-token` | Shut it down / show status and address / make a new token (old QR codes stop working) |
| `rex export [文件] [docx\|srt]` | Export a transcript as Word, or get its subtitle file; with no file, the latest one (see "Export" in section 5) |
| `rex phone` | Lists iPhone Voice Memos (synced over via iCloud) |
| `rex phone 1` | Takes item 1, copies it into `~/Recordings/` and transcribes it |
| `rex in` | Lists transcribable audio and video files in `~/Downloads` / `~/Desktop` (where AirDrop puts files) |
| `rex in 1` / `rex in all` | Transcribes one of them / all of them. **Only copies; never touches the originals** |
| `rex url 链接` (链接 = link) | Downloads a podcast episode's audio from Xiaoyuzhou (a podcast app) or similar sources and transcribes it |
| `rex check` | Records 3 seconds from the microphone and throws it away, only to see whether a signal is really coming in (the first time, a microphone permission prompt appears; click Allow) |
| `rex check sys` | Plays a test tone and records it through the system audio tap; if it comes through, makes the tap the default for recording computer audio (the first time, a "System Audio Recording Only" permission prompt appears; click Allow; see "Recording computer audio while wearing AirPods" below) |
| `rex status` | Is it recording? For how long? Is ffmpeg still running? |
| `rex ls` | The ten most recent recordings, with duration and size |
| `rex find 词` (词 = search term) | Searches the transcripts **and registered documents**; with no search term, lists all transcripts |
| `rex open` | Opens the recordings folder in Finder |
| `rex devices` | Which microphones and output devices there are, and which ones are currently the defaults |
| `rex help` | Help |
| `rex mic` | Explicitly records only the microphone (plain `rex` with no arguments is its on/off toggle; you can also put options directly after it: `rex --device "AirPods Pro"`, `rex --wav`) |
| Aliases | `rex s`=stop, `rex t`=text, `rex st`=status, `rex f`=find, `rex dev`=devices, `rex all`=both, `rex system`=sys, `rex iphone`=phone, `rex drop`=in, `rex dl`=url, `rex cut`=trim, `rex speakers`=who, `rex mobile`=link, `rex x`=export |

Options:

| Option | Used with | Description |
|---|---|---|
| `--split` | `both` | Saves two files (the default single file already has separate tracks, so you usually don't need this) |
| `--wav` | Recording (`rex` / `mic` / `sys` / `both`) | Records 24-bit WAV instead of m4a. Use it when the audio is going to be analyzed |
| `--device "名字"` (名字 = name) | Recording (`rex` / `mic` / `both`) | Picks the microphone; copy the name from `rex devices` |
| `--lang zh\|en\|auto` | `text` | Transcription language; default `auto` (detects the language automatically and splits into segments; see section 5) |
| `--no-vad` | `text` | Turns off voice activity detection (on by default) |
| `--no-rename` | `text` / `phone` / `in` / `url` / `go` | Doesn't rename the file by keywords after transcription; keeps the timestamp name |
| `--names 我,老师` (Me, Teacher) | `text` | What to call the two sides in the dialogue transcript; the first is the microphone side. Default "我,对方" (Me, Other side) |
| `--who [人数]` | `text` / `phone` / `in` / `url` (`go` includes it by default) | After transcription, also runs voiceprint speaker diarization (same as `rex who`) |
| `--to 49:30` | `trim` | Keeps only up to this time (also accepts `1:02:03` and plain seconds) |
| `--dry-run` | `trim` | Only reports how much would be cut; doesn't touch the file |

---

## 2. Three modes, and when to use each

### `rex` — only you

Say whatever comes to mind, then turn it into text afterwards to use as raw material. This is the most common use.

It uses **the input device you've selected in the system**: if you're wearing headphones and the system input is the headphones, it uses the headphone microphone, with no settings to change.

> ⚠️ When you use a Bluetooth headset microphone, it prints a warning: the headphones drop into hands-free mode (sample rate 48k → 24k), and playback quality turns muddy immediately. That doesn't matter if you're only recording yourself talking; if you're also listening to something at the same time, add `--device "MacBook Air Microphone"` to switch to the built-in microphone.

### `rex sys` — only what the computer is playing

Podcasts, videos, online classes, audio on web pages: anything that comes out of the speakers.

**You can still hear it in your headphones as usual**; see section 8 below.

### `rex both` — both together

Phone calls, online meetings, online classes, commenting while you watch. It records **one file**: what you hear in a player is the mix, and the file also stores the two original tracks separately:

| Track | What's on it | What it's for |
|---|---|---|
| 0 | Mix | Players play only this one by default (the other two are disabled, so QuickTime doesn't play them layered on top of each other) |
| 1 | Microphone only (you) | Transcription |
| 2 | System audio only (the other side / what the computer is playing) | Transcription |

**This distinction is worth a lot when transcribing**: `rex text` transcribes each track separately and merges them into one dialogue transcript, so who said what is clear at a glance (section 5, "Who is speaking").

`--split` still works and saves two files:

```
2026-08-16_143052_both-mic.m4a    ← only your voice
2026-08-16_143052_both-sys.m4a    ← only the computer's audio
```

The default file already has separate tracks, so you usually don't need it. When `rex text` finds such a pair, it also merges them into one dialogue transcript.

> **`both` recordings made before 2026-10-11 really are mixed down to one track and can't be separated.** At the time, the docs recommended `--split` for meetings: the mix was a plain sum (`normalize=0`), so when the two sides' levels differed a lot, your own voice got buried. In a meeting on 2026-08-19, the measured microphone peak was −45.3 dB and system audio −13.0 dB, **a 32 dB difference (about 40 times)**, and 16 minutes produced only 24 lines of transcript; trying to rescue it afterwards with `loudnorm` / `dynaudnorm` didn't work either. **Once it's mixed, no fix applied afterwards can bring it back.** Transcription no longer uses the mix track, so the problem is gone along with it.

### Meetings (Tencent Meeting / Zoom): the meeting app grabs the microphone

**The other side's voice generally gets recorded** (via system output → BlackHole, or via the system audio tap; on the BlackHole path, AirPods automatic switching can hijack the output, see section 9, "Recording computer audio while wearing AirPods"). **Your own voice isn't guaranteed.**

A true story from 2026-08-16: `rex both --split` recorded a 128-minute Tencent Meeting call. The microphone track peaked at −3.9 dB in minute 1 (normal speech), **but from minute 2 on it was −91.0 dB**, and the 126 minutes after that were all digital silence. Of the 128-minute meeting, all that was left of your own side was 173 characters at the very start: "hello, hello, can you hear me?"

Why: meeting apps use macOS's Voice-Processing I/O for echo cancellation, which pulls the input device into a special mode and **kicks out any other readers**.

> This document used to say "two processes can open the same microphone at the same time, so there's no problem". That conclusion came from a real test of two ffmpeg processes reading the same device — the test really was done, but **it didn't test the real-world scenario**. Meeting apps take a different path, and in practice they do kick other readers out. Corrected.

**The fix is to have the two sides use different microphones.** Run `rex devices` to see which ones you have, then:

- Set the meeting app's microphone to your **headphones** (or the iPhone microphone)
- `rex both --device "MacBook Air Microphone"`

As long as the two sides don't touch the same device, there's no conflict. The reverse works too — the key is to keep them apart. The per-track check in `rex stop` reports how much of the microphone track is digital silence, so if the microphone was grabbed, you'll see it right away.

**There's also a failure in the opposite direction: put on Bluetooth headphones mid-recording, and the system output gets rerouted around BlackHole**, so the other side's track is digital silence from that moment on. A call on 2026-09-26 lost almost everything the other side said this way; at the time, the recording was stopped and restarted with the headphones on, and a few seconds later it broke again. Now, on the BlackHole path, the output is checked every two seconds and reconnected within two seconds if it gets switched away; with the system audio tap instead (`rex check sys`), it isn't affected at all. The watchdog, `rex stop` and `rex text` also all report on the other side's track, so nothing gets lost silently. See section 9.

Incidentally: when you use Bluetooth headphones in a meeting, they've already dropped into HFP hands-free mode anyway (the meeting app is using their microphone), so the "don't use a Bluetooth microphone, or it will muddy playback" concern doesn't apply to calls.

### Watchdog: know the moment something breaks

The real cost of that incident wasn't "the recording failed"; it was **finding out it had failed only after two hours of recording**. So now, during recording, it checks itself every 3 minutes, looking at each track's level file, which the capture program writes every half second: no new frames for ten seconds = capture has stopped; frame count not going up = stuck; microphone at digital zero for more than 3 seconds = no signal; when system audio goes through BlackHole, the output route is checked as well. If something breaks, it pops up a notification. On the BlackHole path there's also a separate route monitor that runs every two seconds, and if the output gets switched away it's reconnected within two seconds. If the recording stops on its own (it hit the duration limit, a device disconnected, the disk filled up), the watchdog wraps things up for you — switches the output back, finishes writing the file, posts a notification with sound — so the passthrough device doesn't keep holding the output. `rex stop` lays out these records:

```
录制期间的路由和看门狗记录：
  23:13:49  输出被切到「AirPods Pro」，已经重新接上，系统声音接着录
  23:40:02  麦克风断了（峰值 -91.0 dB），从现在起录的是数字静音
```

It reports only once, at the moment something goes from "working" to "broken", rather than flooding the screen every three minutes. `REX_WATCH=秒数` (秒数 = seconds) changes the interval; `REX_WATCH=0` turns it off.

> ⚠️ **The system audio track used to raise false alarms; this was fixed on 2026-08-19.** Originally both tracks shared the criterion "peak < −70 dB means it's broken". That holds for the microphone — a real microphone has a noise floor however quiet things get, measured at around −68 dB in a quiet room. **It doesn't hold for BlackHole**: on a virtual device, no signal means true digital zero; measured with nothing playing, it's `max_volume: -91.0 dB`, exactly the same as "broken".
>
> As a result, in a 16-minute meeting, it reported "broken" every time the other side paused for breath, and in between it also reported "recovered again" — while the link never dropped for even a second (measuring the file every 30 seconds afterwards showed peaks of −2.6 to −19.7 dB throughout, with no digital silence at all). **"Recovered again" is itself the sign of a false alarm: a broken audio route doesn't fix itself.**
>
> Now the system audio track checks the **route** instead: whether the current output device still includes BlackHole. Headphones disconnecting, another app grabbing the output: those are the things that really break, and checking for them is accurate, with no false positives. The alert text was also changed to something you can act on directly: `当前输出「AirPods Pro」里没有 BlackHole` (the current output "AirPods Pro" doesn't include BlackHole).

**Notifications deliberately have no sound** — if you're recording system audio, the alert sound would end up in the recording.

You can also check for yourself during a meeting:

```bash
rex status
```

```
● 在录 · both · 已 42 分 10 秒

  ✓ 麦克风（你）：峰值 -48.8 dB
  ✓ 系统声音（对方）：峰值 -14.1 dB
```

A microphone at digital zero for more than 3 seconds is marked `✗ 没信号` (no signal); a track with no new data for 10 seconds is marked `✗ 采集停了` (capture stopped); when nothing is playing on the system audio track at the moment, it shows `○ 此刻没声音` (no sound right now). The levels are live values that the capture program writes every half second (`~/Recordings/.cap/*.level`; the level meter in the Recording Desk's top bar reads them too), not readings from the file being written: an m4a that's still recording has its index written at the end, so it can't be opened at all until it's finalized. File size doesn't work either: ffmpeg buffers in large chunks, and in a test, 13 seconds were recorded with sound on both tracks, yet the file, checked midway, stayed at 4K the whole time.

If you're recording a meeting that involves other people, it's prudent to let them know before you start.

### Forgot to stop: `rex trim`

```bash
rex trim            # the most recent recording
rex trim --dry-run  # first see how much would be cut
```

```
2026-09-22_123128_sys.m4a  （1:43:46）
  末尾空白：49:52 → 1:43:46，共 53:54（峰值 -91.0 dB）
  切到 49:55（多留 3 秒，免得切掉最后一个字的尾音）
  ✓ 1:43:46 → 49:55 · 30.3M → 28.5M
  原件已放进废纸篓（访达里右键「放回原处」可以恢复）
```

**It cuts only the end, never the middle.** The same recording also has 4 pauses of 20–67 seconds (breaks in the podcast); "delete all the blank parts" would cut those too, shifting everything after them earlier on the timeline, and the already-transcribed `.srt` would no longer line up with the audio. Cutting only the end keeps every second before it exactly as it was, and not a single timestamp moves. Blank space at the beginning is also **deliberately left alone**, for the same reason.

A few details:

- **The criterion depends on the source**: `sys` goes through BlackHole, where silence is true digital zero at −91 dB, so the threshold is −70 dB; a microphone has a noise floor (−55 to −70 dB in a quiet room), so the threshold is −50 dB. Sharing one threshold is exactly the trap the watchdog fell into (see the "Watchdog" subsection above)
- It only counts silence that **lasts at least 30 seconds and continues all the way to the end of the file**. Any speech interrupts it, so a pause in the middle, however long, is never mistaken for trailing blank space
- **No re-encoding**: it only truncates the container (`-c copy`), so there's zero quality loss and it finishes in seconds. In a test, the 49:50 that was kept, once decoded, was byte-for-byte identical to the original
- If the recording has already been transcribed, the `.srt` entries after the cut point are removed as well, and the `.txt` is rebuilt from what remains
- A pair recorded with `--split` is **cut together**
- Blank doesn't necessarily mean silent — if the computer was playing something else, or the fan was loud, it won't touch it. In that case, use `--to 49:30` to set the point manually. It prints the peak of the part to be dropped, so you can tell at a glance if it's real content

> **The original goes to the Trash; it isn't deleted.** This toolchain has deleted the author's recordings on this machine before (`rm` bypasses the Trash), so nothing is ever deleted here: only after the new file's duration has been verified is the original sent away with macOS's built-in `trash`, and you can restore it with "Put Back" in Finder.

Incidentally: 54 minutes of digital silence takes up only 1.8 MB (AAC compresses silence extremely hard), so what trimming it saves isn't space but **duration** — transcription, language detection and the numbers shown in `rex ls` all come out right.

**It reminds you by itself the next time you stop.** `rex stop` now looks at the last 5 minutes, and if there was no sound the whole time, it says:

```
    ⚠ 最后 5 分钟一直没声音（峰值 -91.0 dB），多半是忘了停。
      rex trim 切掉末尾空白（中间的停顿不动，原件进废纸篓）
```

---

## 3. Where the files are

Everything goes into `~/Recordings/`. Files are named `日期_时间_模式` (date_time_mode):

```
2026-08-16_143052_mic.m4a
2026-08-16_143052_sys.m4a
2026-08-16_143052_both.m4a
2026-08-16_143052_both-mic.m4a  +  ..._both-sys.m4a     (--split)
```

Transcription results go right next to the recording, as a `.txt` and an `.srt` (with timestamps) of the same name. `rex both` recordings get a dialogue transcript, with each turn labeled with who is speaking.

Size (per hour):

| | Format | Roughly per hour |
|---|---|---|
| `rex` | AAC mono 96 kbps | 43 MB |
| `rex sys` | AAC stereo 160 kbps | 72 MB |
| `rex both` | Mix at 160 kbps + two separate tracks at 64 kbps each | 130 MB |
| `--wav` (stereo) | 24-bit / 48 kHz PCM | **1.0 GB** |

**There's a 6-hour fuse**: recording stops by itself when the time is up, so forgetting to stop can't fill the disk. To record longer:

```bash
REX_MAX=36000 rex sys
```

---

## 4. Finding old transcripts

File names change after automatic naming, so **going by the old path you remember is bound to come up empty**. Don't memorize paths; search instead:

```bash
rex find docker
```

```
  08-14   2831 字  2026-08-14_1609_phone_Projection-GUI-Session.txt
     走Docker了
     不用那个Docker的形式
     那个是用Docker做的

  录音稿：1/6 份命中 · ~/Recordings
```

It searches file names and body text together. Without a search term, it lists all transcripts:

```bash
rex find
```

Three points:

- The dates in the list come from the **file name**, not the file modification time. Re-transcribe a file once and its mtime becomes today, so a recording from 08-14 would show up as 08-16—worse than showing no date at all
- At the end, it tells you how many voice memos on the iPhone are still **not transcribed**. "Can't find it" often doesn't mean it's lost; that recording simply was never transcribed
- It searches more than just recording transcripts; see below

### It searches documents too

Besides `~/Recordings`, `rex find` also searches the directories registered in `~/.config/rex/text-dirs`. For example, the author has registered a collection of plain text extracted from documents (1,099 files, 31.9 million characters):

```bash
rex find 巴赫金
```

```
  录音稿：0/6 份命中 · ~/Recordings

  文档   309440 字  二十世纪西方文学理论.txt
     巴赫金 ( MikhailBakhtin)。 他 …
     …式主义的最中肯的批评。这一批评的大部分也出自巴赫金之手。巴赫
     （这份里还有 13 处）

  文档   371522 字  巴赫金全集 第3卷.txt

  文档：2/1099 份命中 · /Volumes/Untitled/文档文本
```

Searching all 30-plus million characters takes about 1.5 seconds. **Without a search term, documents are not listed one by one**—that would flood the screen with over a thousand lines, and they have no timeline to speak of—so it only reports a count; for the list, see `_索引.tsv` (the index) in that directory.

To add other directories (a paper library, exported notes), write their paths into `~/.config/rex/text-dirs`, one per line; delete a line and that directory is no longer searched.

> ⚠️ **If the drive isn't plugged in, it says so.** A directory that is registered but currently unreachable gets a one-line warning: "这次搜索**没有**覆盖它" (this search did **not** cover it). If a directory were silently skipped, the result would be "not found" when in fact it never looked at all—you have to be able to tell these two things apart.

All transcripts are in `~/Recordings/`; `rex open` opens that folder directly in Finder.

---

## 5. Transcription

```bash
rex text
```

With no arguments, it transcribes the most recent recording (a `rex both` recording produces a dialogue transcript, and a `--split` pair is combined into one). You can also give it a file directly; it doesn't have to be one you recorded:

```bash
rex text ~/Downloads/某期播客.mp3
```

It uses whisper.cpp with the quantized `large-v3-turbo` model, running on Metal (GPU). **Measured at about 8x real time**: 5 minutes of audio takes 37.9 seconds, and a one-hour podcast takes seven or eight minutes.

The first run automatically downloads two models into `~/.cache/whisper/`:

- `ggml-large-v3-turbo-q5_0.bin` (547 MB): speech recognition
- `ggml-silero-v5.1.2.bin` (864 KB): voice activity detection

### Who is speaking: dialogue transcripts

For a file recorded with `rex both`, `rex text` produces this:

```
[00:01] 我：老师好，能听见吗？

[00:04] 对方：能听见？你那边好了吗？好，我们开始吧。

[00:09] 我：好的，今天想聊一下下学期选课的事，我最近一直在纠结统计那门。
```

**This isn't guesswork; it comes from the separate tracks.** The microphone track contains only you, and the system audio track contains only what the computer plays (the other party on a call, an online class); they are separated at the moment of recording. Each track is transcribed on its own and the results are merged by time, so the labels are correct.

You can change the names; the first one is the microphone side:

```bash
rex text --names 我,老师
REX_NAMES=我,老师 rex text        # or make it the default
```

Each entry in the `.srt` is also prefixed with the name. The keywords used for naming skip these names, so not every file ends up named "老师" (Teacher).

**Three cases this approach can't separate**, which are left to `rex who` (voiceprints) below:

- Several people on the same track: in an online meeting, the three people on the other side are all on the system audio track, and all of them are labeled "对方" (Other side)
- A multi-person conversation recorded with one microphone: phone recordings, in-person meetings
- `both` recordings made before 2026-10-11: back then, they really were mixed into one track

Lines that may be printed during transcription:

| Message | Meaning |
|---|---|
| `拆开 N 处` (split at N places) | whisper merged two sentences that had a sentence from the other side between them into one segment; they have been split apart based on the audio (see below) |
| `去掉 N 段回声` (removed N echo segments) | With audio playing through speakers, the other side's voice leaked into the microphone and was transcribed a second time as "我" (Me); those segments were discarded. **With headphones this should be 0** |
| `⚠ 对方那一轨 N% 是数字静音` (the other side's track is N% digital silence) | Either the other side never spoke, or system audio cut out partway through (most likely because Bluetooth headphones were put on mid-recording) |
| `⚠ 我那一轨 N% 是数字静音` (my track is N% digital silence) | A real microphone doesn't do this: the laptop lid was closed, or a meeting app grabbed the microphone |

**What "拆开" (split) means.** With voice activity detection on, whisper first cuts out silence and then recognizes what is left. Looking at your track alone, the few seconds when the other side is speaking are silence and get cut out, so whisper thinks you were speaking continuously and merges two of your sentences, separated by a whole sentence from the other side, into one segment—and once everything is lined up by time, the order is scrambled. Before merging, segments are repositioned using each track's own volume and split where the other side is speaking. The split point is estimated in proportion to duration, so occasionally a character or two lands in the adjacent turn.

**Why echo removal is so cautious.** Judging by text alone, two people saying "对对对" (right, right, right) at the same time would be taken as echo; judging by volume alone, something you mutter quietly would be thrown away. So a segment counts as echo only if the text is similar, the volume is low, **and it truly overlaps in time**. That last condition came out of testing: the other side asked "是不是担心跟不上" (are you worried about not keeping up?), and you answered "对，是担心跟不上" (yes, I'm worried about not keeping up)—nearly identical text, and the first version threw this sentence away as echo. A restatement comes after the other side has finished speaking; an echo happens at the same time as the original.

### Several people on one track: `rex who` (voiceprints)

```bash
rex who                      # the most recent one
rex who 某录音.m4a           # a specific file; one already transcribed isn't re-transcribed; a 46-minute recording takes about a minute and a half
rex who 某录音.m4a 3         # you know there are 3 people
rex text --who 某录音.m4a    # transcribe and diarize in one go
rex phone 1 --who            # diarize a phone recording as soon as it is fetched
```

The output looks like this (a two-person chat on 2026-10-11 lasting 2 hours 30 minutes):

```
[10:18] 说话人2：对我刚想问的是什么方向的research呢，怎么，那些想做什么

[10:22] 说话人1：我想做后训练方面的research，比如说，怎么让它……

[11:35] 说话人2：你会感兴趣的也是，AI Infra或者是做模型的这种，底层研发的公司吗
```

**This is a guess, not a definite label like the one from separate tracks.** A voiceprint is computed for each short segment, and the segments are grouped into clusters by whether they "sound alike". It uses sherpa-onnx (open source, fully local, no network access); on first use it automatically downloads about 50 MB, which takes up 93 MB after extraction, in `~/.cache/sherpa-onnx/`, outside the repository.

**How it counts the speakers: split finely first, then merge.** It first deliberately splits the recording into dozens, even a hundred or more, small clusters (better to cut one person into several clusters than to let two people into the same one), takes about ten segments from each cluster to compute voiceprints and an **average voiceprint**, and then merges clusters whose average voiceprints are similar enough, until even the two most similar clusters are no longer similar enough. Leftover clusters that are too small (laughter, two people talking at once, noise) are merged into whichever speaker's voice they most resemble.

Why average: over two or three hours, the same person's voice changes—they get tired or excited, or move closer to and farther from the phone—so if you compare just two short segments, the same person at two different points can be less alike than two different people. Averaged over dozens of segments, these momentary changes cancel out: two clusters split off from the same person have an average-voiceprint similarity of 0.8–0.98, while two different people are at 0.15–0.7.

> The first version didn't work this way; it counted people directly from the distances between individual segments: a two-person chat lasting 2 hours 30 minutes was split into **12 people**, and the 04:32 two-person conversation was split into 4 people (at the time I even said "at least 3 people" based on the content, which was also wrong). After switching to the current method, all four recordings on hand (two conversations, one long chat, and a synthetic phone call made for testing) were separated correctly, each into 2 people.

**How accurate it is**: measured on the 2026-10-10 conversation—in that one, the two sides had different spectra (everything above 7.5 kHz was cut off on the far end of the call), so it could serve as a reference answer. Compared sentence by sentence, the results are **97% in agreement**; reading through the remaining 3%, most turned out to be errors in the reference answer (the other side's words had been classified as this machine's side by the spectrum rule), not voiceprint errors.

**How long it takes** (measured): about 40 seconds for a 15-minute recording, about a minute and a half for 46 minutes, and about 5 minutes for two and a half hours—transcribing the same recording takes twenty minutes, so diarization is not the bottleneck.

**The speaker count can still be wrong**, especially when two people have very similar voices (the two synthetic voices used for testing had an average-voiceprint similarity as high as 0.62). When you know the number of people, tell it: `rex who 文件 2` (文件 is the file)—it keeps merging until exactly 2 people remain, without re-transcribing, so you can change it as many times as you like.

**The names are "说话人1", "说话人2", "说话人3"… (Speaker 1, 2, 3…)**, numbered in order of appearance. Working out who is who is up to you: the voiceprints only know "these segments are the same person", not who that person is.

**`rex both` recordings from before 10-11 (mixed into one track) get one extra step**: after diarization, the spectrum is used to match "the local microphone side" to "我" (Me) and "the far end of the call" to "对方" (Other side). When the same side has been split into two clusters, both clusters are matched to "我", which solves the speaker-count problem along the way. If the match fails (for example, when the call audio itself is full-band), the speaker numbers are kept, and it says so.

Recordings in which only one person speaks (lectures, podcasts, monologues) are not labeled "说话人1"; the transcript is left as is.

### The Recording Desk: `rex app` (no commands to type)

```bash
rex app
```

It opens a web page that runs only on your machine (`http://127.0.0.1:8790`). In Safari, choose "File → Add to Dock"; from then on, opening it from the Dock works just like an app.

- **Recording**: three buttons at the top—**"我 + 对方"** (Me + Other side; for calls and meetings: your microphone + computer audio, each side saved on its own track), "只录电脑声音" (Computer audio only; for online classes and videos, **does not record your microphone**), and "只录我" (Only me; for face-to-face conversations). For phone calls and meetings, always use "我 + 对方". While recording, the top bar shows the duration, a live level bar for each track, and "停止" (Stop): if your microphone has no signal, or capture on any track stops, it turns red right away; if the computer isn't playing any sound at the moment, it shows a gray "没声音" (No sound). Starting a recording takes a few seconds, and clicking repeatedly during that time won't start a second one
- **Adding files**: dragging an audio file into the window is the same as putting it in the inbox: automatic transcription → diarization → proofreading → analysis
- **Recordings on your phone**: import Voice Memos with `rex phone` in a terminal (reading them needs Full Disk Access, which belongs to the terminal app; the background Recording Desk doesn't have it). Once imported, they show up here and are processed as usual
- **Viewing a recording**: the transcript is color-coded by speaker, and clicking a timestamp plays from that point; automatically corrected words have a green background (hover to see the original), and those awaiting confirmation have a yellow background
- **Confirming proofreading item by item**: on the "校对" (Proofreading) page, every item Claude is uncertain about offers "采纳 / 不采纳" (Accept / Reject); on the keyboard, `Y` accepts, `N` rejects, `J` / `K` move to the next / previous item, and Space plays that sentence; changes can be reverted with "撤销" (Undo). The edits are made to the transcript file itself, and the report updates to match. To take all the remaining suggestions at once, click "全部采纳" (Accept all) next to the "To confirm" heading; anything whose original text is gone or appears more than once in its line is skipped and left for you
- **Analysis**: the rendered analysis report, with clickable timestamps
- **Ask follow-up questions**: put questions to that analysis session right on the page (it uses your Claude login and is not affected by settings in your terminal that point to another provider's API)
- **Search**: searches all transcripts, with results pinpointed to the exact sentence; click a timestamp to jump straight there
- **Filling in missing steps**: for recordings that haven't been transcribed or proofread, or that have a few segments where proofreading didn't succeed, there are buttons in the top-right corner to fill in what is missing
- **Deleting a recording**: double-click it in the list on the left (or click "删除" (Delete) at the top right of the detail view). After you confirm, the whole recording (audio, transcript, proofreading, analysis) moves to the Trash, where Finder's "Put Back" restores it. A recording that is being recorded or processed can't be deleted. Use this to clear out empty recordings

A few notes:

- **It stays running in the background**: run `rex app` once and macOS's launchd takes over. It starts at login and restarts if it crashes, and closing the terminal or quitting Claude doesn't affect it. It runs the copy of the scripts outside Documents (`~/.local/share/rex-runtime`), so it can't lose access to its own files when the program that started it quits (before 2026-10-16 it could; see section 9). The recording permissions (microphone, system audio) belong to the recording program "rex 录音采集" (rex audio capture) itself, which also lives outside Documents (`~/.local/share/rex/bin`); `rex` in the terminal and the Recording Desk use the same one, so one grant covers both
- Turn it off completely with `rex app stop` (it no longer starts at login; run `rex app` to bring it back), check its status with `rex app status`; the log is at `~/Library/Logs/rex-app.log`. After changing the code in the repository, `rex app restart` makes it use the new code
- It only listens on this machine, so other computers can't connect; other web pages in your browser can't control it either (it requires a token and checks the request origin)

### Export to Word or subtitles: `rex export`

```bash
rex export                 # latest transcript → Word (written next to the recording and selected in Finder)
rex export <file> docx     # a specific one
rex export <file> srt      # subtitles: the <name>.srt written and proofread during transcription; no extra copy is made
```

The Word file has a title (the keyword from the file name), the recording time, then one line per turn: `[time] speaker: words`.
The Recording Desk's detail view and each transcript on the phone page have "Word" and "Subtitles" buttons that download directly.

### End to end: `rex go` and the inbox

**Drop a recording into `~/Recordings/收件箱` (the inbox) and the rest is automatic.** (The first time, install it: `rex auto install`. To open the folder in Finder: `rex auto open`; while you're at it, drag the folder into the Finder sidebar so that from then on you can drag files straight into it.)

**What goes into the inbox**: audio files that came from elsewhere (WeChat, downloads, files people sent you, exports from your phone). Drag in **the file itself** (its icon in Finder). Recordings you made with `rex` on this Mac are already in `~/Recordings` and don't need to go through the inbox; just run `rex go`. If what you drag in isn't audio or video (for example, you dragged in a piece of text instead, which Finder saves as a `.textClipping`), it is moved to `收件箱/转不了` (couldn't convert), and a notification tells you what happened.

Each file you drop in goes through these steps in order:

1. **Transcription** (whisper, local)
2. **Speaker diarization** (`rex both`'s separate tracks / voiceprints, local; skipped when only one person is speaking)
3. **Claude proofreading**: fixes speech recognition errors only, meaning wrong homophones and misheard terms and names. What Claude returns is a **list of changes**, and the script finds each one verbatim in the original text and then replaces it; anything Claude is uncertain about is **left unchanged** for you to confirm.
4. **Claude analysis**: summary, topics, verbatim quotes, points worth following up on, decisions and to-dos

All results go in `~/Recordings`, named after the recording:

| File | What it is |
|---|---|
| `….txt` / `….srt` | The proofread transcript (dialogue transcripts include speaker labels) |
| `….whisper.srt` | The original whisper transcript from before proofreading, for comparison |
| `….校对.json` | The raw record of the proofreading results (the `.校对.md` proofreading report is generated from it). If some segments didn't get proofread, it records their line numbers, and running `rex go` again fills in just those segments |
| `….校对.md` | The proofreading report: **what was changed** (time, original → changed to, reason), plus "拿不准、没改的，请你确认" (uncertain and not changed: please confirm) |
| `….分析.md` | The analysis report. At the top it shows `rex chat "…"`: **run that to return to the session and ask follow-up questions** |
| `….对话.json` | The conversation log: the questions and answers from "接着问" (Ask follow-up questions) in the Recording Desk, plus the session ID it uses (after the analysis is redone, it automatically switches to the new report's session) |

As soon as a file arrives you get a notification, "开始处理（N 分钟）" (processing started, N minutes), and another one when it's done: "校对改了 N 处，M 处待你确认" (proofreading made N changes, M await your confirmation). After processing, the original is moved to `收件箱/已处理` (processed), not deleted. If the transcript is absurdly short (a recording tens of minutes long that yields only a few characters), it isn't handed to Claude; instead you get the notification "转写可能失败" (transcription may have failed). That means something went wrong in transcription, and proofreading can't rescue it. Files that no audio can be extracted from (not a recording, or a damaged file) are moved to `收件箱/转不了`, also with a notification.

You don't have to use the folder; you can also run it directly:

```bash
rex go 某录音.m4a
```

With no file given, it uses the most recent recording. It doesn't redo transcription, diarization, proofreading or analysis that has already been done; it only fills in the missing steps, so dropping the same recording in a second time won't overwrite the first proofreading report. To redo a step, delete that step's output (for example `….分析.md`) and run `rex go` again.

**One thing to do the first time: log in to Claude.** Proofreading and analysis call the local `claude` command-line tool, which needs its own one-time login with your Claude account (it can't use the desktop app's login):

```bash
rex login
```

Just confirm in the browser; you only need to do this once. **If your `~/.zshrc` points `claude` in the terminal at another provider's API** (the `ANTHROPIC_BASE_URL` lines), don't use "run claude, then /login": with those settings in place you can't log in to a Claude account, so `rex login` clears them first. The pipeline clears them the same way when it calls Claude, so when you type `claude` day to day it still goes to that other provider, while the pipeline goes to Claude, and neither affects the other. To check your login status: `rex login status`. To continue the conversation, use `rex chat`; **don't run `claude --resume` directly**: that would return to the session with the other provider's settings in effect, and your transcript would be sent there.

**Usage**: proofreading and analysis draw on your Max subscription's allowance, with no separate per-token charge. How much each run used is written at the top of the report (number of calls, number of tokens, and the equivalent API price; that price only converts the usage into money for easy comparison). Measured on 2026-10-12 with the same 20-line transcript:

| How it was called | Time | Equivalent API price | Proofreading result |
|---|---|---|---|
| First version (launched from the author's repository directory, picking up an 87 KB CLAUDE.md and the default system prompt) | 128 s | $1.28 | 9 items |
| Empty directory + custom system prompt, Fable at default effort | 81 s | $0.31 | 11 items, most of them uncertain |
| Same as above, Sonnet | 110 s | $0.14 | Guessed "真本" meant "真北" and "背头" meant "版图" |
| **Same as above, Fable at low effort (the current setup)** | **24 s** | **$0.09** | "真本→真格", "背头→被投": confident and correct |

If you aren't logged in, your balance is insufficient, or you've hit the usage limit, transcription and diarization still run, but proofreading and analysis are skipped and the notification says why. Afterwards, run `rex go` on that recording once more (the terminal prints the full command) to fill in those two steps.

**Changing what the analysis looks for**: the default analysis prompt is in `tools/analyze.py`. To replace it (for example, if you want something different out of interview recordings), write a `~/.config/rex/analysis-prompt.md`; if that file exists, it is used.

**Privacy**: transcription and diarization are entirely local; **proofreading and analysis send the whole transcript to Claude** (through your own Claude login, the same as pasting it into Claude). Only `rex go` and the inbox go through these two steps; `rex text` / `rex who` don't.

**Seeing what it's doing**: `rex auto` shows the status and the last few lines of the log; the full log is at `~/Library/Logs/rex-inbox.log`.

> Why the inbox lives under `~/Recordings` and not in "Downloads" or iCloud Drive: programs that run automatically in the background can't read folders under macOS privacy protection (Downloads, Desktop, Documents, iCloud Drive). This repository is itself in "Documents", so the background job can't even read its scripts. That's why `rex auto install` copies the scripts to `~/.local/share/rex-runtime` for the background job to use, and that copy is kept in sync automatically whenever you run `rex` in the terminal.

### Language changes mid-recording: automatic segmentation

**whisper identifies the language only once, at the start of the file, and then decodes the entire file as that language.** So feeding it a recording that is "English in the first half, Chinese in the second half" as is goes badly wrong.

A real case from 2026-08-18: a 5 min 39 s meeting recording, with the first 42 seconds in English and the following 4 min 57 s in Chinese (82% of it). At t=0 whisper decided `en` (confidence 0.99), and then:

```
[00:01:20]   It's better than the other bits format.
[00:01:21]   It's better than the other bits format.
…(the same line 167 times in a row, all the way to the end of the recording)
```

**Not a single Chinese character came out, and it didn't report any error.** Automatic naming then dutifully named the file after that sentence: `2026-08-18_1324_phone_It's-better-format`. A silent failure, packaged downstream into a normal-looking result.

Now `rex text` by default **probes the language first, then transcribes segment by segment**:

```
  探测 13 点（网格 31s，二分 2 次）
  语言分段：en 00:00–00:42 · zh 00:42–05:39
  分 2 段各按自己的语言转写

  ── 第 1/2 段 · en · 00:00–00:42 ──
  ── 第 2/2 段 · zh · 00:42–05:39 ──
  2 段合并完成（时间轴已按各段起点校正）
```

Re-transcribing the same recording: Chinese output 0 → **1171 characters**; longest run of "consecutive identical lines" 167 → 4.

Three implementation trade-offs, all settled by measurement:

- **Probing has a cost.** Each probe takes about 1.5 seconds, almost all of it spent loading the 547 MB model rather than on recognition itself. So it first lays down a coarse grid (at most 40 points), and only bisects to find a boundary where two adjacent points differ in language. The grid has both a cap (40 points) and a **minimum spacing** (at least 60 seconds per cell). A cap alone isn't enough: a 21-minute file at 30 seconds per cell lands right at 40 points, which is 27% overhead. Measured: about 20–30% for 5 minutes, about 20% for 21 minutes, about 6% for 130 minutes. **For short files the ratio can't come down**, because the number of probes has a floor (the beginning and the end have to be covered), while transcription time shrinks with the duration.
- **Probe points are recorded at the window's center, not its start.** A 30-second window starting at 31 seconds being judged Chinese means "Chinese is the majority within 31–61 seconds", not "it's Chinese at 31 seconds". Recording by the start point systematically pushes the boundary half a window earlier: in testing, the true boundary was at 42 seconds, recording by start point reported 30 seconds, and 12 seconds of English were put into the Chinese segment.
- **The coarse pass uses 30-second windows; bisection switches to 10-second windows.** When a wide window straddles the boundary, each language takes up half of it, so precision gets stuck at 30 seconds; switching to a 10-second window points straight at 42 seconds, with confidence that is actually higher (en 0.98 / zh 0.91).

**Only Chinese and English are accepted** (an allowlist; to add more, set `REX_LANGS=zh,en,ja`). A detection outside the allowlist is treated as "uncertain" and merged into the neighboring segment, and it prints what was blocked. For what prompted this, see section 9: choppy audio led language detection to classify 5.8 minutes as Icelandic; it was force-decoded as Icelandic, and not a single character came out.

**No language detection where it's too quiet.** Faced with a room's noise floor, whisper will confidently say "this is English" (measured confidence 0.78). In a recording from 2026-09-26, several stretches where almost nobody was speaking were classified as English this way and force-decoded as English, and the few scattered Chinese sentences were translated into English. Now each probe window first measures how much of it actually contains sound; if that's under 20%, no language is assigned and the window follows the segments before and after it, and it prints "其中 N 点太安静" (N of these points are too quiet). When the whole recording is too quiet (for example, the track of an other side who barely makes a sound), it is transcribed in the first language in `REX_LANGS` (Chinese by default).

When probing a monolingual recording finds only one language, that language is **explicitly specified** for transcription instead of letting whisper guess. If you already know the language, you can skip probing altogether:

```bash
rex text --lang zh 某文件.m4a
```

### The repetition trap: `-mc 0`

Those 167 repetitions above weren't only the fault of the wrong language choice. By default whisper feeds the text it has already transcribed back in as context (`--max-context -1`, unlimited), so **once it starts repeating, the repetition itself enters the context, which makes it even more inclined to repeat**: a positive feedback loop. Measured on the same file, again force-decoded as English:

| | Most frequent line repeated |
|---|---|
| `-mc` default (unlimited context) | 54 times |
| `-mc 0` | 4 times |

Now `-mc 0` is always passed. The cost is slightly lower coherence across sentences (it no longer knows what was said earlier), which is a good trade for dictation transcripts: losing a little coherence is acceptable; a whole passage turning into the same sentence is not.

The naming layer has its own independent guard too: the same sentence counts at most twice per transcript, and any further occurrences don't count toward word frequency. **Don't let one sentence repeated hundreds of times decide what the whole transcript is called.**

### Misheard words: two layers

**Layer 1: `tools/whisper-prompt.txt`** — a prompt vocabulary list fed to the model before transcription. In testing, it works:

| | Result |
|---|---|
| Without the vocabulary list | 往文 / 赤心寻天 / 双文 / 新国变 / 哲理变 |
| With the vocabulary list | 网文 ✓ 赤心巡天 ✓ 爽文 ✓ 新国辩 ✓ 哲理辩 ✓ |

**Keep this file short.** The length limit is about 224 tokens (one Chinese character is 1–2 tokens); anything beyond that gets truncated, which makes things worse rather than better: in testing, a longer vocabulary list gave even worse results than a short one. Only include words that **have actually been misheard**.

**Layer 2: `tools/whisper-fix.txt`** — deterministic replacements applied after transcription, one `错的→对的` (wrong→right) per line. The prompt is only a bias and isn't guaranteed to take effect (the same word may come out right in one recording and wrong in another); whatever it can't straighten out goes here.

> ⚠️ Chinese has no word boundaries, so this is an **unconditional string replacement** and can hit text it shouldn't. `往文→网文` would turn "通往文学" ("leading to literature") into "通网文学". Only include misrecognitions that are distinctive enough. Every replacement is printed; if you see a wrong one, delete that line.

Edits to either file take effect immediately; nothing needs to be rebuilt.

**Where these two files live**: `tools/whisper-prompt.txt` and `tools/whisper-fix.txt` in the repository are empty templates. Copy them to `~/.config/rex/` and edit them there: those copies take precedence, stay out of the repository, and survive `git pull`.

### Automatic naming after transcription

After transcription, three keywords are extracted from the transcript and the file is renamed to something recognizable:

```
2026-08-14_1609_phone.m4a                             ← before
2026-08-14_1609_phone_Projection-GUI-Session.m4a      ← after
```

The audio, the `.txt` and the `.srt` are renamed together, and the prefix is still the timestamp, so sorting by time is unaffected.

Keyword extraction lives in `tools/keywords.py` and is **pure word frequency, with no network access**. Sending a private recording transcript to some API just to come up with a filename would trade the "fully local" promise for convenience, which isn't worth it. Three rules:

- Fragments that begin or end with a function word are discarded outright (badly cut ones such as "的问题" and "个东西").
- **Words in `whisper-prompt.txt` get 5× the weight**. That list is your domain vocabulary to begin with, so a match is almost certainly a keyword. In testing, a Chinese transcript yielded "赤心巡天-网文-**文章**" without the vocabulary list and "赤心巡天-网文-**爽文**" with it.
- English words mixed into a Chinese transcript get a higher weight. In technical dictation transcripts, words like `Docker`, `GUI` and `Session` are more distinctive than any two-character Chinese word.

**It extracts "words mentioned repeatedly", not "what this is about".** A transcript that keeps mentioning some word while its real focus is elsewhere will get the wrong name. The name is just an index, not a summary. If you don't want it, use `--no-rename`.

Two edge cases:

- **Transcribing the same file again won't append the keywords a second time**. The test is "is the filename still in the format this tool generates"; a file that has already been named isn't touched again.
- **External files that `rex text` is pointed at are not renamed**. A podcast in `~/Downloads` is someone else's file, so only the transcript gets named, and not a single byte of the original is touched.

When tuning the vocabulary list, you can look at the candidate ranking directly:

```bash
python3 tools/keywords.py 某个稿子.txt --glossary tools/whisper-prompt.txt --verbose
```

### Why a track is empty

On a track where nobody is speaking, whisper will **make up** content. In testing, a track containing nothing but ambient noise floor was transcribed as "中文字幕:王智英 李宗盛" (Chinese subtitles: Wang Zhiying, Li Zongsheng): its training data included subtitled videos.

So VAD is on by default: passages without a human voice are skipped entirely, and an empty transcript says so explicitly: "这一轨 VAD 没找到人声" (VAD found no voice on this track). To see the raw behavior, add `--no-vad`.

---

## 6. Recordings made on the phone

iPhone Voice Memos sync to the Mac through iCloud, and `rex` picks them up directly: **the phone takes care of one-press recording, the Mac takes care of transcription**. The vocabulary list and the replacement table are both reused, so you don't have to maintain a second set on the phone.

```bash
rex phone      # list the 10 most recent
rex phone 1    # fetch item 1, copy it into ~/Recordings/ and transcribe it
```

```
iPhone 语音备忘录（最近 10 条）

   1  2026-08-15_2121   69 分 39 秒    287M 空间音频
   2  2026-08-14_1609   14 分 07 秒    6.5M
   3  2026-08-14_1440   46 分 20 秒     22M
```

### What to set up on the phone

1. Settings → your name → iCloud → **turn on Voice Memos** (syncing depends on it)
2. Settings → Action Button → choose **Voice Memos**. Press and hold to start recording; release to stop
3. If you want a second way in: you can also add Voice Memos to Control Center

### What it does

It takes the **first audio track** of the selected memo, converts it to mono AAC and saves it in `~/Recordings/`, then runs it through exactly the same transcription pipeline as a Mac recording.

Why make a copy instead of transcribing the original directly? Three reasons:

- On the iPhone 17 Pro, Voice Memos records **spatial audio** (`.qta`) by default: one hour is 287 MB, and 48 MB once extracted
- A `.qta` file has **two audio tracks**, and one of them is `apac`, which ffmpeg can't decode. So `-map 0:a:0` has to be passed explicitly; you can't gamble on ffmpeg's default stream selection
- The memo's container is managed by Voice Memos: delete that memo on the phone and the original goes with it

A memo that has been fetched once isn't fetched again; it is only re-transcribed.

### Recording in the phone's browser, streamed live: `rex link`

Voice Memos waits for iCloud, and you still have to run `rex phone` on the Mac afterwards. `rex link` lets the phone's browser record directly, **sending a chunk back to the Mac every 5 seconds**. When you stop, the recording goes into the inbox and through `rex go`; a few minutes later the transcript shows up on the same page, with Word and subtitle downloads.

```bash
rex link             # start the service, open tailscale serve, print a QR code
rex link status      # is it running, and at what address
rex link stop        # shut it down (the tailscale serve port is closed too)
rex link new-token   # make a new token; old QR codes stop working
```

Before the first use:

1. Install Tailscale on the Mac and the phone and sign in with the same account
2. At https://login.tailscale.com/admin/dns, turn on **MagicDNS** and **HTTPS Certificates**
   (phone browsers only allow the microphone on https pages; `tailscale serve` uses the tailnet's real certificate, no self-signed one)
3. To see the QR code right in the terminal: `brew install qrencode` (without it, the address is printed for you to open on the phone)

The phone page has three parts: a big red button to record; "upload a file" (a Voice Memo or an export from another recorder, which goes into the inbox as is); and recent transcripts, which expand to the full text with Word and subtitle downloads.

Notes:

- **Keep the screen on and stay on the page while recording**: phone browsers stop the microphone in the background. The page asks for a screen wake lock
- If the network drops, what was already sent is kept, and the remaining chunks follow in order when it comes back. If the page is closed or the phone dies: after half an hour without a new chunk, whatever arrived still goes into the inbox, with "phone-partial" in its name. If the Mac restarted in the middle, that happens the next time you run `rex link`
- For safety it is separate from the Recording Desk: its own process, bound to `127.0.0.1`, reachable from outside only through `tailscale serve`. It can only receive recordings and files, list transcripts and download them; it cannot delete, edit, start a recording or send anything to Claude. Requests that write anything must carry the token in a header and come from the same origin
- The log is in `~/Library/Logs/rex-link.log`; chunks still being received are in `~/.cache/rex/link/`

### Podcasts: `rex url`

```bash
rex url https://www.xiaoyuzhoufm.com/episode/670a025626fe2954b1a092f3
```

```
  来源：og:audio
  节目：投资ABC · E33 财富规划：加上这一步，你的投资理财之路才算完整
  时长：21 分 25 秒
  ✓ ~/Recordings/2024-10-14_0000_web_投资ABC-E33-财富规划-加上这一步….m4a  37.6M

转写 … → 6263 字
```

**You don't need to install any downloader.** Pages on Xiaoyuzhou (a podcast app) and similar sites put the audio URL right there in `og:audio`. That is a standard Open Graph tag, published precisely so that other players can embed the audio. In testing, that `media.xyzcdn.net/….m4a` URL had no authentication, no signature and no hotlink protection; a single curl command downloaded it.

Finding the audio URL goes through four stages in order of reliability, and **if none of the four hits, it says plainly that it found nothing and prints what it tried**:

1. The link itself is an audio file (`.m4a`/`.mp3`…): download it directly, without parsing a web page
2. `og:audio` / `twitter:player:stream`: standard tags, the most reliable
3. `enclosure.url` in `__NEXT_DATA__`: this also yields the title, podcast name, publication date and duration
4. Fallback: a regex over the whole page to fish out audio links (not necessarily the episode itself; it gets flagged)

The file name uses **the episode's publication date**, not the download date; otherwise a pile of old episodes would all land on today and the `rex find` timeline would be ruined. The name already contains the real title, so **keyword-based automatic naming is skipped**; that layer is meant for spoken transcripts that have no title.

> ⚠️ **An incomplete download must report an error, not print ✓.** This was learned the hard way: the first version stopped after getting 1048576 of the 39432614 bytes (exactly 4 read blocks) and printed a ✓ anyway. When the other end closes the connection early, `urlopen`'s `read()` returns an empty byte string and **does not raise an exception**. Now it checks against `Content-Length`; if bytes are missing, it resumes with `Range` (5 retries), and if bytes are still missing, it reports an error and deletes the partial file.

This is for publicly released podcasts, and it does the same thing any podcast client does. Paid series and members-only pages don't have a public audio URL in the first place.

### Files sent with AirDrop: `rex in`

If you'd rather not go through iCloud sync, you can also AirDrop straight from the phone to the computer. AirDropped files land in `~/Downloads`; then:

```bash
rex in
```

```
可以转的文件（改 REX_DROP 换扫描目录）

   1    69 分     67M  Main St 4.m4a
   2    46 分     23M  Central Library 7.m4a
   5   130 分    125M  Main St 3.m4a

  转一个：rex in 1    转多个：rex in 1 3    全转：rex in all
```

```bash
rex in 1
```

Files that have already been transcribed are marked "已转过" (already transcribed), and `rex in all` skips them automatically. Change the scanned directories with `REX_DROP` (separate multiple directories with colons).

**The iPhone names voice memos after the location** (`Main St 4`, `Central Library 7`). That name carries information, so it is kept in the file name instead of being replaced by a timestamp:

```
Main St 4.m4a  →  2026-08-15_2339_drop-Main-St-4.m4a
                →  after transcription: 2026-08-15_2339_drop-Main-St-4_keywords.m4a
```

The number at the end is deliberately kept: if you recorded seven memos at the same place, it is what tells them apart. A name that is too long is truncated by **word**, never cut in the middle of a word.

Two things worth knowing:

- **It only copies; it never moves or deletes the original.** `~/Downloads` is your folder, and this tool has no business touching what's in it. In testing, the original's byte count was unchanged after a run.
- **If it can remux losslessly, it doesn't re-encode.** Files that arrive via AirDrop are AAC, and remuxing them straight into an mp4 container is instantaneous: in testing, a 130-minute, 125 MB file took just **0.49 seconds**. When the source isn't AAC (wav / flac / opus), `-c:a copy` fails, and only then does it fall back to re-encoding to AAC.

### Recording what the phone is playing: not possible, only workarounds

**iOS doesn't allow any app to capture system audio**; there is no equivalent of BlackHole. This is a sandbox rule, not a missing tool.

The workaround is **screen recording**: Control Center → Screen Recording, which records the app's sound along with the screen. The finished recording is in Photos; AirDrop it to the Mac or save it to Files, then:

```bash
rex text ~/Downloads/某个录屏.mov
```

`rex text` accepts `.mov` files and automatically picks the first audio track. Two limitations, stated up front:

- **DRM-protected content records without sound**: the picture is there, the audio is silent
- Screen recording also captures **notification sounds**

If all you want is the text of a podcast episode, the more direct route is to get the original audio file (download it in the podcast app, or download it straight from the RSS feed on the Mac) and then run `rex text`; that is cleaner than a screen recording.

### Invalid bytes

One learned the hard way on real recordings: at Chinese segment boundaries, whisper occasionally emits half a character, which leaves an invalid UTF-8 byte in the transcript. Synthetic speech doesn't expose it, but as soon as you transcribe a real recording a dozen or so minutes long, things break: Python raises `UnicodeDecodeError`, `tr` reports `Illegal byte sequence`, the replacement layer doesn't run at all, and the character count comes out wrong as well (at the time it reported 1454 characters; the real count was 2831).

Now it repairs this itself and reports it:

```
! 有 1 处无效字节（whisper 在分段边界上吐了半个字），已标成 �
```

It doesn't silently drop anything, so you know that something was originally at that spot.

---

## 7. Binding it to a hotkey

`rex` with no arguments is a **toggle**: if it isn't recording, it starts recording the microphone; if it is recording, it stops. One key is enough.

1. Open the Shortcuts app and create a new shortcut
2. Add a "Run Shell Script" action with the content `export PATH="/opt/homebrew/bin:$PATH"; "$HOME/.local/bin/rex"` (the shell that Shortcuts starts doesn't read `~/.zshrc`, so without the PATH it can't find ffmpeg)
3. In the info panel on the right, set a key, for example ⌥⌘R
4. The first time you press it, a microphone permission prompt appears ("rex 录音采集" (rex audio capture) would like to use the microphone); click Allow

**After binding it, run `rex status` once to confirm it really is still recording.** Whether the background process survives the Shortcuts layer is worth checking once with your own eyes.

---

## 8. What it does to your audio settings

Only `rex sys` and `rex both` change anything, and only when they go through BlackHole; `rex` (microphone only) changes nothing. After you switch to the system audio tap (`rex check sys` passes), **nothing is changed**, and the volume keys work as usual too. The rest of this section only describes the old BlackHole path.

Recording system audio requires sending the sound into BlackHole (a virtual sound card), but if output were simply switched over to it, you yourself would no longer hear anything. So it builds a "multi-output device" on the spot, based on **the output device you are using right now**:

```
Before   Default output: AirPods Pro
During   Default output: 录音直通（AirPods Pro）                ← "recording passthrough"
                         Members: BlackHole 2ch + AirPods Pro   ← headphones play sound as usual
After    Default output: AirPods Pro                            ← switched back, temporary device deleted
```

Switch to another pair of headphones or to speakers, and it follows along; no configuration changes needed. **If your current output already includes BlackHole** (for example, you picked a Multi-Output Device manually), it doesn't change a thing.

There is only one cost: while recording, **the volume keys don't work** (multi-output devices don't support hardware volume), so use the app's own volume slider.

---

## 9. Troubleshooting

### System audio recorded before 2026-09-22 is missing 11–21%

**This is not something you did wrong; it was a bug in the tool, and it has been fixed.** Capture used to be handed to ffmpeg's avfoundation, which silently drops about 14% of the samples: no error, the file looks normal and plays fine, it is just missing a slice, spread evenly throughout.

Compared at the same moment, reading BlackHole directly through CoreAudio for 20 seconds got **99.94%** of the samples, while ffmpeg got only **85.9%**; the microphone was the same (99.90% vs. 86.1%). The devices delivered every sample; it was ffmpeg that dropped them. Measured on recordings on this Mac:

| Recording | Lost |
|---|---|
| 2026-08-16 Tencent Meeting `both --split` (two tracks) | 18.5% |
| 2026-08-20 `sys` (6 hours) | 20.8% |
| 2026-08-28 / 09-18 / 09-22 `sys` | 10.8%–14.1% |
| `phone`, transferred from the iPhone | 0% |

A mixed `both` recording looks like 0%, but it lost samples all the same: its filter chain fills the holes with silence, so you can't see it.

The consequences go beyond a few missing sentences: the audio stutters, and language detection misjudges (5.8 minutes of one recording were detected as Icelandic, and not a single word was transcribed); the wav used for transcription has the gaps squeezed out, so the further into the recording, the further the subtitles drift from the audio.

**Recordings are no longer captured by ffmpeg**: `audiocap` (reading CoreAudio directly) hands every frame to ffmpeg, and measured loss is zero in all four modes. **Samples that were lost before cannot be recovered**: they never made it into the file during capture. What can be repaired is the timeline and the language segmentation; run `rex text` again and the repairs are applied.

To check for yourself whether a recording lost samples, **count frames; don't go by the duration**:

```bash
ffprobe -v error -select_streams a:0 -count_packets \
  -show_entries stream=nb_read_packets,sample_rate:format=duration -of default=nw=1 某.m4a
```

`nb_read_packets × 1024 ÷ sample_rate` should roughly equal `duration`.


### The recording is empty, or you suspect nothing was recorded

First, spend 3 seconds on a test:

```bash
rex check
```

```bash
rex check sys
```

(The first time you run either command, it shows a permission prompt: `rex check` asks for the microphone, and `rex check sys` asks for "System Audio Recording Only". Click Allow; the command waits until you have clicked, then runs the test. `rex check sys` plays a test tone by itself and records it through the system audio tap; if nothing comes through, it plays it once more over the old BlackHole route. Neither route needs you to play anything.)

### Recording computer audio while wearing AirPods (2026-10-13)

**AirPods' "automatic switching" grabs the output.** The AirPods are connected to both the Mac and the iPhone, and as soon as the Mac makes a sound while the AirPods in your ears aren't in use, they change the output straight to the AirPods. Recording computer audio used to rely on "录音直通" (recording passthrough: BlackHole + your headphones), and once the output is changed, BlackHole receives nothing. On 2026-10-13, the output was grabbed 6 seconds after recording started, and the remaining 47 minutes were all silence.

There are now two lines of defense:

1. **Default: automatic reconnection within two seconds.** While recording, rex checks the output every two seconds; if it has been switched away, rex rebuilds the passthrough around the new output device, switches back, and notes this in the `rex stop` report. If the output is grabbed three or more times within a minute, rex stops fighting over it and tells you with a notification (with an alert sound).
2. **More robust: the system audio tap.** It copies everything the computer plays directly and **doesn't change the output device at all**, so recording continues however the AirPods switch, and the volume keys work as usual. It needs permission once first; run this in the terminal:

   ```bash
   rex check sys
   ```

   You'll see the prompt "“rex 录音采集”想录制系统音频" ("rex audio capture" would like to record system audio). Click Allow; once you have, the command plays a test tone and runs the test. When you see "✓ 系统音频接口收到了测试音" (✓ The system audio tap received the test tone), all computer-audio recording goes through the tap from then on. If no prompt appeared, or you denied it at the time, go to System Settings → Privacy & Security → Screen & System Audio Recording, turn on "rex 录音采集" (rex audio capture) under "System Audio Recording Only", and run the command again.

   **The permission belongs to the recording program itself, not to the terminal.** In the first version, on 2026-10-13, the permission went to the terminal: when run from Ghostty, the system attributed the request to Ghostty, and since Ghostty doesn't declare the "record system audio" usage, the system **didn't even show a prompt**, and the tap quietly delivered all zeros. Now `audiocap` requests permission in its own name, so it works the same whether it is started from any terminal, the Recording Desk or the background. The cost is that after it has been recompiled (because its source changed), the system treats it as a new program and asks again; `rex check sys` and the start of a recording will tell you so. When the tap has no permission, computer-audio recording automatically falls back to the BlackHole route, so recording still starts. The switch is stored in `~/.config/rex/system-audio` (its content is `tap`); to go back to the old route, delete this file, or temporarily use `REX_SYS=blackhole rex both`.

   This tap has a quirk: **when no program on the computer is playing sound, it delivers not a single frame** (not recorded silence, but nothing at all). If the other side hasn't spoken yet when recording starts, the recording can't get going. So while recording, `audiocap` itself writes silence to the **built-in speakers** (inaudible, and it doesn't touch the AirPods) to keep the tap running. The third step of `rex check sys` verifies exactly this: it records for 2 seconds with nothing playing, and data must keep coming the whole time.

**Don't forget to record yourself, too:** for a call, press "我 + 对方" (Me + Other side), which is `rex both` on the command line. "只录电脑声音" (Computer audio only), that is `rex sys`, never records the microphone.

**Why this command is needed:** when microphone permission has been denied, or something is wrong in the audio chain, macOS **feeds digital silence instead of reporting an error**. ffmpeg runs normally, the file is created as usual, there is no warning at all, and only after an hour of recording do you find out it's empty. That's why `rex stop` always reports the peak:

- A peak of **−91 dB** = exact digital silence; nothing was received
- A microphone in a quiet room sits around **−40 dB**; that is normal
- A peak **> −0.5 dB** triggers a warning about possible clipping

### Lid closed: your own track is empty

When a laptop's lid is closed, the built-in microphone is disconnected **in hardware** (an Apple privacy design). The system still lists "MacBook Air Microphone", but everything read from it is 0, exactly as when the audio chain is broken. When you start recording with the built-in microphone, `rex` checks this first and warns you on the spot if the lid is closed; if you really need to record with the lid closed, use `--device` to switch to another microphone (headphones, iPhone).

### "Almost digital silence"

There are two causes:

1. **Permission**: in System Settings → Privacy & Security → Microphone, "rex 录音采集" must be turned on (the first recording or `rex check` asks you with a prompt; if you denied it before, you have to come here and turn it on manually). To the system, capturing sound from BlackHole also counts as "using the microphone", so it needs this permission too.
2. **The audio chain is broken**, which is common after a Bluetooth device disconnects. This really happened once: after the headphones disconnected, the built-in microphone kept putting out −91 dB, and calling ffmpeg directly gave the same result. Restart the audio service:

   ```bash
   sudo killall coreaudiod
   ```

### `rex phone` says "no recordings", but the Voice Memos app clearly has some

**It's permissions, not missing files.**

The Voice Memos container `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/` is protected by macOS TCC, and **permission is granted per app**. Finder being able to see it, or the Voice Memos app being able to see it, doesn't mean your terminal can: without permission, that directory simply looks empty to the terminal.

The fix:

1. System Settings → Privacy & Security → **Full Disk Access**
2. Add the terminal app you use (Terminal / iTerm / VS Code…)
3. **Quit the terminal completely, then reopen it**: a permission change doesn't take effect until the process restarts

`rex phone` now reports these three cases separately, instead of lumping them together as "没有录音" (no recordings):

| Probe result | Meaning |
|---|---|
| `NODIR` | iCloud sync isn't turned on |
| `DENIED` | A permission problem; follow the three steps above |
| `OK 0` | The directory really is empty |

### "Couldn't create the passthrough device"

Your current output device is itself an aggregate device. Switch back to ordinary headphones or speakers in the menu bar, then record.

### "Already recording"

```bash
rex status
```

Check whether it really is recording. If the process is gone but the state file is still there, run `rex stop` once to clear it.

### It crashed last time and the output device wasn't switched back

Select it again manually in the menu bar. The next time `rex` starts, it automatically cleans up leftover temporary devices.

### Recording during a video call (WeChat, FaceTime and the like)

When a call app opens the microphone, it switches the Mac's built-in microphone from 1 to 3 channels (and back when the call ends), and the device pauses for about 0.25 s at each switch;
the computer-audio track pauses briefly too. Since 2026-10-17 the recording program keeps the channel count it started with and fills each pause with the same length of silence,
so the two tracks stay aligned; the report at stop says "changed format N time(s) mid-recording … aligned automatically".

In recordings made before that, the microphone track is garbled from the moment the call opened the microphone (two thirds of its data was lost); the other side's track is unaffected.
If a track is losing data during a recording, the watchdog shows a notification, and the report at stop says how much was lost.

### The Recording Desk suddenly stopped working (it was fine before)

The page won't load, `rex app status` says the Recording Desk is "stuck", and the log shows `PermissionError: Operation not permitted`.
Your recordings and transcripts are fine. This is the Recording Desk from before 2026-10-17: it ran the code in the Documents folder, and macOS only lets the program that started it
(a terminal app, or Claude) read there. Once that program quit entirely (an update restart, for example), the running Recording Desk could no longer read its own page and scripts.

Run `rex app` once in a terminal: it recognizes the stuck one, stops it and switches to the background one (after that this no longer happens).

---

## 10. Environment variables

| Variable | Default | Description |
|---|---|---|
| `REX_DIR` | `~/Recordings` | Where recordings are saved |
| `REX_LANG` | (your macOS language) | Output language, `en` or `zh`. Or write it to `~/.config/rex/lang` to make it permanent |
| `REX_MAX` | `21600` (6 hours) | Maximum recording length, in seconds |
| `WHISPER_MODEL` | `~/.cache/whisper/ggml-large-v3-turbo-q5_0.bin` | Use a different recognition model |
| `WHISPER_VAD_MODEL` | `~/.cache/whisper/ggml-silero-v5.1.2.bin` | Use a different VAD model |
| `REX_NAMES` | `我,对方` (Me, Other side) | What the two sides are called in dialogue transcripts; same as `--names` |
| `REX_DIAR_DIR` | `~/.cache/sherpa-onnx` | Where the program and models for voiceprint speaker diarization are kept |
| `REX_INBOX` | `~/Recordings/收件箱` (the inbox) | The inbox for the end-to-end pipeline |
| `REX_CLAUDE_MODEL` | (the claude CLI's default) | Which model proofreading and analysis use, e.g. `sonnet` |
| `REX_CLAUDE_ENV` | (clears `ANTHROPIC_*`) | Set to `inherit` to keep the settings from your terminal (for example an `ANTHROPIC_BASE_URL` pointing at another provider's API) instead of using the Claude login |
| `REX_PROOF_EFFORT` | `low` | How deeply Claude thinks during proofreading (`low` / `medium` / `high`). In testing, `low` was both fast and accurate; see "Usage" in section 5 |
| `REX_SYS` | (per `~/.config/rex/system-audio`) | Which route computer-audio recording takes: `tap` (system audio tap) or `blackhole`; temporarily overrides the result of `rex check sys` |
| `REX_ROUTE_EVERY` | `2` | When going through BlackHole, how often (in seconds) to check whether the output has been switched away; `0` turns off automatic reconnection |
| `REX_WATCH` | `180` | How often (in seconds) the watchdog checks itself; `0` turns it off |
| `REX_DROP` | `~/Downloads:~/Desktop` | Which directories `rex in` scans, separated by colons |
| `REX_LANGS` | `zh,en` | Which languages transcription recognizes; when detection fails, the first one is used |
| `REX_APP_PORT` / `REX_APP_LOG` | `8790` / `~/Library/Logs/rex-app.log` | Port and log of the Recording Desk |
| `REX_INBOX_LABEL` / `REX_INBOX_LOG` | `local.rex.inbox` / `~/Library/Logs/rex-inbox.log` | launchd label and log of the inbox background job |
| `REX_RUNTIME` | `~/.local/share/rex-runtime` | Where the copies of the scripts used by background jobs (the inbox watcher, the background Recording Desk) are kept |
| `REX_BIN_DIR` | `~/.local/share/rex/bin` | Where the compiled audiocap / audiodev go (must be outside Documents; moving them needs permission again) |
| `REX_LINK_PORT` / `REX_LINK_HTTPS` / `REX_LINK_LOG` | `8791` / `8443` / `~/Library/Logs/rex-link.log` | `rex link`: local port, the https port tailscale serve exposes, and the log |

---

## 11. What gets installed, and the file list

```bash
brew install ffmpeg blackhole-2ch whisper-cpp
```

After installing BlackHole, you need to **reboot once**. `switchaudio-osx` isn't needed: device switching is done by this repository's `audiodev`. You also need the Xcode Command Line Tools (`xcode-select --install`; the first run compiles `audiodev` / `audiocap` and signs them with `codesign`) and the Claude Code CLI (used for the proofreading and analysis in `rex go` and for `rex chat`; without it, rex only transcribes and doesn't proofread).

| File | What it is |
|---|---|
| `tools/rex.sh` | The main script, symlinked to `~/.local/bin/rex` |
| `tools/audiodev.swift` | Queries/switches audio devices and builds multi-output devices on the fly. Compiled automatically on first run |
| `~/.local/share/rex/bin/audiodev` | Build output (outside Documents); recompiled automatically when the source changes |
| `tools/whisper-prompt.txt` | The prompt vocabulary list |
| `tools/whisper-fix.txt` | Deterministic replacements applied after transcription |
| `tools/keywords.py` | Extracts keywords from transcripts, used to name files |
| `tools/audiocap.swift` | **Audio capture**: reads devices directly through CoreAudio and passes the audio through a named pipe to ffmpeg for encoding. Compiled automatically on first run |
| `tools/audiocap-Info.plist` | The program name "rex 录音采集" (rex audio capture) and two usage descriptions, linked into `audiocap`; the system needs them to show the permission prompts |
| `~/.local/share/rex/bin/audiocap` | Build output (outside Documents; `rex` in the terminal and the background Recording Desk share this one). Recompiled only when the content of the source or the plist changes (judged by a fingerprint of the content, so git refreshing file times doesn't count). The permissions are recorded for this path: after a rebuild or a move it needs permission once more |
| `~/Library/LaunchAgents/local.rex.app.plist` | launchd configuration of the background Recording Desk; written by `rex app`, removed by `rex app stop` |
| `tools/whisper_run.py` | The main transcription program: detects the language, segments, calls whisper-cli, and stitches the results back onto the timeline |
| `tools/podcast_url.py` | `rex url`: finds the audio URL on a podcast page and downloads it |
| `tools/rex_trim.py` | `rex trim`: cuts off the silence at the end |
| `tools/speakers.py` | Merges two-track transcriptions into a dialogue transcript: repositions segments, removes echo, warns about empty tracks |
| `tools/diarize.py` | `rex who`: separates speakers by voiceprint, using sherpa-onnx |
| `tools/proofread.py` | Claude proofreading for `rex go`: accepts only a list of edits, applies them as exact replacements, and leaves uncertain spots unchanged |
| `tools/analyze.py` | Claude analysis for `rex go`: writes the analysis report and leaves a session you can return to with `claude --resume` |
| `tools/claude_cli.py` | How the two above call the `claude` CLI: clears variables that point at another provider's API, and stops immediately when it detects you're not logged in or out of credit |
| `tools/rex_app.py`, `tools/rex_app/` | The Recording Desk (`rex app`): the local web server and pages. Listens only on 127.0.0.1 |
| `tools/rex_link.py`, `tools/rex_link/` | Phone recording (`rex link`): a service and phone page that only receive recordings and files and offer transcripts for download. Listens only on 127.0.0.1; reached through tailscale serve |
| `tools/rex_export.py` | `rex export`: Word (a .docx assembled with the standard library) and subtitles |
| `~/.config/rex/link-token` | The `rex link` token (mode 600); replaced by `rex link new-token` |
| `~/.local/share/rex-runtime/` | Copies of the scripts for the inbox background job (background jobs can't read "Documents"), **synced automatically** |
| `~/.cache/sherpa-onnx/` | Program and models for voiceprint speaker diarization (about 93 MB), **not in the repository** |
| `~/Recordings/` | Recordings and transcripts, **not in the repository** |
| `~/.config/rex/` | `system-audio` (which route computer-audio recording takes), `text-dirs` (which other directories `rex find` also searches), `analysis-prompt.md` (the analysis prompt) |
| `~/.cache/rex/` | The Recording Desk's duration cache and job logs; `claude/` is an empty directory used when proofreading and analysis run `claude` (so that a CLAUDE.md from elsewhere doesn't get pulled in) |
| `~/Library/LaunchAgents/local.rex.inbox.plist` | The inbox background job (written by `rex auto install`) |
| `~/Library/Logs/rex-{inbox,app}.log` | Logs for the inbox job and the Recording Desk |
| `~/.cache/whisper/` | whisper models, **not in the repository** |
| `~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/` | Voice memos synced over from the iPhone, owned by Voice Memos; **read only, never written to** |

---

## 12. For whoever changes this script next

**When Chinese text immediately follows a variable, you must write `${var}`, not `$var`.** macOS only has bash 3.2, which uses `isalnum()` to decide where a variable name ends, and `isalnum()` follows the locale: under UTF-8, it swallows the bytes of "）" and "」" into the variable name:

```
LANG=en_US.UTF-8  →  bash: x<0xef>: unbound variable
LC_CTYPE=C        →  （hi）      ← same line of code
```

This has really happened, in six places: `rex sys` exited as soon as it ran. Scan the whole file:

```bash
grep -nP '\$(?!\{)[A-Za-z_]\w*[^\x00-\x7F]' tools/rex.sh
```

(`-P` requires ugrep or GNU grep; the system's own `/usr/bin/grep` doesn't have it. An equivalent: `perl -ne 'print \"$.:$_\" if /\$(?!\{)[A-Za-z_]\w*[^\x00-\x7F]/' tools/rex.sh`)

**And after making changes, run it once under a UTF-8 locale**; don't test only in your own shell:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 rex devices
```

The remaining design trade-offs are written in the header comment of `tools/rex.sh` and in the comments of each script; each one explains why it is done this way.
