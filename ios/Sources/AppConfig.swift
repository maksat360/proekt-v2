import Foundation

/// Настройки подключения к порталу: адрес сервера и режим работы.
enum AppConfig {
    private static let urlKey = "server_url"
    private static let modeKey = "sklad_mode"

    /// Адрес по умолчанию — MacBook в локальной сети.
    static let defaultURL = "http://192.168.0.116:8787"

    static var url: String {
        get { normalize(UserDefaults.standard.string(forKey: urlKey) ?? defaultURL) }
        set { UserDefaults.standard.set(normalize(newValue), forKey: urlKey) }
    }

    /// true — приложение открывает только склад (/sklad).
    static var skladMode: Bool {
        get { UserDefaults.standard.bool(forKey: modeKey) }
        set { UserDefaults.standard.set(newValue, forKey: modeKey) }
    }

    /// Полный адрес с учётом режима.
    static var startURL: URL? {
        URL(string: url + (skladMode ? "/sklad" : "/"))
    }

    /// Убирает пробелы и хвостовой слэш, добавляет схему.
    static func normalize(_ raw: String) -> String {
        var s = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.isEmpty { return defaultURL }
        if !s.hasPrefix("http://") && !s.hasPrefix("https://") { s = "http://" + s }
        while s.hasSuffix("/") { s.removeLast() }
        return s
    }
}
