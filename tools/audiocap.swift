// audiocap：用 CoreAudio 直接从一个输入设备读采样，原样写到 stdout（float32 交错）。
//
//     audiocap BlackHole               # 一直读，直到收到 SIGINT/SIGTERM 或 stdout 被关掉
//     audiocap "MacBook.*Microph" --info   # 打印「采样率 声道数 设备名」然后退出
//     audiocap BlackHole --seconds 20  # 读 20 秒自己停（验证用）
//     audiocap --list                  # 列出所有能录的输入设备
//     audiocap --system                # 录电脑放出来的所有声音（系统音频接口，不经过 BlackHole）
//     audiocap --system --info --request   # 没授权就弹系统的授权框、等答复（rex check sys 用）
//     audiocap BlackHole --level F     # 每半秒把这一路的电平写进文件 F（录音台、看门狗读它）
//
// ## 为什么要有它
//
// 2026-09-22 查出来的：**ffmpeg 的 avfoundation 输入会静默丢掉约 14% 的采样。**
// 同一台机器同一时刻对照：
//
//     CoreAudio 直读 BlackHole   20.01 秒收到 960000 帧     比例 0.9994
//     ffmpeg avfoundation        20.50 秒只拿到 17.60 秒     比例 0.859
//     CoreAudio 直读内建麦克风    比例 0.9990
//     ffmpeg avfoundation 麦克风  比例 0.861
//
// 设备一个样本都没少给，丢在 ffmpeg 里。`-thread_queue_size 4096`、
// `-drop_late_frames 0` 都试过，一点不变。回头量本机所有录音：凡是 avfoundation
// 直录的 `sys` 和 `both --split`，**都丢了 10.8% ~ 20.8%**，最早一条是 2026-08-16。
// 混音的 `both` 看着是 0%，那是因为滤镜链里的 `aresample=async=1` 把洞用静音
// 填上了——样本照样丢，只是时间轴被补齐所以看不出来。
//
// 丢样本的后果不只是少了几句话：音频一卡一卡的，whisper 的语言识别被扰乱，把
// 整段中文判成冰岛语；转写用的 wav 把空隙挤掉了，字幕时间轴越往后越对不上。
//
// 所以采集不再交给 ffmpeg。这个工具只做一件事：把设备给的每一帧都交出去。
// 编码仍然是 ffmpeg 的活，经命名管道读原始 PCM——管道里的时间戳由样本数决定，
// 天然连续，不会有洞。
//
// ## 实时线程里不做 I/O
//
// CoreAudio 的 IOProc 跑在实时线程上，在里面 write() 会阻塞——ffmpeg 编码稍一卡，
// 实时线程就被拖住，设备过载，又回到丢样本。所以 IOProc 只往环形缓冲里拷，
// 另一个线程负责写 stdout。缓冲给 10 秒的余量；真溢出了**打印出来**，绝不静默。
//
// ## 设备没了要退出，不要挂着
//
// 拔掉 USB 麦克风、蓝牙耳机断连，IOProc 就不再被调用。不处理的话这个进程会一直
// 挂着、ffmpeg 一直等数据、文件停止增长，却没有任何报错。所以监听设备存活，
// 设备一消失就报错退出——管道关闭，ffmpeg 收到 EOF 正常收尾，前面录的都保住。

// ## --system：不改输出设备也能录电脑声音（2026-10-13）
//
// 原来录系统声音靠「录音直通」：建一个 BlackHole + 当前耳机/喇叭的多输出设备，设成系统输出，
// 再从 BlackHole 读。它的命门是**系统输出必须一直是那个设备**。2026-10-13 戴着 AirPods 开录，
// 6.5 秒后 AirPods 的「自动切换」把 Mac 的输出直接改成了耳机（系统日志：Tipi device hijack →
// Route changed from Speaker to Bluetooth），BlackHole 从此收不到东西，47 分钟全是数字静音；
// 2026-09-26 那次也是戴上蓝牙耳机就断。
//
// macOS 14.2 起有系统音频接口（Core Audio tap）：直接抄所有程序放出来的声音，**不管声音最后
// 去了哪个设备**，也不用动系统输出——AirPods 怎么切、音量键照常用。这里建一个抄全局的立体声
// tap，挂在一个私有聚合设备上读。聚合设备的时钟借内建扬声器（只有输出、永远在）；耳机连上
// 断开都不影响它。tap 和聚合设备都是私有的，进程一退就没了，不会留在系统里。
//
// 没授权时 tap 交出来的是全零——和「这会儿没放声音」分不出来。授权怎么要、记在谁头上，见下面
// 「权限：自己负责」一节；rex 还要先用 `rex check sys` 放一声测试音确认收得到，才把它当默认。
//
// **tap 只在有人写的时候才转。**2026-10-13 实测：聚合设备建好、IOProc 也起了，可只要电脑里没有任何程序
// 在放声音，它一帧都不交（coreaudiod 日志：Starting tap after waiting for writers）。开录时对方还没说话，
// ffmpeg 等不到这一路，rex 判「没能开始采集」；就算开起来了，第一声响之前这一路根本不存在，两路的
// 时间轴对不齐。放一段静音它就持续出数据（安静时是全零）。所以 tap 开着的时候，这里自己往**内建扬声器**
// 写静音（startKeepAlive）：听不见、不碰系统默认输出（AirPods 该怎么切还怎么切、音量键照常），只是让
// coreaudiod 认为有人在写。没有内建扬声器的机器退而写到默认输出设备。

import AVFoundation   // 只用来问麦克风权限（公开 API）
import CoreAudio
import Darwin
import Foundation

func errln(_ s: String) { FileHandle.standardError.write((s + "\n").data(using: .utf8)!) }

// 输出语言：rex.sh 导出 REX_LANG（en / zh）；单独跑时看 ~/.config/rex/lang，再看系统首选语言（中文 → zh，其余 → en）
let EN: Bool = {
    let env = ProcessInfo.processInfo.environment["REX_LANG"] ?? ""
    if env == "en" || env == "zh" { return env == "en" }
    if let f = try? String(contentsOfFile: NSHomeDirectory() + "/.config/rex/lang", encoding: .utf8) {
        let v = f.trimmingCharacters(in: .whitespacesAndNewlines)
        if v == "en" || v == "zh" { return v == "en" }
    }
    return !(Locale.preferredLanguages.first ?? "en").hasPrefix("zh")
}()
func L(_ zh: String, _ en: String) -> String { EN ? en : zh }

