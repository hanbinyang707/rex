// audiodev —— rex.sh 的小帮手：查/切输出设备，按需现建一个「多输出设备」。
//
//   audiodev list                          列出所有输出设备：UID / 传输方式 / 名字
//   audiodev list-in                       列出所有输入设备
//   audiodev default                       当前默认输出设备的 UID
//   audiodev default-in                    当前默认输入设备的名字（麦克风）
//   audiodev use <uid>                     切到某个输出设备
//   audiodev members <uid>                 如果它是聚合设备，列出成员的 UID
//   audiodev make <名字> <主时钟uid> <uid...>  现建一个多输出设备，打印它的 UID
//   audiodev destroy <uid>                 删掉
//
// 为什么要这个东西：录系统声音得让声音同时进 BlackHole 和你的耳机。
// 「音频 MIDI 设置」里手建的那个 Multi-Output Device 是**写死成员**的——
// 当初为台式喇叭建的，你戴上蓝牙耳机之后切过去，声音会从笔记本喇叭出来。
// 所以这里改成按「你此刻正在用的输出设备 + BlackHole」现建一个，用完删掉。
//
// 主时钟固定选 BlackHole：蓝牙当主时钟会把它自己的抖动写进录音，非主时钟的成员一律开漂移校正。
//
// 编译（rex.sh 会自动做，源文件比二进制新就重编）：
//   swiftc -O -o audiodev audiodev.swift

import CoreAudio
import Foundation

let SYS = AudioObjectID(kAudioObjectSystemObject)

func addr(_ sel: AudioObjectPropertySelector,
          _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal)
    -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: sel, mScope: scope,
                               mElement: kAudioObjectPropertyElementMain)
}

func cfString(_ id: AudioObjectID, _ sel: AudioObjectPropertySelector) -> String? {
    var a = addr(sel)
    var size = UInt32(MemoryLayout<CFString?>.size)
    var out: CFString?
    let st = withUnsafeMutablePointer(to: &out) {
        AudioObjectGetPropertyData(id, &a, 0, nil, &size, $0)
    }
    guard st == noErr, let s = out else { return nil }
    return s as String
}

func uint32Prop(_ id: AudioObjectID, _ sel: AudioObjectPropertySelector) -> UInt32? {
    var a = addr(sel)
    var size = UInt32(MemoryLayout<UInt32>.size)
    var v: UInt32 = 0
    guard AudioObjectGetPropertyData(id, &a, 0, nil, &size, &v) == noErr else { return nil }
    return v
}

func allDevices() -> [AudioObjectID] {
    var a = addr(kAudioHardwarePropertyDevices)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(SYS, &a, 0, nil, &size) == noErr else { return [] }
    var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(SYS, &a, 0, nil, &size, &ids) == noErr else { return [] }
    return ids
}

/// 某个方向上有没有通道。只按名字猜会把「BlackHole 既是输入又是输出」这类设备搞错。
func hasChannels(_ id: AudioObjectID, _ scope: AudioObjectPropertyScope) -> Bool {
    var a = addr(kAudioDevicePropertyStreamConfiguration, scope)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(id, &a, 0, nil, &size) == noErr, size > 0 else { return false }
    let buf = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: 16)
    defer { buf.deallocate() }
    guard AudioObjectGetPropertyData(id, &a, 0, nil, &size, buf) == noErr else { return false }
    for b in UnsafeMutableAudioBufferListPointer(buf.assumingMemoryBound(to: AudioBufferList.self)) {
        if b.mNumberChannels > 0 { return true }
    }
    return false
}

func hasOutput(_ id: AudioObjectID) -> Bool { hasChannels(id, kAudioObjectPropertyScopeOutput) }
func hasInput(_ id: AudioObjectID) -> Bool { hasChannels(id, kAudioObjectPropertyScopeInput) }

func transport(_ id: AudioObjectID) -> String {
    switch uint32Prop(id, kAudioDevicePropertyTransportType) {
    case kAudioDeviceTransportTypeBuiltIn?:    return "builtin"
    case kAudioDeviceTransportTypeBluetooth?,
         kAudioDeviceTransportTypeBluetoothLE?: return "bluetooth"
    case kAudioDeviceTransportTypeUSB?:        return "usb"
    case kAudioDeviceTransportTypeVirtual?:    return "virtual"
    case kAudioDeviceTransportTypeAggregate?:  return "aggregate"
    case kAudioDeviceTransportTypeHDMI?:       return "hdmi"
    case kAudioDeviceTransportTypeAirPlay?:    return "airplay"
    default:                                   return "other"
    }
}

func deviceID(uid: String) -> AudioObjectID? {
    var a = addr(kAudioHardwarePropertyTranslateUIDToDevice)
    var cf = uid as CFString
    var out: AudioObjectID = 0
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    let st = withUnsafeMutablePointer(to: &cf) { p -> OSStatus in
        AudioObjectGetPropertyData(SYS, &a, UInt32(MemoryLayout<CFString>.size), p, &size, &out)
    }
    guard st == noErr, out != 0 else { return nil }
    return out
}

