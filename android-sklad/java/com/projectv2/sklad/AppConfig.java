package com.projectv2.sklad;

import android.content.Context;
import android.content.SharedPreferences;

/** Адрес сервера: хранение, нормализация и проверка допустимости. */
public final class AppConfig {

    private static final String PREFS = "ceh_prefs";
    private static final String KEY_URL = "server_url";

    /** Адрес по умолчанию — MacBook в локальной сети (меняется в настройках приложения). */
    public static final String DEFAULT_URL = "http://192.168.0.116:8787/sklad";

    private AppConfig() {}

    public static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public static String getUrl(Context c) {
        String raw = prefs(c).getString(KEY_URL, DEFAULT_URL);
        String url = normalize(raw);
        return isAllowed(url) ? url : DEFAULT_URL;
    }

    public static void setUrl(Context c, String url) {
        prefs(c).edit().putString(KEY_URL, normalize(url)).apply();
    }

    /** Добавляет схему, убирает хвостовой слэш и пробелы. */
    public static String normalize(String raw) {
        if (raw == null) return DEFAULT_URL;
        String s = raw.trim();
        if (s.isEmpty()) return DEFAULT_URL;
        if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://" + s;
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }

    /**
     * HTTP разрешаем только для локальной сети (приватные адреса, .local, localhost).
     * Для внешних адресов требуется HTTPS — так приложение не станет случайно
     * ходить по открытому HTTP в интернет.
     */
    public static boolean isAllowed(String url) {
        String host;
        String scheme;
        try {
            int idx = url.indexOf("://");
            scheme = url.substring(0, idx).toLowerCase();
            String rest = url.substring(idx + 3);
            int slash = rest.indexOf('/');
            String authority = slash >= 0 ? rest.substring(0, slash) : rest;
            int at = authority.indexOf('@');
            if (at >= 0) authority = authority.substring(at + 1);
            int colon = authority.indexOf(':');
            host = colon >= 0 ? authority.substring(0, colon) : authority;
        } catch (Exception e) {
            return false;
        }
        if (host.isEmpty()) return false;
        if ("https".equals(scheme)) return true;
        if (!"http".equals(scheme)) return false;
        return isPrivateHost(host);
    }

    public static boolean isPrivateHost(String host) {
        String h = host.toLowerCase();
        if (h.equals("localhost") || h.equals("127.0.0.1")) return true;
        if (h.endsWith(".local")) return true;
        if (h.equals("10.0.2.2")) return true; // эмулятор Android
        String[] p = h.split("\\.");
        if (p.length != 4) return false;
        try {
            int a = Integer.parseInt(p[0]);
            int b = Integer.parseInt(p[1]);
            if (a == 10) return true;
            if (a == 192 && b == 168) return true;
            if (a == 172 && b >= 16 && b <= 31) return true;
            if (a == 127) return true;
        } catch (NumberFormatException ignored) {
            return false;
        }
        return false;
    }
}