// ---------------------------------------------------------------- 权限：自己负责
//
// macOS 的隐私授权（TCC）记在「负责的那个 App」头上：从终端起的命令行程序，负责人是终端。
// 2026-10-13 从 Ghostty 跑 rex check sys，tccd 把请求算在了 Ghostty 头上（系统日志：
// AUTHREQ_SUBJECT subject=com.mitchellh.ghostty），而 Ghostty 的 Info.plist 没申报
// NSAudioCaptureUsageDescription——没有用途说明的 App，系统**不弹授权框**，只回一个「没问过」
// （AUTHREQ_RESULT authValue=1），coreaudiod 于是让 tap 静静地交全零。麦克风那一路是同一个坑，
// 只不过 Ghostty 碰巧申报了麦克风用途、用户早就点过允许，所以一直没露出来；换个终端就会露。
//
// 所以 audiocap 一启动先用 posix_spawn + responsibility_spawnattrs_setdisclaim 把自己重新起一遍：
// 子进程「自己对自己负责」，授权记在 audiocap 头上，程序名和用途说明从链接进二进制的 Info.plist
// （tools/audiocap-Info.plist，-sectcreate __TEXT __info_plist）里读。于是：
//   - 从哪个终端、从录音台网页、从 launchd 起都一样，授权一次就够；
//   - 系统设置的「麦克风」和「屏幕与系统录音 → 仅系统录音」里出现的是「rex 录音采集」，不是终端。
// 父进程只做一件事：等子进程、把 SIGINT/SIGTERM 转给它、按它的退出码退出。stdout（命名管道）、
// stderr、电平文件都由子进程直接写；rex.sh 记的 PID 是父进程，kill 它等于 kill 子进程；子进程
// 发现父进程没了也自己退，不留孤儿。
//
// 代价：二进制是 ad-hoc 签名的，重编一次 cdhash 就变，TCC 认不出是同一个程序，要重新授权一次。
// 所以不是「允许了就永远有」——rex check mic / rex check sys 会把这事当场说出来，rex start 在
// 麦克风没授权时弹框等你点，系统声音没授权时退回 BlackHole 那条路并告诉你。
let relayEnvKey = "REX_AUDIOCAP_CHILD"
let isRelayChild = ProcessInfo.processInfo.environment[relayEnvKey] != nil
var relayChild: pid_t = 0

func respawnDisclaimed() {
    if isRelayChild { return }
    guard let sym = dlsym(dlopen(nil, RTLD_NOW), "responsibility_spawnattrs_setdisclaim") else { return }
    typealias Disclaim = @convention(c) (UnsafeMutablePointer<posix_spawnattr_t?>, Int32) -> Int32
    var attr: posix_spawnattr_t? = nil
    guard posix_spawnattr_init(&attr) == 0 else { return }
    defer { posix_spawnattr_destroy(&attr) }
    guard unsafeBitCast(sym, to: Disclaim.self)(&attr, 1) == 0 else { return }
    // rex.sh 用 nohup … & 起我们，后台作业的 SIGINT 是「忽略」，posix_spawn 会原样传给子进程——子进程在问权限、建 tap
    // 的那段时间里收到转发的 SIGINT 就直接丢掉了。恢复默认，那段时间里收到就退
    var sigs = sigset_t()
    sigemptyset(&sigs); sigaddset(&sigs, SIGINT); sigaddset(&sigs, SIGTERM)
    posix_spawnattr_setsigdefault(&attr, &sigs)
    posix_spawnattr_setflags(&attr, Int16(POSIX_SPAWN_SETSIGDEF))
    var exe = [CChar](repeating: 0, count: 4096)
    var exeLen = UInt32(exe.count)
    guard _NSGetExecutablePath(&exe, &exeLen) == 0 else { return }
    let argv: [UnsafeMutablePointer<CChar>?] = CommandLine.arguments.map { strdup($0) } + [nil]
    var env = ProcessInfo.processInfo.environment
    env[relayEnvKey] = "1"
    env["REX_AUDIOCAP_PARENT"] = String(getpid())   // 子进程拿它和 getppid() 比：父进程被 kill -9 了也能发现
    let envp: [UnsafeMutablePointer<CChar>?] = env.map { strdup("\($0.key)=\($0.value)") } + [nil]
    var child: pid_t = 0
    let rc = posix_spawn(&child, exe, nil, &attr, argv, envp)
    guard rc == 0 else {
        errln(L("audiocap：没法以自己的名义重起（\(rc)），就在本进程里跑——授权会记在终端头上", "audiocap: couldn\'t relaunch as its own responsible process (\(rc)); running in this process, so permissions go to the terminal")); return
    }
    relayChild = child
    for sig in [SIGINT, SIGTERM] { signal(sig) { s in if relayChild > 0 { kill(relayChild, s) } } }
    var status: Int32 = 0
    while waitpid(child, &status, 0) < 0 { if errno != EINTR { exit(1) } }
    if status & 0x7f == 0 { exit((status >> 8) & 0xff) }
    exit(128 + (status & 0x7f))
}
respawnDisclaimed()

// 麦克风：公开 API。没问过就问（弹系统提示、等答复）；拒绝了就明说，绝不录一段全零出来。
func micAuthorized() -> Bool {
    let fix = L("系统设置 → 隐私与安全性 → 麦克风 → 打开「rex 录音采集」", "System Settings → Privacy & Security → Microphone → turn on \"rex 录音采集\"")
    switch AVCaptureDevice.authorizationStatus(for: .audio) {
    case .authorized: return true
    case .notDetermined:
        errln(L("audiocap：第一次用麦克风，等你在屏幕上的提示里点「允许」……", "audiocap: first use of the microphone; waiting for you to click Allow in the prompt…"))
        let sem = DispatchSemaphore(value: 0)
        var ok = false
        AVCaptureDevice.requestAccess(for: .audio) { ok = $0; sem.signal() }
        if sem.wait(timeout: .now() + 120) == .timedOut {
            errln(L("audiocap：等了两分钟没人点，先不录。再开一次会再问。", "audiocap: no answer after two minutes, not recording. It will ask again next time.")); return false
        }
        if !ok { errln(L("audiocap：麦克风被拒绝了，这一路没法录。\(fix)", "audiocap: microphone access was denied, so this track can\'t be recorded. \(fix)")) }
        return ok
    default:
        errln(L("audiocap：这个程序没有麦克风权限，这一路没法录。\(fix)", "audiocap: this program has no microphone permission, so this track can\'t be recorded. \(fix)")); return false
    }
}

