# Rex

**English** | [中文](README.zh-CN.md)

A recorder for macOS that you start and stop with one command. It records your microphone, the computer's audio (calls, meetings, videos), or both. Transcription with whisper.cpp runs on your machine. Each transcript line is labeled with who said it. Optionally, Claude proofreads the transcript and writes an analysis. There is also a local web UI, the Recording Desk (录音台).

> **Status**: a personal tool, open-sourced as it is. It only runs on macOS and is tested on macOS 26 with Apple Silicon. Command output, the web UI and code comments are currently in **Chinese**; the manual is in English and Chinese. See [Language](#language).

## Why it exists

Every design decision here comes from a recording that failed without any error message:

- **ffmpeg's avfoundation input drops ~14% of samples.** The file plays normally, but it is missing about a seventh of the audio. rex reads devices directly through CoreAudio with a small Swift helper, `audiocap`. ffmpeg only encodes.
- **AirPods automatic switching takes over the output device mid-call.** When you record system audio through a BlackHole multi-output device and the output changes, BlackHole records silence. rex captures system audio with a **Core Audio process tap** (macOS 14.2+), which never touches the output device. If the tap isn't available, it falls back to BlackHole and switches the output back within 2 seconds.
- **The tap delivers nothing while no app is playing audio.** It doesn't record silence; it delivers no frames at all. `audiocap` writes inaudible silence to the built-in speaker so the tap keeps running.
- **Permission prompts never appeared.** macOS assigns a command-line tool's privacy permissions to the terminal that launched it. A terminal that doesn't declare system audio capture as a purpose gets no prompt, only zeros. `audiocap` relaunches itself as its own "responsible process" with an embedded Info.plist, so the grants belong to "rex 录音采集".
- **"Who said this" is recorded, not guessed.** `rex both` stores the mixed audio plus a separate microphone track and system-audio track in one file. The transcript labels come from the tracks, not from a model.
- **whisper detects the language only once per file.** Chinese/English mixed recordings come out garbled. rex checks the language at several points through the file and transcribes each segment in its own language.
- **Failures are reported.** A watchdog, live level meters per track, digital-silence detection and notifications tell you when something is wrong. If a recording stops on its own, rex finishes the file and tells you.

## Features

| Command | What it does |
|---|---|
| `rex` | Toggle microphone recording (bind it to a hotkey) |
| `rex both` | Microphone + system audio, one file with separate tracks. **Use this for calls.** |
| `rex sys` | System audio only (podcasts, videos) |
| `rex stop` / `rex status` | Stop; check that every track is actually receiving audio |
| `rex text [file]` | Transcribe locally (whisper.cpp, VAD, segments by language) |
| `rex who [file] [n]` | Speaker diarization (sherpa-onnx) for single-track multi-person recordings |
| `rex go [file]` | Transcribe → speakers → Claude proofreading → Claude analysis |
| `rex auto install` | Watch `~/Recordings/收件箱` (inbox) with launchd; anything dropped there goes through `rex go` |
| `rex app` | Recording Desk web UI at `http://127.0.0.1:8790`: record, review corrections (Y/N), ask follow-up questions, search, double-click a recording to move it to the Trash |
| `rex phone` | Import iPhone Voice Memos synced through iCloud |
| `rex url <link>` | Download a podcast episode's audio and transcribe it |
| `rex find <word>` | Search all transcripts |
| `rex trim [file]` | Cut trailing silence (the original goes to the Trash) |
| `rex check` / `rex check sys` | 3-second self-tests; they also trigger the permission prompts |

Run `rex help` for every option. Full manual: [English](docs/manual.md) · [中文](docs/manual.zh-CN.md).

## Requirements

- macOS 14.2 or later for the system-audio tap. Older versions work with BlackHole only.
- [Homebrew](https://brew.sh): `brew install ffmpeg whisper-cpp blackhole-2ch`
  BlackHole is only needed for the fallback path; reboot once after installing it.
- Xcode Command Line Tools (`xcode-select --install`). `audiocap` and `audiodev` are compiled on first run.
- Python 3 (standard library only)
- Optional: [Claude Code](https://claude.com/claude-code) CLI for proofreading and analysis (`rex login`)

Downloaded on first use: the whisper model `large-v3-turbo-q5_0` (~547 MB, to `~/.cache/whisper`), and sherpa-onnx with its models (~93 MB, to `~/.cache/sherpa-onnx`) for `rex who`.

## Install

```bash
git clone https://github.com/hanbinyang707/rex.git
mkdir -p ~/.local/bin && ln -s "$PWD/rex/tools/rex.sh" ~/.local/bin/rex   # ~/.local/bin must be on your PATH
rex check       # microphone: first run asks for microphone permission
rex check sys   # system audio: asks for "System Audio Recording Only"; passes = rex uses the tap from now on
```

## Quick start

```bash
rex both      # record a call: you + the other side
rex stop      # stop; reports peak level and digital silence per track
rex go        # transcribe → speakers → proofread → analysis, for the latest recording
rex app       # open the Recording Desk
```

## Permissions

- Microphone and system-audio permissions belong to **"rex 录音采集"** (the `audiocap` helper), not to your terminal. They work the same whether rex is started from any terminal, the web UI or launchd.
- `audiocap` is ad-hoc signed. **Rebuilding it (any change to `audiocap.swift` or `audiocap-Info.plist`) changes its signature, so macOS asks again.** rex warns you when it rebuilds.
- It uses private APIs: `responsibility_spawnattrs_setdisclaim`, and `TCCAccessPreflight` / `TCCAccessRequest` from TCC.framework. They may break in a future macOS. If the tap stops working, rex falls back to BlackHole for that recording.
- `rex phone` needs Full Disk Access for the terminal you run it from.

## Privacy

- Recording, transcription and speaker diarization all run on your Mac.
- Only `rex go` and the web UI's "ask" box send text out: the transcript goes to Anthropic through your local `claude` login. rex clears `ANTHROPIC_*` environment variables first, so a shell that points `claude` at another provider doesn't redirect your transcripts. Set `REX_CLAUDE_ENV=inherit` to keep them.
- The web UI listens on `127.0.0.1` only and checks the Host header, a per-launch cookie token and the request origin.
- **Recording other people:** consent laws differ (one-party vs. all-party). Tell people you are recording.

## Layout

| Path | What |
|---|---|
| `tools/rex.sh` | The `rex` command (bash 3.2) |
| `tools/audiocap.swift` | CoreAudio capture → named pipe → ffmpeg; system-audio tap; permission handling |
| `tools/audiodev.swift` | List/switch audio devices, build the BlackHole multi-output device |
| `tools/whisper_run.py` | Language probing, segmenting, whisper-cli |
| `tools/speakers.py`, `tools/diarize.py` | Two-track dialogue merge (echo removal); voiceprint diarization |
| `tools/proofread.py`, `tools/analyze.py`, `tools/claude_cli.py` | Claude proofreading (only a list of corrections, applied verbatim) and analysis |
| `tools/rex_app.py`, `tools/rex_app/` | Recording Desk web UI |
| `tools/whisper-prompt.txt`, `tools/whisper-fix.txt` | Templates for your vocabulary hints and fixed replacements; copy them to `~/.config/rex/` and edit there |
| `docs/manual.md`, `docs/manual.zh-CN.md` | Full manual (English, Chinese) |

Your recordings and transcripts stay in `~/Recordings`, never in this repo.

## Development

```bash
python3 -m unittest discover -s tests
bash -n tools/rex.sh
```

Code comments explain *why* (in Chinese). Most describe a real failure and how it was found. Read them before changing a threshold.

## Language

The README and the manual ([English](docs/manual.md), [中文](docs/manual.zh-CN.md)) are bilingual. The command output, web UI and code comments are in Chinese; the manual reproduces output samples verbatim and explains them. English output is on the roadmap; contributions are welcome.

## License

[MIT](LICENSE). Nothing below is bundled; it is installed separately or downloaded on first use: whisper.cpp (MIT), sherpa-onnx (Apache-2.0), pyannote segmentation-3.0 (MIT), 3D-Speaker CAM++ (Apache-2.0), BlackHole (GPL-3.0), ffmpeg (LGPL/GPL).
