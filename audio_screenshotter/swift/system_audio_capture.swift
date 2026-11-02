// Capture system audio output (everything the Mac plays, e.g. VoiceOver
// speech) to a WAV file via ScreenCaptureKit, macOS 13+.
//
// Usage: system-audio-capture <output.wav>
//
// Built on demand by system_audio.py (swiftc, from the Xcode command line tools).
//
// Prints "first_pts=<seconds>" on stdout when the first buffer arrives. That
// value is on the host clock, the same clock ffmpeg's avfoundation input
// reports as its "start:" time, so the caller can line the two recordings up.
//
// Audio is placed by its presentation timestamp, and any gap (silence the
// system didn't deliver, or time the process spent SIGSTOPped during a pause)
// is filled with silence, so the file tracks wall-clock time like ffmpeg's
// recording does.
//
// Stops cleanly on SIGINT/SIGTERM or when stdin closes.

import AVFoundation
import CoreMedia
import Foundation
@preconcurrency import ScreenCaptureKit

let sampleRate = 48000.0
let channelCount: AVAudioChannelCount = 1

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("system-audio-capture: \(message)\n".utf8))
    exit(1)
}

guard CommandLine.arguments.count == 2 else { fail("usage: system-audio-capture <output.wav>") }
let outputURL = URL(fileURLWithPath: CommandLine.arguments[1])

// Only touched from its own serial queue, apart from finish(), which syncs onto it.
final class AudioWriter: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    private let file: AVAudioFile
    private let format: AVAudioFormat
    private let queue = DispatchQueue(label: "system-audio-capture.writer")
    private var firstPTS: Double?
    private var framesWritten: AVAudioFramePosition = 0

    init(url: URL) throws {
        format = AVAudioFormat(standardFormatWithSampleRate: sampleRate, channels: channelCount)!
        file = try AVAudioFile(
            forWriting: url,
            settings: [
                AVFormatIDKey: kAudioFormatLinearPCM,
                AVSampleRateKey: sampleRate,
                AVNumberOfChannelsKey: channelCount,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false,
            ],
            commonFormat: .pcmFormatFloat32,
            interleaved: false
        )
    }

    var sampleQueue: DispatchQueue { queue }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, sampleBuffer.isValid else { return }
        let pts = sampleBuffer.presentationTimeStamp.seconds
        if firstPTS == nil {
            firstPTS = pts
            print("first_pts=\(pts)")
            fflush(stdout)
        }

        // Fill any gap since the last buffer with silence.
        let expected = AVAudioFramePosition(((pts - firstPTS!) * sampleRate).rounded())
        if expected > framesWritten + AVAudioFramePosition(sampleRate * 0.05) {
            writeSilence(frames: expected - framesWritten)
        }

        try? sampleBuffer.withAudioBufferList { abl, _ in
            guard let description = sampleBuffer.formatDescription,
                  let input = AVAudioPCMBuffer(pcmFormat: AVAudioFormat(cmAudioFormatDescription: description),
                                               bufferListNoCopy: abl.unsafePointer)
            else { return }
            write(downmix(input))
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fail("capture stopped: \(error.localizedDescription)")
    }

    // ScreenCaptureKit delivers non-interleaved float stereo; average to mono.
    private func downmix(_ input: AVAudioPCMBuffer) -> AVAudioPCMBuffer {
        let frames = input.frameLength
        let output = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames)!
        output.frameLength = frames
        guard let src = input.floatChannelData, let dst = output.floatChannelData else { return output }
        let channels = Int(input.format.channelCount)
        for i in 0..<Int(frames) {
            var sum: Float = 0
            for c in 0..<channels { sum += src[c][i] }
            dst[0][i] = sum / Float(channels)
        }
        return output
    }

    private func writeSilence(frames: AVAudioFramePosition) {
        var remaining = frames
        while remaining > 0 {
            let chunk = AVAudioFrameCount(min(remaining, AVAudioFramePosition(sampleRate)))
            let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: chunk)!
            buffer.frameLength = chunk  // zero-filled on allocation
            write(buffer)
            remaining -= AVAudioFramePosition(chunk)
        }
    }

    private func write(_ buffer: AVAudioPCMBuffer) {
        do {
            try file.write(from: buffer)
            framesWritten += AVAudioFramePosition(buffer.frameLength)
        } catch {
            fail("could not write \(outputURL.path): \(error.localizedDescription)")
        }
    }

    // Called on the writer queue so it can't race a buffer being written.
    func finish() {
        queue.sync { file.close() }
    }
}

func startCapture() async throws -> (SCStream, AudioWriter) {
    let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
    guard let display = content.displays.first else { fail("no display found") }

    let config = SCStreamConfiguration()
    config.capturesAudio = true
    config.excludesCurrentProcessAudio = true
    config.sampleRate = Int(sampleRate)
    config.channelCount = 2
    // Audio is captured for the whole system regardless of the filter, but a
    // stream still needs a video setup; keep it as small as possible.
    config.width = 2
    config.height = 2
    config.minimumFrameInterval = CMTime(value: 1, timescale: 1)

    let writer = try AudioWriter(url: outputURL)
    let stream = SCStream(filter: SCContentFilter(display: display, excludingWindows: []),
                          configuration: config, delegate: writer)
    try stream.addStreamOutput(writer, type: .audio, sampleHandlerQueue: writer.sampleQueue)
    try await stream.startCapture()
    return (stream, writer)
}

func stopAndExit(_ stream: SCStream, _ writer: AudioWriter) {
    Task {
        try? await stream.stopCapture()
        writer.finish()
        exit(0)
    }
}

Task {
    let stream: SCStream
    let writer: AudioWriter
    do {
        (stream, writer) = try await startCapture()
    } catch {
        fail("could not start capture: \(error.localizedDescription)")
    }

    for sig in [SIGINT, SIGTERM] {
        signal(sig, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
        source.setEventHandler { stopAndExit(stream, writer) }
        source.resume()
        signalSources.append(source)
    }

    // The parent closing our stdin also means stop.
    DispatchQueue.global().async {
        while FileHandle.standardInput.availableData.count > 0 {}
        DispatchQueue.main.async { stopAndExit(stream, writer) }
    }
}

var signalSources: [DispatchSourceSignal] = []
dispatchMain()
