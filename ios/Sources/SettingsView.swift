import SwiftUI

/// Экран настроек: адрес сервера и режим склада.
struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var address: String = AppConfig.url
    @State private var skladMode: Bool = AppConfig.skladMode
    @State private var status: String = ""
    @State private var checking = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Адрес сервера") {
                    TextField("192.168.0.104:8787", text: $address)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button(checking ? "Проверяю…" : "Проверить связь") { check() }
                        .disabled(checking)
                    if !status.isEmpty {
                        Text(status).font(.footnote).foregroundStyle(.secondary)
                    }
                }
                Section("Режим") {
                    Toggle("Только склад", isOn: $skladMode)
                    Text(skladMode
                         ? "Приложение откроет раздел «Склад»: остатки, приход, адрес, поставки."
                         : "Приложение откроет весь портал: склад, магазин, партии, отчёты.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section {
                    Button("Сохранить") {
                        AppConfig.url = address
                        AppConfig.skladMode = skladMode
                        dismiss()
                    }
                }
            }
            .navigationTitle("Настройки")
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Закрыть") { dismiss() } } }
        }
    }

    private func check() {
        let base = AppConfig.normalize(address)
        guard let url = URL(string: base + "/api/companies") else {
            status = "Некорректный адрес"
            return
        }
        checking = true
        status = ""
        var request = URLRequest(url: url)
        request.timeoutInterval = 4
        URLSession.shared.dataTask(with: request) { data, response, _ in
            DispatchQueue.main.async {
                checking = false
                if let http = response as? HTTPURLResponse, http.statusCode == 200, data != nil {
                    status = "Связь есть — сервер отвечает"
                } else {
                    status = "Сервер не ответил. Проверьте Wi-Fi и запуск портала."
                }
            }
        }.resume()
    }
}