// 系统声音（kTCCServiceAudioCapture）没有公开的「申请授权」API：coreaudiod 建 tap 时只做不弹框的
// 预检，没授权就交全零。用 TCC 框架的私有接口 TCCAccessPreflight / TCCAccessRequest（AudioCap 等
// 工具也是这么做的）：预检拿结果；「没问过」且带 --request 才弹框、等答复。接口没了就放行，靠
// rex check sys 的测试音和录音时的电平兜底。
let sysAudioService = "kTCCServiceAudioCapture" as CFString
func tccSym(_ name: String) -> UnsafeMutableRawPointer? {
    guard let h = dlopen("/System/Library/PrivateFrameworks/TCC.framework/TCC", RTLD_NOW) else { return nil }
    return dlsym(h, name)
}
func sysAudioPreflight() -> Int32 {        // 0 已允许  1 被拒绝  2 还没问过  -1 查不了
    guard let s = tccSym("TCCAccessPreflight") else { return -1 }
    typealias F = @convention(c) (CFString, CFDictionary?) -> Int32
    return unsafeBitCast(s, to: F.self)(sysAudioService, nil)
}
func sysAudioRequest() -> Bool {
    guard let s = tccSym("TCCAccessRequest") else { return false }
    // 回调是 TCC 存起来、用户点了才调的，必须标 @escaping，否则 Swift 当它是非逃逸的，运行时直接报错退出
    typealias F = @convention(c) (CFString, CFDictionary?, @escaping @convention(block) (DarwinBoolean) -> Void) -> Void
    let sem = DispatchSemaphore(value: 0)
    var ok = false
    unsafeBitCast(s, to: F.self)(sysAudioService, nil) { ok = $0.boolValue; sem.signal() }
    return sem.wait(timeout: .now() + 120) == .success && ok
}
func sysAudioAuthorized(request: Bool) -> Bool {
    let fix = L("系统设置 → 隐私与安全性 → 屏幕与系统录音 → 「仅系统录音」→ 打开「rex 录音采集」", "System Settings → Privacy & Security → Screen & System Audio Recording → \"System Audio Recording Only\" → turn on \"rex 录音采集\"")
    var st = sysAudioPreflight()
    if st == 2 && request {
        errln(L("audiocap：第一次录系统声音，等你在屏幕上的提示里点「允许」……", "audiocap: first system-audio recording; waiting for you to click Allow in the prompt…"))
        st = sysAudioRequest() ? 0 : sysAudioPreflight()
    }
    switch st {
    case 0, -1: return true
    case 1: errln(L("audiocap：录系统声音被拒绝过。\(fix)", "audiocap: system audio recording was denied. \(fix)")); return false
    default: errln(L("audiocap：录系统声音还没授权。跑一次 rex check sys 会弹授权提示；或者 \(fix)", "audiocap: system audio recording isn\'t authorized yet. Run rex check sys to get the prompt, or \(fix)")); return false
    }
}

func addr(_ sel: AudioObjectPropertySelector,
          _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: sel, mScope: scope, mElement: kAudioObjectPropertyElementMain)
}

func allDevices() -> [AudioDeviceID] {
    var a = addr(kAudioHardwarePropertyDevices)
    var sz: UInt32 = 0
    AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil, &sz)
    var ids = [AudioDeviceID](repeating: 0, count: Int(sz) / MemoryLayout<AudioDeviceID>.size)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil, &sz, &ids)
    return ids
}

func deviceName(_ d: AudioDeviceID) -> String {
    var a = addr(kAudioObjectPropertyName)
    var n: Unmanaged<CFString>?
    var sz = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    guard AudioObjectGetPropertyData(d, &a, 0, nil, &sz, &n) == noErr, let s = n else { return "?" }
    return s.takeRetainedValue() as String
}

func inputChannels(_ d: AudioDeviceID) -> Int {
    var a = addr(kAudioDevicePropertyStreamConfiguration, kAudioDevicePropertyScopeInput)
    var sz: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(d, &a, 0, nil, &sz) == noErr, sz > 0 else { return 0 }
    let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(sz), alignment: 16)
    defer { raw.deallocate() }
    guard AudioObjectGetPropertyData(d, &a, 0, nil, &sz, raw) == noErr else { return 0 }
    let abl = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
    return abl.reduce(0) { $0 + Int($1.mNumberChannels) }
}

// 输入的缓冲形状：几块、单块最多几个声道（判断是「每块一个声道」还是「一块多声道」）
func inputBufferShape(_ d: AudioDeviceID) -> (buffers: Int, maxCh: Int) {
    var a = addr(kAudioDevicePropertyStreamConfiguration, kAudioDevicePropertyScopeInput)
    var sz: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(d, &a, 0, nil, &sz) == noErr, sz > 0 else { return (0, 0) }
    let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(sz), alignment: 16)
    defer { raw.deallocate() }
    guard AudioObjectGetPropertyData(d, &a, 0, nil, &sz, raw) == noErr else { return (0, 0) }
    let abl = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
    return (abl.count, abl.reduce(0) { max($0, Int($1.mNumberChannels)) })
}

func outputChannels(_ d: AudioDeviceID) -> Int {
    var a = addr(kAudioDevicePropertyStreamConfiguration, kAudioDevicePropertyScopeOutput)
    var sz: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(d, &a, 0, nil, &sz) == noErr, sz > 0 else { return 0 }
    let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(sz), alignment: 16)
    defer { raw.deallocate() }
    guard AudioObjectGetPropertyData(d, &a, 0, nil, &sz, raw) == noErr else { return 0 }
    let abl = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
    return abl.reduce(0) { $0 + Int($1.mNumberChannels) }
}

func deviceUID(_ d: AudioDeviceID) -> String? {
    var a = addr(kAudioDevicePropertyDeviceUID)
    var n: Unmanaged<CFString>?
    var sz = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    guard AudioObjectGetPropertyData(d, &a, 0, nil, &sz, &n) == noErr, let s = n else { return nil }
    return s.takeRetainedValue() as String
}

func transport(_ d: AudioDeviceID) -> UInt32 {
    var a = addr(kAudioDevicePropertyTransportType)
    var t: UInt32 = 0
    var sz = UInt32(MemoryLayout<UInt32>.size)
    AudioObjectGetPropertyData(d, &a, 0, nil, &sz, &t)
    return t
}

