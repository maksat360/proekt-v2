import SwiftUI

@main
struct PortalApp: App {
    @State private var showSettings = false
    @State private var reloadID = UUID()
    @State private var loading = false
    @State private var failed = false
    @State private var url: URL = AppConfig.startURL ?? URL(string: AppConfig.defaultURL)!

    var body: some Scene {
        WindowGroup {
            ZStack(alignment: .top) {
                WebView(url: url, loading: $loading, failed: $failed)
                    .id(reloadID)
                    .ignoresSafeArea(edges: .bottom)

                if loading {
                    ProgressView()
                        .progressViewStyle(.linear)
                        .tint(.blue)
                        .padding(.top, 4)
                }

                if failed {
                    VStack(spacing: 14) {
                        Image(systemName: "wifi.slash").font(.system(size: 44)).foregroundStyle(.secondary)
                        Text("Сервер недоступен").font(.headline)
                        Text("Проверьте Wi-Fi и запуск портала на MacBook.")
                            .font(.footnote).foregroundStyle(.secondary)
                        HStack(spacing: 12) {
                            Button("Повторить") { reloadID = UUID() }
                                .buttonStyle(.borderedProminent)
                            Button("Адрес") { showSettings = true }
                                .buttonStyle(.bordered)
                        }
                    }
                    .padding(22)
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 22))
                    .padding(24)
                }
            }
            .sheet(isPresented: $showSettings, onDismiss: {
                url = AppConfig.startURL ?? URL(string: AppConfig.defaultURL)!
                reloadID = UUID()
            }) {
                SettingsView()
            }
            .onAppear {
                if let custom = ProcessInfo.processInfo.environment["V2_URL"], !custom.isEmpty {
                    url = URL(string: custom) ?? url
                }
            }
        }
    }
}
