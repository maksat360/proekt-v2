package com.projectv2.ceh;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebResourceResponse;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import android.util.TypedValue;

/** Обёртка существующего сайта цеха: тот же сервер, тот же интерфейс. */
public class MainActivity extends Activity {

    private WebView web;
    private TextView offlineBar;
    private ProgressBar progress;
    private String currentUrl;
    private boolean errorShown = false;
    private long lastBackPress = 0;
    private android.content.BroadcastReceiver scanReceiver;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        currentUrl = AppConfig.getUrl(this);
        buildUi();
        setupWebView();
        registerScanReceiver();
        registerNetworkWatch();
        web.loadUrl(pageUrl());
    }


    /** Какой файл из assets отдать вместо сети. null — пусть идёт в сеть. */
    static String localAsset(Uri uri, String serverUrl) {
        String serverHost = Uri.parse(serverUrl).getHost();
        if (uri == null || uri.getHost() == null || !uri.getHost().equals(serverHost)) return null;
        String p = uri.getPath() == null ? "/" : uri.getPath();
        if (p.equals("/") || p.equals("/index.html")) return "index.html";
        if (p.equals("/sklad") || p.equals("/sklad/") || p.equals("/sklad.html")) return "sklad.html";
        if (p.equals("/sw.js")) return "sw.js";
        if (p.equals("/manifest.webmanifest")) return "manifest.webmanifest";
        if (p.equals("/manifest-sklad.webmanifest")) return "manifest-sklad.webmanifest";
        if (p.startsWith("/static/")) return p.substring(1);
        return null;
    }

    static String mimeFor(String name) {
        if (name.endsWith(".js")) return "application/javascript";
        if (name.endsWith(".css")) return "text/css";
        if (name.endsWith(".html")) return "text/html";
        if (name.endsWith(".png")) return "image/png";
        if (name.endsWith(".webmanifest")) return "application/manifest+json";
        if (name.endsWith(".svg")) return "image/svg+xml";
        if (name.endsWith(".json")) return "application/json";
        return "application/octet-stream";
    }

    private String pageUrl() {
        return AppConfig.getUrl(this) + "/?app=android";
    }

    private int dp(float v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics());
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#F5F5F7"));

        // верхняя панель
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(Color.parseColor("#1D1D1F"));
        bar.setPadding(dp(14), dp(8), dp(6), dp(8));

        TextView title = new TextView(this);
        title.setText(R.string.app_name);
        title.setTextColor(Color.WHITE);
        title.setTextSize(16);
        title.setSingleLine(true);
        LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        title.setLayoutParams(tp);
        bar.addView(title);

        bar.addView(barButton("⟳", new View.OnClickListener() {
            @Override public void onClick(View v) {
                errorShown = false;
                web.loadUrl(pageUrl());
            }
        }));
        bar.addView(barButton("⚙", new View.OnClickListener() {
            @Override public void onClick(View v) {
                startActivity(new Intent(MainActivity.this, SettingsActivity.class));
            }
        }));

        // полоса «нет сети»
        offlineBar = new TextView(this);
        offlineBar.setText("Нет связи с сервером. Проверьте Wi-Fi и что Mac включён.");
        offlineBar.setTextColor(Color.WHITE);
        offlineBar.setTextSize(12.5f);
        offlineBar.setBackgroundColor(Color.parseColor("#D2321E"));
        offlineBar.setPadding(dp(14), dp(8), dp(14), dp(8));
        offlineBar.setVisibility(View.GONE);

        // прогресс
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100);
        progress.setVisibility(View.GONE);

        web = new WebView(this);
        LinearLayout.LayoutParams wp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        web.setLayoutParams(wp);

        root.addView(bar);
        root.addView(offlineBar);
        root.addView(progress, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(2)));
        root.addView(web);
        setContentView(root);
    }

    private Button barButton(String label, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextSize(18);
        b.setTextColor(Color.WHITE);
        b.setBackgroundColor(Color.TRANSPARENT);
        b.setMinWidth(dp(44));
        b.setMinimumWidth(dp(44));
        b.setPadding(dp(8), 0, dp(8), 0);
        b.setOnClickListener(l);
        return b;
    }

    private void setupWebView() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setUserAgentString(s.getUserAgentString() + " CehApp/1.0");
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);

        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        cm.setAcceptThirdPartyCookies(web, false);

        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onProgressChanged(WebView view, int newProgress) {
                progress.setVisibility(newProgress < 100 ? View.VISIBLE : View.GONE);
                progress.setProgress(newProgress);
            }
        });

        web.setWebViewClient(new WebViewClient() {
            // Интерфейс берём из APK: в сеть уходят только запросы к /api/.
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                String asset = MainActivity.localAsset(request.getUrl(), AppConfig.getUrl(MainActivity.this));
                if (asset == null) return null;
                try {
                    WebResourceResponse resp = new WebResourceResponse(
                            MainActivity.mimeFor(asset), "utf-8", getAssets().open("www/" + asset));
                    java.util.Map<String, String> headers = new java.util.HashMap<>();
                    headers.put("Cache-Control", "public, max-age=604800");
                    resp.setResponseHeaders(headers);
                    return resp;
                } catch (java.io.IOException e) {
                    return null;
                }
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String scheme = uri.getScheme() == null ? "" : uri.getScheme();
                if ("ceh".equals(scheme)) {
                    String host = uri.getHost();
                    if ("retry".equals(host)) {
                        errorShown = false;
                        web.loadUrl(pageUrl());
                    } else if ("settings".equals(host)) {
                        startActivity(new Intent(MainActivity.this, SettingsActivity.class));
                    }
                    return true;
                }
                if (!"http".equals(scheme) && !"https".equals(scheme)) return true;
                String serverHost = Uri.parse(AppConfig.getUrl(MainActivity.this)).getHost();
                if (uri.getHost() != null && uri.getHost().equals(serverHost)) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (ActivityNotFoundException ignored) {}
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                progress.setVisibility(View.GONE);
                offlineBar.setVisibility(View.GONE);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) showError();
            }

            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                showError();
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                            android.webkit.WebResourceResponse response) {
                if (request.isForMainFrame() && response.getStatusCode() >= 500) showError();
            }
        });

        web.setDownloadListener(new DownloadListener() {
            @Override public void onDownloadStart(String url, String userAgent, String disposition,
                                                 String mimeType, long contentLength) {
                download(url, userAgent, disposition, mimeType);
            }
        });
    }

    private void download(String url, String userAgent, String disposition, String mimeType) {
        try {
            String name = "отчёт.xlsx";
            if (disposition != null) {
                int i = disposition.indexOf("filename*=UTF-8''");
                if (i >= 0) name = Uri.decode(disposition.substring(i + 17).replace("\"", ""));
            }
            DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
            req.setMimeType(mimeType != null ? mimeType :
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
            String cookie = CookieManager.getInstance().getCookie(url);
            if (cookie != null) req.addRequestHeader("Cookie", cookie);
            if (userAgent != null) req.addRequestHeader("User-Agent", userAgent);
            req.setTitle(name);
            req.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            req.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
            DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            if (dm != null) {
                dm.enqueue(req);
                Toast.makeText(this, "Файл сохраняется в «Загрузки»", Toast.LENGTH_SHORT).show();
            }
        } catch (Exception e) {
            Toast.makeText(this, "Не удалось скачать файл", Toast.LENGTH_SHORT).show();
        }
    }

    private void showError() {
        if (errorShown) return;
        errorShown = true;
        offlineBar.setVisibility(View.VISIBLE);
        progress.setVisibility(View.GONE);
        String url = AppConfig.getUrl(this);
        String html = "<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
                + "<style>body{margin:0;background:#F5F5F7;font-family:-apple-system,'Helvetica Neue',Arial;"
                + "color:#1D1D1F;display:flex;min-height:100vh;align-items:center;justify-content:center}"
                + ".c{max-width:420px;padding:28px;text-align:center}"
                + "h1{font-size:22px;margin:0 0 10px}p{color:#6E6E73;font-size:14px;line-height:1.5;margin:0 0 18px}"
                + "a{display:inline-block;background:#0071E3;color:#fff;text-decoration:none;padding:12px 22px;"
                + "border-radius:999px;font-size:14px;margin:4px}a.sec{background:#E8E8ED;color:#1D1D1F}"
                + "code{background:#E8E8ED;padding:2px 6px;border-radius:6px;font-size:12px}"
                + "</style></head><body><div class='c'>"
                + "<h1>Сервер недоступен</h1>"
                + "<p>Приложение не смогло подключиться к <code>" + url + "</code>.<br>"
                + "Проверьте: Mac включён и не спит, портал запущен, телефон в той же Wi-Fi сети.</p>"
                + "<a href='ceh://retry'>Повторить</a>"
                + "<a class='sec' href='ceh://settings'>Изменить адрес</a>"
                + "</div></body></html>";
        web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
    }

    private void registerNetworkWatch() {
        try {
            ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
            if (cm == null) return;
            cm.registerDefaultNetworkCallback(new ConnectivityManager.NetworkCallback() {
                @Override public void onAvailable(Network network) {
                    runOnUiThread(new Runnable() {
                        @Override public void run() {
                            if (errorShown) {
                                errorShown = false;
                                web.loadUrl(pageUrl());
                            } else {
                                offlineBar.setVisibility(View.GONE);
                            }
                        }
                    });
                }

                @Override public void onLost(Network network) {
                    runOnUiThread(new Runnable() {
                        @Override public void run() {
                            offlineBar.setVisibility(View.VISIBLE);
                        }
                    });
                }
            });
        } catch (Exception ignored) {}
    }

    @Override
    protected void onResume() {
        super.onResume();
        String url = AppConfig.getUrl(this);
        if (!url.equals(currentUrl)) {
            currentUrl = url;
            errorShown = false;
            web.loadUrl(pageUrl());
        }
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) {
            web.goBack();
        } else if (System.currentTimeMillis() - lastBackPress < 2000) {
            super.onBackPressed();
        } else {
            lastBackPress = System.currentTimeMillis();
            Toast.makeText(this, "Нажмите ещё раз, чтобы выйти", Toast.LENGTH_SHORT).show();
        }
    }

    @Override
    protected void onDestroy() {
        if (scanReceiver != null) {
            try { unregisterReceiver(scanReceiver); } catch (Exception ignored) {}
        }
        if (web != null) web.destroy();
        super.onDestroy();
    }

    /** Приём сканов от DataWedge (Zebra TC15) в режиме Intent output. */
    private void registerScanReceiver() {
        android.content.IntentFilter f = new android.content.IntentFilter();
        f.addCategory(android.content.Intent.CATEGORY_DEFAULT);
        f.addAction("com.projectv2.ceh.SCAN");           // профиль DataWedge
        f.addAction("com.symbol.datawedge.api.RESULT_ACTION");
        f.addAction("com.motorolasolutions.emdk.datawedge.api.ACTION_BARCODE_DATA");
        f.addAction("android.intent.action.DECODE_DATA");

        scanReceiver = new android.content.BroadcastReceiver() {
            @Override public void onReceive(Context c, Intent i) {
                String data = extractScanData(i);
                if (data != null) deliverScan(data);
            }
        };
        try {
            if (android.os.Build.VERSION.SDK_INT >= 33) {
                registerReceiver(scanReceiver, f, Context.RECEIVER_EXPORTED);
            } else {
                registerReceiver(scanReceiver, f);
            }
        } catch (Exception e) {
            scanReceiver = null;
        }
    }

    private String extractScanData(Intent i) {
        String data = i.getStringExtra("com.symbol.datawedge.data_string");
        if (data == null) data = i.getStringExtra("com.motorolasolutions.emdk.datawedge.data_string");
        if (data == null) data = i.getStringExtra("barcode_string");
        if (data == null) data = i.getStringExtra("SCAN_RESULT");
        if (data == null && i.getDataString() != null) data = i.getDataString();
        if (data == null) {
            android.os.Bundle b = i.getExtras();
            if (b != null) {
                for (String k : b.keySet()) {
                    Object v = b.get(k);
                    if (v instanceof String && !"com.symbol.datawedge.label_type".equals(k)
                            && !"com.symbol.datawedge.source".equals(k)) {
                        String val = (String) v;
                        if (val.length() >= 4 && val.length() <= 40) { data = val; break; }
                    }
                }
            }
        }
        if (data != null) data = data.trim();
        return data;
    }

    private void deliverScan(final String data) {
        runOnUiThread(new Runnable() {
            @Override public void run() {
                if (web == null) return;
                String q;
                try { q = org.json.JSONObject.quote(data); } catch (Exception e) { q = "\"" + data + "\""; }
                web.evaluateJavascript("window.__nativeScan && window.__nativeScan(" + q + ")", null);
            }
        });
    }
}
