const CACHE = 'nekosuneai-mobile-v1';
const SHELL = ['/mobile', '/manifest.webmanifest', '/logo.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).catch(() => undefined));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
});

self.addEventListener('message', (event) => {
  if (event.data?.type !== 'notify') return;
  const title = event.data.title || 'NekoSuneAI';
  const body = event.data.body || '';
  const level = event.data.level || 'warning';
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: '/logo.png',
      badge: '/logo.png',
      tag: `nekosuneai-${level}`,
      renotify: true,
      vibrate: level === 'danger' ? [250, 120, 250, 120, 500] : [180, 100, 180],
      data: { url: '/mobile' }
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      const existing = clients.find((client) => 'focus' in client);
      if (existing) {
        existing.navigate('/mobile');
        return existing.focus();
      }
      return self.clients.openWindow('/mobile');
    })
  );
});
