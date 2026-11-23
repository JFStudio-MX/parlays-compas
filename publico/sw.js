// Necesario para que el cel deje instalar la app. Siempre pide lo más nuevo (los momios cambian);
// si no hay internet, enseña la última versión que se abrió.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET' || new URL(e.request.url).origin !== location.origin) return;
  e.respondWith(fetch(e.request).then(r => {
    const copia = r.clone();
    caches.open('parlays').then(c => c.put(e.request, copia));
    return r;
  }).catch(() => caches.match(e.request)));
});
