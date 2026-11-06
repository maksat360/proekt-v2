package com.projectv2.sklad;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import android.util.TypedValue;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/** Настройка адреса сервера: ввод, проверка связи и поиск Mac в сети. */
public class SettingsActivity extends Activity {

    private EditText input;
    private TextView status;
    private Button checkBtn;
    private Button scanBtn;
    private final Handler ui = new Handler(Looper.getMainLooper());

    private int dp(float v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.parseColor("#F5F5F7"));

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(22), dp(20), dp(28));

        TextView h = new TextView(this);
        h.setText("Адрес сервера");
        h.setTextSize(24);
        h.setTextColor(Color.parseColor("#1D1D1F"));
        root.addView(h);

        TextView sub = new TextView(this);
        sub.setText("Укажите IP-адрес MacBook в локальной сети и порт портала. "
                + "Найти адрес можно кнопкой «Найти в сети» или на Mac: Системные настройки → Wi-Fi → Подробнее.");
        sub.setTextSize(13);
        sub.setTextColor(Color.parseColor("#6E6E73"));
        sub.setPadding(0, dp(6), 0, dp(16));
        root.addView(sub);

        input = new EditText(this);
        input.setSingleLine(true);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setText(AppConfig.getUrl(this));
        input.setTextSize(16);
        input.setPadding(dp(12), dp(10), dp(12), dp(10));
        input.setBackgroundColor(Color.WHITE);
        root.addView(input, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(0, dp(14), 0, dp(6));

        checkBtn = pillButton("Проверить связь", Color.parseColor("#0071E3"), Color.WHITE);
        checkBtn.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { check(); }
        });
        row.addView(checkBtn, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        scanBtn = pillButton("Найти в сети", Color.parseColor("#E8E8ED"), Color.parseColor("#1D1D1F"));
        scanBtn.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { scan(); }
        });
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        sp.leftMargin = dp(10);
        row.addView(scanBtn, sp);
        root.addView(row);

        status = new TextView(this);
        status.setTextSize(13);
        status.setTextColor(Color.parseColor("#6E6E73"));
        status.setPadding(0, dp(10), 0, dp(18));
        root.addView(status);

        Button save = pillButton("Сохранить и открыть", Color.parseColor("#1D1D1F"), Color.WHITE);
        save.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { save(); }
        });
        root.addView(save, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48)));

        Button def = new Button(this);
        def.setText("Сбросить на адрес по умолчанию");
        def.setBackgroundColor(Color.TRANSPARENT);
        def.setTextColor(Color.parseColor("#0071E3"));
        def.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                input.setText(AppConfig.DEFAULT_URL);
                status.setText("");
            }
        });
        root.addView(def);

        TextView hint = new TextView(this);
        hint.setText("Подсказка: IP может измениться после переподключения к Wi-Fi — "
                + "тогда снова нажмите «Найти в сети». Порт по умолчанию 8787.");
        hint.setTextSize(12);
        hint.setTextColor(Color.parseColor("#86868B"));
        hint.setPadding(0, dp(8), 0, 0);
        root.addView(hint);

        scroll.addView(root);
        setContentView(scroll);
    }

    private Button pillButton(String text, int bg, int fg) {
        Button b = new Button(this);
        b.setText(text);
        b.setTextSize(14);
        b.setTextColor(fg);
        b.setBackgroundColor(bg);
        b.setPadding(dp(16), dp(10), dp(16), dp(10));
        b.setAllCaps(false);
        return b;
    }

    private void check() {
        final String url = AppConfig.normalize(input.getText().toString());
        if (!AppConfig.isAllowed(url)) {
            status.setTextColor(Color.parseColor("#D2321E"));
            status.setText("Недопустимый адрес. Для внешних адресов нужен https, для локальной сети — http://192.168.x.x:8787");
            return;
        }
        status.setTextColor(Color.parseColor("#6E6E73"));
        status.setText("Проверяю…");
        checkBtn.setEnabled(false);
        new Thread(new Runnable() {
            @Override public void run() {
                final String result = probe(url);
                ui.post(new Runnable() {
                    @Override public void run() {
                        checkBtn.setEnabled(true);
                        if (result != null) {
                            status.setTextColor(Color.parseColor("#1D9A4E"));
                            status.setText("Сервер отвечает · " + result);
                        } else {
                            status.setTextColor(Color.parseColor("#D2321E"));
                            status.setText("Не отвечает. Проверьте, что портал запущен на Mac и телефон в той же Wi-Fi.");
                        }
                    }
                });
            }
        }).start();
    }

    /** Возвращает описание цехов при успехе, иначе null. */
    private String probe(String base) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(base + "/api/companies");
            conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(3500);
            conn.setReadTimeout(3500);
            if (conn.getResponseCode() != 200) return null;
            InputStream in = conn.getInputStream();
            byte[] buf = new byte[2048];
            int n = in.read(buf);
            in.close();
            if (n <= 0) return null;
            String body = new String(buf, 0, n, "UTF-8");
            if (!body.contains("\"ok\": true") && !body.contains("\"ok\":true")) return null;
            int count = body.split("\"код\"").length - 1;
            return count > 0 ? "цехов: " + count : "портал доступен";
        } catch (Exception e) {
            return null;
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private void scan() {
        status.setTextColor(Color.parseColor("#6E6E73"));
        status.setText("Ищу портал в сети…");
        scanBtn.setEnabled(false);
        final int port = Discovery.portFromUrl(AppConfig.normalize(input.getText().toString()));
        new Thread(new Runnable() {
            @Override public void run() {
                final String found = Discovery.scan(port, 450);
                ui.post(new Runnable() {
                    @Override public void run() {
                        scanBtn.setEnabled(true);
                        if (found != null) {
                            input.setText(found);
                            status.setTextColor(Color.parseColor("#1D9A4E"));
                            status.setText("Нашёл сервер: " + found);
                        } else {
                            status.setTextColor(Color.parseColor("#D2321E"));
                            status.setText("В этой сети сервер не найден. Проверьте Wi-Fi и что портал запущен.");
                        }
                    }
                });
            }
        }).start();
    }

    private void save() {
        String url = AppConfig.normalize(input.getText().toString());
        if (!AppConfig.isAllowed(url)) {
            Toast.makeText(this, "Такой адрес не подходит", Toast.LENGTH_LONG).show();
            return;
        }
        AppConfig.setUrl(this, url);
        Toast.makeText(this, "Сохранено: " + url, Toast.LENGTH_SHORT).show();
        finish();
    }
}
