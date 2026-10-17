"""audiocap 的 ingest（tools/audiocap.swift 里「// ingest: begin」到「// ingest: end」那一段）：设备录到一半换了声道数，
交给 ffmpeg 的仍然是开录时的声道数，采样一个不多、一个不少；换格式那一下设备停顿了，补上同样长的静音，两路照样对齐。

2026-10-17 一边开微信视频一边录「我 + 对方」：内置麦克风在通话打开它时从 1 声道变成 3 声道，ffmpeg 还按 1 声道读，
只读得动三分之一，其余全丢，那一路从第 3 分钟起成了乱的。这里把那一段原样抽出来，和一个小测试程序一起用 swiftc
编译运行，喂给它伪造的 IO 块。没有 swiftc 就跳过。

    python3 -m unittest discover -s tests
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "audiocap.swift")

HARNESS = r'''
import CoreAudio
import Foundation

var ch = 1
let rate: Double = 48000
var overrun = 0
var lock = os_unfair_lock()
let scratch = UnsafeMutablePointer<Float>.allocate(capacity: 16384 * 4)
let silence = UnsafeMutablePointer<Float>.allocate(capacity: 16384 * 4)
silence.initialize(repeating: 0, count: 16384 * 4)
var got: [Float] = []
var gotSrc: [Int] = []
func push(_ src: UnsafePointer<Float>, _ nFloats: Int, _ srcCh: Int) {
    got.append(contentsOf: UnsafeBufferPointer(start: src, count: nFloats))
    gotSrc.append(srcCh)
}

/*INGEST*/

func interleaved(_ frames: Int, _ chans: Int, _ f: (Int, Int) -> Float) -> UnsafeMutableAudioBufferListPointer {
    let abl = AudioBufferList.allocate(maximumBuffers: 1)
    let data = UnsafeMutablePointer<Float>.allocate(capacity: frames * chans)
    for i in 0..<frames { for c in 0..<chans { data[i * chans + c] = f(i, c) } }
    abl[0] = AudioBuffer(mNumberChannels: UInt32(chans), mDataByteSize: UInt32(frames * chans * 4), mData: data)
    return abl
}
func planar(_ frames: Int, _ chans: Int, _ f: (Int, Int) -> Float) -> UnsafeMutableAudioBufferListPointer {
    let abl = AudioBufferList.allocate(maximumBuffers: chans)
    for c in 0..<chans {
        let data = UnsafeMutablePointer<Float>.allocate(capacity: frames)
        for i in 0..<frames { data[i] = f(i, c) }
        abl[c] = AudioBuffer(mNumberChannels: 1, mDataByteSize: UInt32(frames * 4), mData: data)
    }
    return abl
}
var failures = 0
func check(_ name: String, _ ok: Bool) { print((ok ? "ok: " : "FAIL: ") + name); if !ok { failures += 1 } }
func reset(_ c: Int) { ch = c; got = []; gotSrc = []; overrun = 0; lastInT = -1; lastInFrames = 0; gapFrames = 0 }
func stamp(_ seconds: Double, valid: Bool = true) -> UnsafeMutablePointer<AudioTimeStamp> {
    let t = UnsafeMutablePointer<AudioTimeStamp>.allocate(capacity: 1)
    t.initialize(to: AudioTimeStamp())
    t.pointee.mHostTime = UInt64((seconds / hostTick).rounded())
    t.pointee.mFlags = valid ? .hostTimeValid : []
    return t
}

reset(1); ingest(interleaved(4, 1) { i, _ in Float(i) }, nil)
check("mono stays as is", got == [0, 1, 2, 3] && gotSrc == [1])

// 开录时 1 声道，设备变成 3 声道交错（2026-10-17 那一回）：取平均，帧数不变
reset(1); ingest(interleaved(4, 3) { i, c in Float(i * 10 + c) }, nil)
check("3ch interleaved -> mono average", got == [1, 11, 21, 31] && gotSrc == [3])

reset(1); ingest(planar(4, 3) { i, c in Float(i * 10 + c) }, nil)
check("3ch planar -> mono average", got == [1, 11, 21, 31] && gotSrc == [3])

// 开录时 3 声道（通话中开的录），挂断后设备变回 1 声道：复制成 3 路
reset(3); ingest(interleaved(2, 1) { i, _ in Float(i + 5) }, nil)
check("mono -> 3ch duplicated", got == [5, 5, 5, 6, 6, 6] && gotSrc == [1])

reset(2); ingest(interleaved(2, 3) { i, c in Float(i * 10 + c) }, nil)
check("3ch -> 2ch takes the first two", got == [0, 1, 10, 11])

reset(2); ingest(planar(3, 2) { i, c in Float(i * 10 + c) }, nil)
check("2ch planar -> 2ch interleaved", got == [0, 1, 10, 11, 20, 21])

// 交给下游的永远是「帧数 × 开录时的声道数」：ffmpeg 靠这个跟得上
reset(1); ingest(interleaved(512, 3) { _, _ in 0.5 }, nil)
check("512 frames of 3ch -> 512 mono samples", got.count == 512 && got.allSatisfy { abs($0 - 0.5) < 1e-6 })

reset(1); ingest(interleaved(20000, 3) { _, _ in 0 }, nil)
check("an oversized block is counted, not silently dropped", got.isEmpty && overrun == 20000)

// 设备停顿（换格式那一下）：按时间戳补同样长的静音
reset(1); ingest(interleaved(480, 1) { _, _ in 1 }, stamp(0)); ingest(interleaved(480, 1) { _, _ in 1 }, stamp(0.01))
check("back-to-back blocks: nothing added", got.count == 960 && gapFrames == 0)

reset(1); ingest(interleaved(480, 1) { _, _ in 1 }, stamp(1.0)); ingest(interleaved(480, 1) { _, _ in 1 }, stamp(1.26))
check("0.25 s pause filled with 0.25 s of silence", abs(gapFrames - 12000) <= 2 && got.count == 960 + gapFrames
      && got[480..<(480 + gapFrames)].allSatisfy { $0 == 0 } && got.last == 1)

reset(1); ingest(interleaved(480, 1) { _, _ in 1 }, stamp(1.0)); ingest(interleaved(480, 1) { _, _ in 1 }, stamp(7.01))
check("a 6 s pause (the Mac slept) is not filled", got.count == 960 && gapFrames == 0)

reset(1); ingest(interleaved(480, 1) { _, _ in 1 }, stamp(1.0, valid: false)); ingest(interleaved(480, 1) { _, _ in 1 }, stamp(1.26, valid: false))
check("no valid timestamps: nothing added", got.count == 960 && gapFrames == 0)

// 换格式和停顿一起来（真实情况）：开录 1 声道，停顿 0.25 秒后来的是 3 声道
reset(1); ingest(interleaved(480, 1) { _, _ in 1 }, stamp(2.0)); ingest(interleaved(480, 3) { _, c in Float(c) }, stamp(2.26))
check("pause + switch to 3ch: silence, then the average", abs(gapFrames - 12000) <= 2 && got.count == 960 + gapFrames
      && got.last == 1 && gotSrc.last == 3)

reset(3); ingest(interleaved(480, 3) { _, _ in 1 }, stamp(3.0)); ingest(interleaved(480, 1) { _, _ in 2 }, stamp(3.26))
check("3ch recording, pause, back to mono: silence in 3 channels, then duplicated", got.count == (960 + gapFrames) * 3
      && got[(480 * 3)..<((480 + gapFrames) * 3)].allSatisfy { $0 == 0 } && Array(got.suffix(3)) == [2, 2, 2])

exit(failures == 0 ? 0 : 1)
'''


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"), "要 macOS 和 swiftc")
class Ingest(unittest.TestCase):
    def test_channel_count_changes_mid_recording(self):
        with open(SRC, encoding="utf-8") as fh:
            code = fh.read()
        a, b = code.index("// ingest: begin"), code.index("// ingest: end")
        d = tempfile.mkdtemp()
        try:
            src = os.path.join(d, "t.swift")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(HARNESS.replace("/*INGEST*/", code[a:b]))
            r = subprocess.run(["swiftc", "-O", "-o", os.path.join(d, "t"), src],
                               capture_output=True, text=True, timeout=600)
            self.assertEqual(r.returncode, 0, r.stderr[-3000:])
            r = subprocess.run([os.path.join(d, "t")], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