// 系统声音那个聚合设备的时钟：内建的、只有输出的设备（MacBook 的扬声器）。它永远在，耳机连上
// 断开、自动切换都不影响；只有输出，聚合设备的输入就只剩 tap 那两路。没有内建扬声器的机器
// （Mac mini）退而用一个只有输出的物理设备；都没有就不挂，只靠 tap。
func clockDeviceUID() -> String? {
    let outs = allDevices().filter { outputChannels($0) > 0 && inputChannels($0) == 0 }
    if let d = outs.first(where: { transport($0) == kAudioDeviceTransportTypeBuiltIn }) { return deviceUID(d) }
    let skip: Set<UInt32> = [kAudioDeviceTransportTypeAggregate, kAudioDeviceTransportTypeVirtual,
                             kAudioDeviceTransportTypeBluetooth, kAudioDeviceTransportTypeBluetoothLE]
    if let d = outs.first(where: { !skip.contains(transport($0)) }) { return deviceUID(d) }
    return nil
}

var tapID = AudioObjectID(kAudioObjectUnknown)
var tapAggID = AudioDeviceID(kAudioObjectUnknown)

// 往一个输出设备写静音，让 tap 一直有「写的人」（见文件头「tap 只在有人写的时候才转」）
var keepAliveDev = AudioDeviceID(kAudioObjectUnknown)
var keepAliveProc: AudioDeviceIOProcID? = nil

func deviceForUID(_ uid: String) -> AudioDeviceID? { allDevices().first { deviceUID($0) == uid } }

func defaultOutputDevice() -> AudioDeviceID? {
    var a = addr(kAudioHardwarePropertyDefaultOutputDevice)
    var d = AudioDeviceID(kAudioObjectUnknown)
    var sz = UInt32(MemoryLayout<AudioDeviceID>.size)
    guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil, &sz, &d) == noErr,
          d != kAudioObjectUnknown else { return nil }
    return d
}

func startKeepAlive(clockUID: String?) -> Bool {
    // 内建扬声器的 UID 在 Mac 上是固定的 BuiltInSpeakerDevice；clockDeviceUID 按「内建、只有输出」挑，插着有线耳机时
    // 可能挑到耳机那个设备，拔掉就没了。所以先按固定 UID 找，再退回时钟设备，再退回默认输出
    guard let d = deviceForUID("BuiltInSpeakerDevice") ?? clockUID.flatMap(deviceForUID) ?? defaultOutputDevice() else {
        errln(L("audiocap：找不到可以写静音的输出设备——没放声音时系统声音这一路会没数据", "audiocap: no output device to write silence to; the system-audio track gets no data while nothing is playing")); return false
    }
    var p: AudioDeviceIOProcID? = nil
    let st = AudioDeviceCreateIOProcIDWithBlock(&p, d, nil) { _, _, _, outData, _ in
        for b in UnsafeMutableAudioBufferListPointer(outData) {
            if let m = b.mData { memset(m, 0, Int(b.mDataByteSize)) }
        }
    }
    guard st == noErr, let proc = p else {
        errln(L("audiocap：往「\(deviceName(d))」写静音没起来（\(st)）——没放声音时系统声音这一路会没数据", "audiocap: couldn\'t start writing silence to \"\(deviceName(d))\" (\(st)); the system-audio track gets no data while nothing is playing")); return false
    }
    guard AudioDeviceStart(d, proc) == noErr else {
        AudioDeviceDestroyIOProcID(d, proc)
        errln(L("audiocap：「\(deviceName(d))」启动不了——没放声音时系统声音这一路会没数据", "audiocap: \"\(deviceName(d))\" won\'t start; the system-audio track gets no data while nothing is playing")); return false
    }
    keepAliveDev = d
    keepAliveProc = proc
    return true
}

func stopKeepAlive() {
    if keepAliveDev != kAudioObjectUnknown, let p = keepAliveProc {
        AudioDeviceStop(keepAliveDev, p)
        AudioDeviceDestroyIOProcID(keepAliveDev, p)
    }
    keepAliveDev = AudioDeviceID(kAudioObjectUnknown)
    keepAliveProc = nil
}

@available(macOS 14.2, *)
func openSystemTap(keepAlive: Bool) -> AudioDeviceID? {
    let desc = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
    desc.uuid = UUID()
    desc.name = "rex 系统声音"
    desc.isPrivate = true
    desc.muteBehavior = .unmuted          // 只抄，不把声音截走：耳机里照常听得到
    var tap = AudioObjectID(kAudioObjectUnknown)
    var err = AudioHardwareCreateProcessTap(desc, &tap)
    guard err == noErr, tap != kAudioObjectUnknown else {
        errln(L("audiocap：建不了系统声音的 tap（\(err)）", "audiocap: couldn\'t create the system audio tap (\(err))")); return nil
    }
    tapID = tap
    var dict: [String: Any] = [
        kAudioAggregateDeviceNameKey: "rex 系统声音",
        kAudioAggregateDeviceUIDKey: "rex.tap." + UUID().uuidString,
        kAudioAggregateDeviceIsPrivateKey: true,
        kAudioAggregateDeviceIsStackedKey: false,
        kAudioAggregateDeviceTapAutoStartKey: true,
        kAudioAggregateDeviceTapListKey: [[kAudioSubTapUIDKey: desc.uuid.uuidString,
                                           kAudioSubTapDriftCompensationKey: true]],
    ]
    let clk = clockDeviceUID()
    if let c = clk {
        dict[kAudioAggregateDeviceMainSubDeviceKey] = c
        dict[kAudioAggregateDeviceSubDeviceListKey] = [[kAudioSubDeviceUIDKey: c]]
    }
    var agg = AudioDeviceID(kAudioObjectUnknown)
    err = AudioHardwareCreateAggregateDevice(dict as CFDictionary, &agg)
    guard err == noErr, agg != kAudioObjectUnknown else {
        AudioHardwareDestroyProcessTap(tap); tapID = AudioObjectID(kAudioObjectUnknown)
        errln(L("audiocap：建不了系统声音的聚合设备（\(err)）", "audiocap: couldn\'t create the aggregate device for system audio (\(err))")); return nil
    }
    tapAggID = agg
    // 写静音是这条路成立的前提（没人写 tap 就不转），起不来就整条路算失败（退出码 11），别留一条「开着却不出数据」的
    if keepAlive && !startKeepAlive(clockUID: clk) {
        closeSystemTap()
        errln(L("audiocap：系统声音这一路没法保持运转，不录了（退出码 11）", "audiocap: can\'t keep the system-audio track running, not recording (exit code 11)")); exit(11)
    }
    return agg
}