func members(_ id: AudioObjectID) -> [String] {
    var a = addr(kAudioAggregateDevicePropertyFullSubDeviceList)
    var size = UInt32(MemoryLayout<CFArray?>.size)
    var out: CFArray?
    let st = withUnsafeMutablePointer(to: &out) {
        AudioObjectGetPropertyData(id, &a, 0, nil, &size, $0)
    }
    guard st == noErr, let arr = out as? [String] else { return [] }
    return arr
}

func defaultDevice(_ sel: AudioObjectPropertySelector) -> AudioObjectID? {
    var a = addr(sel)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    var v: AudioObjectID = 0
    guard AudioObjectGetPropertyData(SYS, &a, 0, nil, &size, &v) == noErr else { return nil }
    return v
}

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write(("audiodev: " + msg + "\n").data(using: .utf8)!)
    exit(1)
}

// ------------------------------------------------------------------ 入口

let argv = Array(CommandLine.arguments.dropFirst())
guard let cmd = argv.first else { fail("要一个子命令：list / default / use / members / make / destroy") }
let rest = Array(argv.dropFirst())

switch cmd {

case "list":
    for id in allDevices() where hasOutput(id) {
        let u = cfString(id, kAudioDevicePropertyDeviceUID) ?? "?"
        let n = cfString(id, kAudioObjectPropertyName) ?? "?"
        print("\(u)\t\(transport(id))\t\(n)")
    }

case "list-in":
    for id in allDevices() where hasInput(id) {
        let u = cfString(id, kAudioDevicePropertyDeviceUID) ?? "?"
        let n = cfString(id, kAudioObjectPropertyName) ?? "?"
        print("\(u)\t\(transport(id))\t\(n)")
    }

case "default":
    guard let id = defaultDevice(kAudioHardwarePropertyDefaultOutputDevice),
          let u = cfString(id, kAudioDevicePropertyDeviceUID)
    else { fail("读不到当前输出设备") }
    print(u)

case "default-in":
    // 打印**名字**不是 UID：调用方要拿它去 avfoundation 的设备表里按名字匹配。
    guard let id = defaultDevice(kAudioHardwarePropertyDefaultInputDevice),
          let n = cfString(id, kAudioObjectPropertyName)
    else { fail("读不到当前输入设备") }
    print(n)

case "name":
    guard let u = rest.first, let id = deviceID(uid: u) else { fail("没有这个 UID") }
    print(cfString(id, kAudioObjectPropertyName) ?? "?")

case "use":
    guard let u = rest.first, let id = deviceID(uid: u) else { fail("没有这个 UID：\(rest.first ?? "")") }
    var a = addr(kAudioHardwarePropertyDefaultOutputDevice)
    var v = id
    let st = AudioObjectSetPropertyData(SYS, &a, 0, nil, UInt32(MemoryLayout<AudioObjectID>.size), &v)
    if st != noErr { fail("切换失败，OSStatus \(st)") }

case "members":
    guard let u = rest.first, let id = deviceID(uid: u) else { fail("没有这个 UID") }
    members(id).forEach { print($0) }

case "make":
    // make <名字> <主时钟uid> <成员uid...>
    guard rest.count >= 3 else { fail("用法：make <名字> <主时钟uid> <成员uid...>") }
    let name = rest[0], master = rest[1], subs = Array(rest.dropFirst(2))
    guard subs.contains(master) else { fail("主时钟必须也在成员里") }

    let uid = "rex.passthru." + UUID().uuidString
    let desc: [String: Any] = [
        kAudioAggregateDeviceNameKey as String: name,
        kAudioAggregateDeviceUIDKey as String: uid,
        // stacked = 1 才是「多输出设备」（一份声音同时送给所有成员）；
        // 等于 0 是普通聚合设备，通道会被拼接而不是复制，耳机里就没声了。
        kAudioAggregateDeviceIsStackedKey as String: 1,
        // private = 1 的设备只有创建它的进程看得见，而我们要让整个系统把声音
        // 路由过来，所以必须是 0。代价是进程退出后它还在，得显式 destroy。
        kAudioAggregateDeviceIsPrivateKey as String: 0,
        kAudioAggregateDeviceMasterSubDeviceKey as String: master,
        kAudioAggregateDeviceSubDeviceListKey as String: subs.map { u -> [String: Any] in
            [kAudioSubDeviceUIDKey as String: u,
             kAudioSubDeviceDriftCompensationKey as String: (u == master ? 0 : 1)]
        }
    ]
    var newID: AudioObjectID = 0
    let st = AudioHardwareCreateAggregateDevice(desc as CFDictionary, &newID)
    if st != noErr || newID == 0 { fail("建不出多输出设备，OSStatus \(st)") }
    print(uid)

case "destroy":
    guard let u = rest.first else { fail("要一个 UID") }
    guard let id = deviceID(uid: u) else { exit(0) }   // 已经不在了，当成功
    let st = AudioHardwareDestroyAggregateDevice(id)
    if st != noErr { fail("删不掉，OSStatus \(st)") }

default:
    fail("不认识的子命令：\(cmd)")
}
