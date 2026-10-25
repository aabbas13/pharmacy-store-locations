const CACHE_NAME = 'hmc-picker-pwa-v1';
const APP_SCOPE = self.registration.scope;
const APP_INDEX = new URL('index.html', APP_SCOPE).href;
const APP_SHELL = [
  APP_INDEX,
  new URL('manifest.webmanifest', APP_SCOPE).href,
  new URL('icons/hmc-picker-192.png', APP_SCOPE).href,
  new URL('icons/hmc-picker-512.png', APP_SCOPE).href
];
const SCRIPT_CDNS = new Set([
  'cdnjs.cloudflare.com',
  'cdn.jsdelivr.net',
  'www.gstatic.com'
]);

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(key => key.startsWith('hmc-picker-pwa-') && key !== CACHE_NAME).map(key => caches.delete(key))
  )).then(() => self.clients.claim()));
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);

  if (url.origin === self.location.origin && request.mode === 'navigate') {
    event.respondWith(fetch(request).then(response => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(APP_INDEX, copy));
      }
      return response;
    }).catch(async () => (await caches.match(request)) || (await caches.match(APP_INDEX))));
    return;
  }

  if (request.destination === 'script' && SCRIPT_CDNS.has(url.hostname)) {
    event.respondWith(caches.open(CACHE_NAME).then(async cache => {
      const cached = await cache.match(request);
      const update = fetch(request).then(response => {
        if (response.ok || response.type === 'opaque') cache.put(request, response.clone());
        return response;
      });
      if (cached) {
        event.waitUntil(update.catch(() => {}));
        return cached;
      }
      return update;
    }).catch(async () => (await caches.match(request)) || Response.error()));
    return;
  }

  if (url.origin === self.location.origin) {
    event.respondWith(caches.match(request).then(cached => cached || fetch(request).then(response => {
      if (response.ok) caches.open(CACHE_NAME).then(cache => cache.put(request, response.clone()));
      return response;
    })));
  }
});