func closeSystemTap() {
    stopKeepAlive()
    if tapAggID != kAudioObjectUnknown { AudioHardwareDestroyAggregateDevice(tapAggID) }
    if #available(macOS 14.2, *), tapID != kAudioObjectUnknown { AudioHardwareDestroyProcessTap(tapID) }
    tapAggID = AudioDeviceID(kAudioObjectUnknown); tapID = AudioObjectID(kAudioObjectUnknown)
}

func nominalRate(_ d: AudioDeviceID) -> Double {
    var a = addr(kAudioDevicePropertyNominalSampleRate)
    var r: Float64 = 0
    var sz = UInt32(MemoryLayout<Float64>.size)
    AudioObjectGetPropertyData(d, &a, 0, nil, &sz, &r)
    return r
}

// IOProc 拿到的是输入流的「虚拟格式」，现代设备几乎都是 32 位浮点。
// 不是的话宁可报错退出，也不把字节当浮点数硬写出去——那会是一段听起来像噪声的录音。
func inputIsFloat32(_ d: AudioDeviceID) -> Bool {
    var a = addr(kAudioDevicePropertyStreams, kAudioDevicePropertyScopeInput)
    var sz: UInt32 = 0
    AudioObjectGetPropertyDataSize(d, &a, 0, nil, &sz)
    var streams = [AudioStreamID](repeating: 0, count: Int(sz) / MemoryLayout<AudioStreamID>.size)
    AudioObjectGetPropertyData(d, &a, 0, nil, &sz, &streams)
    guard let st = streams.first else { return false }
    var fa = addr(kAudioStreamPropertyVirtualFormat)
    var f = AudioStreamBasicDescription()
    var fsz = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
    guard AudioObjectGetPropertyData(st, &fa, 0, nil, &fsz, &f) == noErr else { return false }
    return f.mFormatID == kAudioFormatLinearPCM
        && (f.mFormatFlags & kAudioFormatFlagIsFloat) != 0 && f.mBitsPerChannel == 32
}

// 按名字找，必须有输入声道。先认**完整设备名**（不分大小写），再按正则——
// rex.sh 有时传的是 `MacBook.*Microph` 这样的模式，有时传的是 audiodev 报的
// 默认输入设备的全名；后者要是带了 `USB Audio (2)` 这样的括号，按正则就成了
// 分组，反而匹配不上它自己。
func findInput(_ pattern: String) -> AudioDeviceID? {
    let inputs = allDevices().filter { inputChannels($0) > 0 }
    if let d = inputs.first(where: { deviceName($0).lowercased() == pattern.lowercased() }) { return d }
    if let re = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]),
       let d = inputs.first(where: {
           let n = deviceName($0)
           return re.firstMatch(in: n, range: NSRange(n.startIndex..., in: n)) != nil }) { return d }
    return inputs.first { deviceName($0).lowercased().contains(pattern.lowercased()) }
}

// ---------------------------------------------------------------- 参数

var args = Array(CommandLine.arguments.dropFirst())
if args.first == "--list" {
    for d in allDevices() where inputChannels(d) > 0 {
        print(String(format: "%6.0f Hz  %d ch  %@", nominalRate(d), inputChannels(d), deviceName(d)))
    }
    exit(0)
}
let systemMode = args.first == "--system"
guard systemMode || (args.first.map { !$0.hasPrefix("--") } ?? false) else {
    errln(L("用法：audiocap <设备名（正则）>|--system [--info] [--seconds N] [--level 文件] [--request]", "usage: audiocap <device name (regex)>|--system [--info] [--seconds N] [--level FILE] [--request]")); exit(64)
}
let pattern = args[0]
let infoOnly = args.contains("--info")
var limit: Double = 0
if let i = args.firstIndex(of: "--seconds"), i + 1 < args.count { limit = Double(args[i + 1]) ?? 0 }
var levelPath: String? = nil
if let i = args.firstIndex(of: "--level"), i + 1 < args.count { levelPath = args[i + 1] }

// 退出码：8 麦克风没权限、9 系统声音没权限——rex.sh 据此决定是弹框等、还是退回别的路
var picked: AudioDeviceID? = nil
if systemMode {
    guard #available(macOS 14.2, *) else { errln(L("audiocap：--system 要 macOS 14.2 以上", "audiocap: --system needs macOS 14.2 or later")); exit(6) }
    if !sysAudioAuthorized(request: args.contains("--request")) { exit(9) }
    picked = openSystemTap(keepAlive: !infoOnly)
    if picked == nil { exit(7) }
} else {
    if !micAuthorized() { exit(8) }
    picked = findInput(pattern)
}
guard let dev = picked else {
    errln(L("audiocap：找不到能录音的设备「\(pattern)」。audiocap --list 看看有哪些。", "audiocap: no input device matching \"\(pattern)\". Run audiocap --list to see what is available.")); exit(2)
}
let rate = nominalRate(dev)
let ch = inputChannels(dev)
let devLabel = systemMode ? L("系统声音（系统音频接口）", "System audio (system audio tap)") : deviceName(dev)
// 校验放在 --info 的输出之前：「探测通过」必须等于「采集能起来」，不然 rex.sh 会把 "48000 0 …" 交给 ffmpeg
guard ch > 0, rate > 0 else {
    errln(L("audiocap：「\(devLabel)」没有可读的输入（\(ch) 声道、\(rate) Hz）", "audiocap: \"\(devLabel)\" has no readable input (\(ch) channels, \(rate) Hz)")); closeSystemTap(); exit(3)
}
guard inputIsFloat32(dev) else {
    errln(L("audiocap：「\(devLabel)」的输入不是 32 位浮点，这个工具不处理，免得写出一段噪声。", "audiocap: \"\(devLabel)\" does not deliver 32-bit float; not supported (it would write noise).")); closeSystemTap(); exit(3)
}
// 多个 stream、其中又有多声道的 stream：下面拼交错的那段只会按「一块一个声道」拼，拼出来是错位的。少见（自建聚合、
// 某些多 stream 声卡），直接拒绝，比写出一段错位的录音好
let shape = inputBufferShape(dev)
guard shape.buffers <= 1 || shape.maxCh <= 1 else {
    errln(L("audiocap：「\(devLabel)」有 \(shape.buffers) 个输入 stream 且其中有多声道的，这个工具不处理这种设备", "audiocap: \"\(devLabel)\" has \(shape.buffers) input streams, some multichannel; this kind of device is not supported")); closeSystemTap(); exit(3)
}
if infoOnly { print(String(format: "%.0f %d %@", rate, ch, devLabel)); closeSystemTap(); exit(0) }

