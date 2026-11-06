package com.projectv2.ceh;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.URL;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Поиск сервера в локальной сети: перебор адресов подсети и проверка /api/companies. */
public final class Discovery {

    private Discovery() {}

    public static String localIpv4() {
        try {
            Enumeration<NetworkInterface> ifaces = NetworkInterface.getNetworkInterfaces();
            while (ifaces != null && ifaces.hasMoreElements()) {
                NetworkInterface nif = ifaces.nextElement();
                if (!nif.isUp() || nif.isLoopback()) continue;
                Enumeration<InetAddress> addrs = nif.getInetAddresses();
                while (addrs.hasMoreElements()) {
                    InetAddress addr = addrs.nextElement();
                    if (addr instanceof Inet4Address && !addr.isLoopbackAddress() && !addr.isLinkLocalAddress()) {
                        return addr.getHostAddress();
                    }
                }
            }
        } catch (Exception ignored) {}
        return null;
    }

    /** Возвращает http://IP:port найденного сервера или null. */
    public static String scan(int port, int timeoutMs) {
        String myIp = localIpv4();
        if (myIp == null) return null;
        String[] parts = myIp.split("\\.");
        if (parts.length != 4) return null;
        String base = parts[0] + "." + parts[1] + "." + parts[2] + ".";

        ExecutorService pool = Executors.newFixedThreadPool(32);
        final CountDownLatch latch = new CountDownLatch(254);
        final AtomicReference<String> found = new AtomicReference<>(null);

        for (int i = 1; i <= 254; i++) {
            final String host = base + i;
            pool.execute(new Runnable() {
                @Override public void run() {
                    try {
                        if (found.get() == null && probe(host, port, timeoutMs)) {
                            found.compareAndSet(null, host);
                        }
                    } finally {
                        latch.countDown();
                    }
                }
            });
        }
        try {
            latch.await(6, TimeUnit.SECONDS);
        } catch (InterruptedException ignored) {}
        pool.shutdownNow();
        String host = found.get();
        return host == null ? null : "http://" + host + ":" + port;
    }

    private static boolean probe(String host, int port, int timeoutMs) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL("http://" + host + ":" + port + "/api/companies");
            conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(timeoutMs);
            conn.setReadTimeout(timeoutMs);
            conn.setRequestMethod("GET");
            if (conn.getResponseCode() != 200) return false;
            InputStream in = conn.getInputStream();
            byte[] buf = new byte[512];
            int n = in.read(buf);
            in.close();
            if (n <= 0) return false;
            String body = new String(buf, 0, n, "UTF-8");
            return body.contains("\"ok\": true") || body.contains("\"ok\":true");
        } catch (Exception e) {
            return false;
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    public static int portFromUrl(String url) {
        try {
            int idx = url.indexOf("://");
            String rest = url.substring(idx + 3);
            int slash = rest.indexOf('/');
            String authority = slash >= 0 ? rest.substring(0, slash) : rest;
            int colon = authority.lastIndexOf(':');
            if (colon >= 0) return Integer.parseInt(authority.substring(colon + 1));
        } catch (Exception ignored) {}
        return 8787;
    }
}
