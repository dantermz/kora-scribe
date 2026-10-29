// KoraCapture: minimal iPhone app that records the consultation through the
// Ray-Ban Meta glasses microphone (Bluetooth hands-free profile) and shares the file.
//
// Output: 16 kHz, mono, 16-bit PCM WAV, the exact format Muse Voice Transcribe expects,
// so the file goes straight into scripts/transcribe_file.py with no conversion.

import AVFoundation
import Combine
import SwiftUI

@main
struct KoraCaptureApp: App {
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}

@MainActor
final class Recorder: ObservableObject {
    @Published var inputName = "—"
    @Published var usingGlasses = false
    @Published var isRecording = false
    @Published var elapsed: TimeInterval = 0
    @Published var lastFile: URL?
    @Published var message: String?

    private var recorder: AVAudioRecorder?
    private var timer: Timer?

    func configure() {
        // Only set the category here. The session is activated after the user grants mic
        // permission (in activate()), because activating first can fail with
        // "Session activation failed".
        do {
            // .allowBluetoothHFP enables the hands-free profile, which is how the glasses expose their mic.
            try AVAudioSession.sharedInstance().setCategory(
                .playAndRecord, mode: .default, options: [.allowBluetoothHFP]
            )
        } catch {
            message = "No se pudo configurar el audio: \(error.localizedDescription)"
        }
        NotificationCenter.default.addObserver(
            forName: AVAudioSession.routeChangeNotification, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.refreshRoute() }
        }
        NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.isRecording else { return }
                self.message = "La grabación se interrumpió (llamada, alarma u otra app de audio). Revisa el archivo."
                self.stop()
            }
        }
        Task { await activate() }
    }

    /// Ask for mic permission, then activate the audio session off the main thread.
    @discardableResult
    func activate() async -> Bool {
        guard await AVAudioApplication.requestRecordPermission() else {
            message = "Sin permiso de micrófono. Actívalo en Ajustes > KoraCapture."
            return false
        }
        do {
            try await Task.detached {
                try AVAudioSession.sharedInstance().setActive(true)
            }.value
            message = nil
            preferGlasses()
            return true
        } catch {
            message = "No se pudo activar el audio: \(error.localizedDescription). Cierra otras apps de audio (Meta AI, música, llamadas) y toca Reintentar."
            refreshRoute()
            return false
        }
    }

    func preferGlasses() {
        let session = AVAudioSession.sharedInstance()
        if let bluetooth = session.availableInputs?.first(where: { $0.portType == .bluetoothHFP }) {
            try? session.setPreferredInput(bluetooth)
        }
        refreshRoute()
    }

    func refreshRoute() {
        let input = AVAudioSession.sharedInstance().currentRoute.inputs.first
        inputName = input?.portName ?? "Sin micrófono"
        usingGlasses = input?.portType == .bluetoothHFP
    }

    func start() async {
        guard await activate() else { return }

        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        let url = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("kora-\(formatter.string(from: Date())).wav")

        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
        ]
        do {
            recorder = try AVAudioRecorder(url: url, settings: settings)
            recorder?.record()
            isRecording = true
            UIApplication.shared.isIdleTimerDisabled = true  // keep the screen from locking while recording
            lastFile = nil
            message = nil
            elapsed = 0
            timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
                Task { @MainActor in self?.elapsed = self?.recorder?.currentTime ?? 0 }
            }
        } catch {
            message = "No se pudo grabar: \(error.localizedDescription)"
        }
    }

    func stop() {
        recorder?.stop()
        timer?.invalidate()
        isRecording = false
        UIApplication.shared.isIdleTimerDisabled = false
        lastFile = recorder?.url
    }
}

struct ContentView: View {
    @StateObject private var recorder = Recorder()

    var body: some View {
        VStack(spacing: 28) {
            Text("KoraCapture").font(.largeTitle.bold())

            VStack(spacing: 6) {
                Text("Micrófono").font(.caption).foregroundStyle(.secondary)
                Label(recorder.inputName, systemImage: recorder.usingGlasses ? "eyeglasses" : "iphone")
                    .font(.headline)
                    .foregroundStyle(recorder.usingGlasses ? .green : .orange)
                if !recorder.usingGlasses {
                    Text("No se detectan los lentes. Conéctalos por Bluetooth y toca Reintentar.")
                        .font(.footnote).multilineTextAlignment(.center).foregroundStyle(.secondary)
                    Button("Reintentar") { Task { await recorder.activate() } }
                }
            }

            Text(String(format: "%02d:%02d", Int(recorder.elapsed) / 60, Int(recorder.elapsed) % 60))
                .font(.system(size: 56, weight: .semibold, design: .monospaced))

            Button {
                if recorder.isRecording { recorder.stop() } else { Task { await recorder.start() } }
            } label: {
                Text(recorder.isRecording ? "Detener" : "Grabar")
                    .font(.title2.bold())
                    .frame(maxWidth: .infinity, minHeight: 64)
            }
            .buttonStyle(.borderedProminent)
            .tint(recorder.isRecording ? .red : .accentColor)

            if let file = recorder.lastFile {
                ShareLink(item: file) {
                    Label("Compartir \(file.lastPathComponent)", systemImage: "square.and.arrow.up")
                }
            }

            if let message = recorder.message {
                Text(message).font(.footnote).foregroundStyle(.red).multilineTextAlignment(.center)
            }
            Spacer()
        }
        .padding(24)
        .onAppear { recorder.configure() }
    }
}