// ---------------------------------------------------------------- 环形缓冲

// 10 秒余量。IOProc 往里写，写线程往外取；两边只在这把锁上碰一下。
let capacity = Int(rate) * ch * 10
let ring = UnsafeMutablePointer<Float>.allocate(capacity: capacity)
var rHead = 0, wHead = 0, filled = 0
var overrun = 0          // 因为缓冲满了没存进去的帧数：写进电平文件，退出时也报
var delivered: UInt64 = 0
var firstFrameT: Double = 0   // 第一帧到达的墙钟时刻（电平文件里的 t0：两路对齐时能量出相差多少）
var lastFrameT: Double = 0    // 最近一帧到达的墙钟时刻（电平文件里的 last_frame_t：帧不来了，文件还在刷也得看出来）
var lock = os_unfair_lock()
var winPeak: Float = 0   // 上次报电平以来的峰值（绝对值），--level 用

// 非交错输入（每个声道一块缓冲）、声道数中途变了的输入，先在这里排成开录时的 ch 声道交错。
// 按最大 IO 块预分配，实时线程里不分配内存。
let scratch = UnsafeMutablePointer<Float>.allocate(capacity: 16384 * max(ch, 1))
let silence = UnsafeMutablePointer<Float>.allocate(capacity: 16384 * max(ch, 1))   // 补停顿用的静音
silence.initialize(repeating: 0, count: 16384 * max(ch, 1))
var srcChNow = ch        // 设备眼下交来的声道数（锁里改、锁里读）
var fmtChanges = 0       // 录的过程中声道数变了几次：写进电平文件，rex stop 的报告里提一句

func push(_ src: UnsafePointer<Float>, _ nFloats: Int, _ srcCh: Int) {
    let now = Date().timeIntervalSince1970
    var pk: Float = 0
    for i in 0..<nFloats { let v = abs(src[i]); if v > pk { pk = v } }
    os_unfair_lock_lock(&lock)
    if srcCh != srcChNow { srcChNow = srcCh; fmtChanges += 1 }
    if pk > winPeak { winPeak = pk }        // 溢出丢掉的那段峰值也算：不然下游写得慢会被报成「麦克风没信号」
    lastFrameT = now
    if firstFrameT == 0 { firstFrameT = now }
    if filled + nFloats > capacity {
        overrun += nFloats / max(ch, 1)
        os_unfair_lock_unlock(&lock)
        return
    }
    var n = nFloats, s = src
    while n > 0 {
        let k = min(n, capacity - wHead)
        (ring + wHead).update(from: s, count: k)
        wHead = (wHead + k) % capacity
        s += k; n -= k
    }
    filled += nFloats
    delivered += UInt64(nFloats / max(ch, 1))
    os_unfair_lock_unlock(&lock)
}

func pop(_ dst: UnsafeMutablePointer<Float>, _ maxFloats: Int) -> Int {
    os_unfair_lock_lock(&lock)
    let n = min(filled, maxFloats)
    var left = n, d = dst
    while left > 0 {
        let k = min(left, capacity - rHead)
        d.update(from: ring + rHead, count: k)
        rHead = (rHead + k) % capacity
        d += k; left -= k
    }
    filled -= n
    os_unfair_lock_unlock(&lock)
    return n
}

// ---------------------------------------------------------------- 采集

// ingest: begin —— tests/test_audiocap_ingest.py 把这一段原样抽出来编进测试程序：它用到的 ch、scratch、push、lock、
// overrun 留在外面，别挪进来
//
// 声道数中途变了：别的程序打开这个麦克风时会把它切成另一种格式。2026-10-17 一边开微信视频一边录「我 + 对方」，
// 内置麦克风在通话打开它时从 1 声道变成 3 声道（挂断又变回 1），ffmpeg 还按开录时的 1 声道读，只读得动三分之一，
// 其余全丢，那一路从第 3 分钟起成了乱的。所以交给下游的永远是开录时的 ch 声道：
// 目标是单声道就把所有声道取平均；否则第 c 路取第 c 个声道，少了复制最后一个。
@inline(__always)
func remix(_ frames: Int, _ src: Int, _ dstCh: Int, _ dst: UnsafeMutablePointer<Float>,
           _ sample: (Int, Int) -> Float) {
    if dstCh == 1 {
        let scale = 1 / Float(max(src, 1))
        for i in 0..<frames {
            var s: Float = 0
            for k in 0..<src { s += sample(k, i) }
            dst[i] = s * scale
        }
    } else {
        for i in 0..<frames {
            for c in 0..<dstCh { dst[i * dstCh + c] = sample(min(c, src - 1), i) }
        }
    }
}

// 设备换格式的那一下会停顿：2026-10-17 实测每次约 0.25 秒一个采样都不交（10 秒里切两次只交出 9.5 秒）。不补的话
// 这一路从那以后比另一路提前，合并对话稿时判回声只留 0.3 秒余量，提前半秒对方的话就会被当成「我」又出现一遍。
// 所以按系统给每个 IO 块打的时间戳，比相邻两块：这一块比上一块结束晚了 0.05~5 秒，就先补同样长的静音。
// 只比相邻两块、不累计，长时间录音的时钟漂移不会误触发；超过 5 秒多半是电脑睡了，两路一起停，不用补
var lastInT: Double = -1         // 上一块第一帧的时刻（秒）
var lastInFrames = 0             // 上一块的帧数
var gapFrames = 0                // 补过的静音帧数（锁里改、锁里读）
let hostTick: Double = {
    var tb = mach_timebase_info_data_t()
    mach_timebase_info(&tb)
    return Double(tb.numer) / Double(tb.denom) / 1e9
}()

