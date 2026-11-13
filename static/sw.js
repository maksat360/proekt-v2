// Кэш оболочки приложения: позволяет открыть приложение без сети.
const CACHE = 'v2-shell-v91';
const ASSETS = ['/', '/static/app.js?v=20261114a', '/static/style.css?v=20261114a', '/static/accounts.js?v=20261106f'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
  ).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin || url.pathname.startsWith('/api/')) return;   // данные — только из сети
  // страницы и файлы без версии (цех, склад) — из сети: иначе после обновления виден старый экран;
  // кэш — только запас на случай, когда сети нет
  const versioned = url.searchParams.has('v');
  if (req.mode === 'navigate' || !versioned) {
    e.respondWith(fetch(req).then((resp) => {
      if (resp.ok && !resp.redirected && resp.type === 'basic') {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
      }
      return resp;
    }).catch(() => caches.match(req).then((hit) => hit || caches.match('/'))));
    return;
  }
  // файлы с ?v= не меняются — их можно брать из кэша
  e.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((resp) => {
      // не запоминаем ошибки и редиректы — иначе старый ответ «залипает» навсегда
      if (resp.ok && !resp.redirected && resp.type === 'basic') {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
      }
      return resp;
    }))
  );
});