// 一个 IO 块进来。交错的、声道数和开录时一样的直接存；别的（非交错、声道数变了）先排成 ch 声道交错再存。
// 实时线程：不分配内存、不打印（声道数变了、补了停顿，都由看门狗那边报）
func ingest(_ abl: UnsafeMutableAudioBufferListPointer, _ ts: UnsafePointer<AudioTimeStamp>?) {
    guard abl.count > 0 else { return }
    var src = 0
    for b in abl { src += max(Int(b.mNumberChannels), 1) }
    let frames = Int(abl[0].mDataByteSize) / (4 * max(Int(abl[0].mNumberChannels), 1))
    guard frames > 0 else { return }
    if let ts = ts, ts.pointee.mFlags.contains(.hostTimeValid) {
        let t = Double(ts.pointee.mHostTime) * hostTick
        if lastInT >= 0 {
            let gap = t - (lastInT + Double(lastInFrames) / rate)
            if gap > 0.05 && gap < 5 {
                var left = Int(gap * rate)
                os_unfair_lock_lock(&lock); gapFrames += left; os_unfair_lock_unlock(&lock)
                while left > 0 {
                    let k = min(left, 16384)
                    push(silence, k * ch, src)
                    left -= k
                }
            }
        }
        lastInT = t; lastInFrames = frames
    }
    if abl.count == 1 && src == ch {
        guard let p = abl[0].mData else { return }
        push(p.assumingMemoryBound(to: Float.self), frames * ch, src)
        return
    }
    guard frames <= 16384 else {           // 超过预分配的拼接缓冲：丢，但要计数，别悄悄丢
        os_unfair_lock_lock(&lock); overrun += frames; os_unfair_lock_unlock(&lock); return
    }
    remix(frames, src, ch, scratch) { k, i in
        var k = k
        for b in abl {
            let n = max(Int(b.mNumberChannels), 1)
            if k < n { return b.mData.map { $0.assumingMemoryBound(to: Float.self)[i * n + k] } ?? 0 }
            k -= n
        }
        return 0
    }
    push(scratch, frames * ch, src)
}
// ingest: end

var procID: AudioDeviceIOProcID?
let st = AudioDeviceCreateIOProcIDWithBlock(&procID, dev, nil) { _, inData, inTime, _, _ in
    ingest(UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inData)), inTime)
}
guard st == noErr, let pid = procID else { errln(L("audiocap：建不了 IOProc（\(st)）", "audiocap: couldn\'t create the IOProc (\(st))")); exit(4) }

signal(SIGPIPE, SIG_IGN)
var stopping = false
var pipeBroken = false
var deviceGone = false
let finished = DispatchSemaphore(value: 0)

// 写线程：把缓冲里的东西搬到 stdout。stdout 被关（ffmpeg 退出了，比如到了时长上限）
// 就收工——那不是错误，是下游说够了。
let writer = Thread {
    let chunk = 8192 * max(ch, 1)
    let out = UnsafeMutablePointer<Float>.allocate(capacity: chunk)
    while true {
        let n = pop(out, chunk)
        if n > 0 {
            let bytes = n * 4
            var off = 0
            while off < bytes {
                let r = write(1, UnsafeRawPointer(out).advanced(by: off), bytes - off)
                if r < 0 { if errno == EINTR { continue }; pipeBroken = true; break }
                off += r
            }
            if pipeBroken { break }
        } else {
            if stopping { break }
            usleep(5000)
        }
    }
    finished.signal()
}
writer.qualityOfService = .userInitiated

// 设备消失：拔了 USB、蓝牙断连。读「还活着吗」读不出来也算没了（SDL 的 CoreAudio 后端同样把 BadDevice 当拔出）
var shuttingDown = false
var aliveAddr = addr(kAudioDevicePropertyDeviceIsAlive)
let aliveSt = AudioObjectAddPropertyListenerBlock(dev, &aliveAddr, DispatchQueue.global()) { _, _ in
    if shuttingDown { return }                 // 自己在拆聚合设备，别把这当成「设备断开了」
    var alive: UInt32 = 1
    var sz = UInt32(MemoryLayout<UInt32>.size)
    var a = addr(kAudioDevicePropertyDeviceIsAlive)
    let st = AudioObjectGetPropertyData(dev, &a, 0, nil, &sz, &alive)
    if st != noErr || alive == 0 {
        deviceGone = true
        errln(L("audiocap：设备「\(deviceName(dev))」断开了，停止采集（已录的部分会正常保存）", "audiocap: device \"\(deviceName(dev))\" disconnected, stopping capture (what was recorded is saved)"))
        kill(getpid(), SIGTERM)
    }
}
if aliveSt != noErr { errln(L("audiocap：装不上设备存活监听（\(aliveSt)），设备断开只能靠帧数看门狗发现", "audiocap: couldn\'t install the device-alive listener (\(aliveSt)); a disconnect will only be caught by the frame watchdog")) }
// 写静音那台设备没了（只在退回默认输出时可能发生）：tap 跟着停转，这一路没意义了，退出让另一路接着录
if keepAliveDev != kAudioObjectUnknown {
    var ka = addr(kAudioDevicePropertyDeviceIsAlive)
    AudioObjectAddPropertyListenerBlock(keepAliveDev, &ka, DispatchQueue.global()) { _, _ in
        if shuttingDown { return }
        var alive: UInt32 = 1
        var sz = UInt32(MemoryLayout<UInt32>.size)
        var a = addr(kAudioDevicePropertyDeviceIsAlive)
        if AudioObjectGetPropertyData(keepAliveDev, &a, 0, nil, &sz, &alive) != noErr || alive == 0 {
            errln(L("audiocap：写静音的输出设备没了，系统声音这一路停止（退出码 11）", "audiocap: the output device used for silence is gone, stopping the system-audio track (exit code 11)"))
            DispatchQueue.main.async { shutdown(11) }
        }
    }
}
// 采样率中途变了（别的程序改了设备设置）：ffmpeg 还按开录时的 -ar 解释，后半段会变速。退出（码 12），别写错的
var rateAddr = addr(kAudioDevicePropertyNominalSampleRate)
AudioObjectAddPropertyListenerBlock(dev, &rateAddr, DispatchQueue.global()) { _, _ in
    if shuttingDown { return }
    let r2 = nominalRate(dev)
    if r2 > 0 && abs(r2 - rate) > 0.5 {
        errln(String(format: L("audiocap：「%@」的采样率从 %.0f 变成了 %.0f，这一路停止（退出码 12）", "audiocap: \"%@\" sample rate changed from %.0f to %.0f, stopping this track (exit code 12)"), devLabel, rate, r2))
        DispatchQueue.main.async { shutdown(12) }
    }
}

func shutdown(_ code: Int32) -> Never {
    shuttingDown = true
    AudioDeviceStop(dev, pid)
    AudioDeviceDestroyIOProcID(dev, pid)
    closeSystemTap()
    stopping = true
    _ = finished.wait(timeout: .now() + 10)   // 把缓冲里剩下的写完
    if overrun > 0 {
        errln(String(format: L("audiocap：⚠ 缓冲溢出，丢了 %d 帧（%.2f 秒）——下游写得太慢", "audiocap: ⚠ buffer overrun, dropped %d frames (%.2f s); the consumer is too slow"), overrun, Double(overrun) / rate))
    }
    exit(code)
}

var signalSources: [DispatchSourceSignal] = []
for sig in [SIGINT, SIGTERM] {
    signal(sig, SIG_IGN)
    let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    src.setEventHandler { shutdown(deviceGone ? 2 : 0) }
    src.resume()
    signalSources.append(src)
}

guard AudioDeviceStart(dev, pid) == noErr else { errln(L("audiocap：设备启动失败", "audiocap: failed to start the device")); closeSystemTap(); exit(5) }
errln(String(format: L("audiocap：在读「%@」%.0f Hz %d 声道", "audiocap: reading \"%@\" %.0f Hz %d ch"), devLabel, rate, ch))
writer.start()

// 帧数看门狗：开头 6 秒内一帧都没来（蓝牙麦克风切免提模式要一两秒，留足），或者中途 4 秒没有新帧（设备停转、
// tap 没人写、coreaudiod 重启），都报出来退出（退出码 10）。管道一关，ffmpeg 的 amix 带着另一路接着录；
// 不退的话另一路的写端会被这路堵住，10 秒后缓冲溢出开始丢帧（2026-10-13 复核实测）
var wdLast: UInt64 = 0
var wdSince = DispatchTime.now()
let wd = DispatchSource.makeTimerSource(queue: .main)
wd.schedule(deadline: .now() + 1, repeating: 1)
var srcChSaid = ch
var gapSaid = 0
wd.setEventHandler {
    os_unfair_lock_lock(&lock)
    let got = delivered, sc = srcChNow, gf = gapFrames
    os_unfair_lock_unlock(&lock)
    if gf != gapSaid {
        errln(String(format: L("audiocap：「%@」停顿了 %.2f 秒（换格式时会这样），补上了同样长的静音，和另一路照样对得齐",
                               "audiocap: \"%@\" paused for %.2f s (this happens when its format changes); filled the same length with silence so it stays aligned with the other track"),
                     devLabel, Double(gf - gapSaid) / rate))
        gapSaid = gf
    }
    if sc != srcChSaid {                   // 声道数变了：ingest 已经对齐了，这里说一声（实时线程里不能打印）
        srcChSaid = sc
        errln(String(format: L("audiocap：「%@」现在交来 %d 声道（多半是别的程序打开了它，比如视频通话），照旧按开录时的 %d 声道交出去，这一路接着录",
                               "audiocap: \"%@\" now delivers %d channels (most likely another program opened it, such as a video call); still handing over the %d channels it started with, so this track keeps recording"),
                     devLabel, sc, ch))
    }
    if got != wdLast { wdLast = got; wdSince = DispatchTime.now(); return }
    let quiet = Double(DispatchTime.now().uptimeNanoseconds - wdSince.uptimeNanoseconds) / 1e9
    if (got == 0 && quiet >= 6) || (got > 0 && quiet >= 4) {
        errln(got == 0 ? L("audiocap：「\(devLabel)」启动了，但 6 秒内一帧都没交出来——这一路起不来", "audiocap: \"\(devLabel)\" started but delivered no frames within 6 s; this track can\'t start")
                       : L("audiocap：「\(devLabel)」\(Int(quiet)) 秒没有新帧，这一路停转了，停止采集", "audiocap: \"\(devLabel)\" delivered no new frames for \(Int(quiet)) s; the track has stalled, stopping capture"))
        shutdown(10)
    }
}
wd.resume()

// 每半秒把电平写进 --level 指的文件（先写临时文件再改名，读的一方不会读到半截）：
// {"db": 峰值 dBFS, "zero_since": 从哪一刻起一直是数字零（0 = 现在有声音）, "t": 现在, "frames": 收到的帧数,
//  "overrun": 缓冲满了丢掉的帧数, "ch": 交给下游的声道数, "src_ch": 设备眼下交来的声道数, "fmt_changes": 中途变了几次,
//  "gap_s": 设备停顿、补上的静音一共几秒}
// 数字零和「安静」是两回事：真麦克风再安静也有底噪，全零只可能是没接上。
var levelTimer: DispatchSourceTimer? = nil
if let lp = levelPath {
    var zeroSince: Double = 0
    let t = DispatchSource.makeTimerSource(queue: DispatchQueue.global(qos: .utility))
    t.schedule(deadline: .now() + 0.5, repeating: 0.5)
    t.setEventHandler {
        os_unfair_lock_lock(&lock)
        let pk = winPeak; winPeak = 0; let fr = delivered
        let lft = lastFrameT, t0 = firstFrameT, ov = overrun, sc = srcChNow, fc = fmtChanges, gf = gapFrames
        os_unfair_lock_unlock(&lock)
        let now = Date().timeIntervalSince1970
        if pk == 0 { if zeroSince == 0 { zeroSince = now } } else { zeroSince = 0 }
        let db = pk > 0 ? 20 * log10(Double(pk)) : -120
        let line = String(format: "{\"db\": %.1f, \"zero_since\": %.0f, \"t\": %.0f, \"frames\": %llu, "
                          + "\"last_frame_t\": %.0f, \"t0\": %.3f, \"overrun\": %d, \"ch\": %d, \"src_ch\": %d, \"fmt_changes\": %d, \"gap_s\": %.2f}\n",
                          db, zeroSince, now, fr, lft, t0, ov, ch, sc, fc, Double(gf) / rate)
        let tmp = lp + ".tmp"
        if FileManager.default.createFile(atPath: tmp, contents: line.data(using: .utf8)) { rename(tmp, lp) }
    }
    t.resume()
    levelTimer = t
}

// 下游关管道 → 写线程收工 → 这里跟着退出。作为子进程跑时（见「权限：自己负责」）父进程没了也退，
// 不留一个没人管的采集进程往管道里灌
let parentAtStart = pid_t(ProcessInfo.processInfo.environment["REX_AUDIOCAP_PARENT"] ?? "") ?? getppid()
DispatchQueue.global().async {
    while !pipeBroken {
        if isRelayChild && getppid() != parentAtStart { errln(L("audiocap：父进程没了，停止采集", "audiocap: parent process is gone, stopping capture")); break }
        usleep(50000)
    }
    DispatchQueue.main.async { shutdown(0) }
}
if limit > 0 {
    DispatchQueue.main.asyncAfter(deadline: .now() + limit) { shutdown(0) }
}
dispatchMain()
