/* Offline shell. Static assets are cached; API responses are not — cycle data
   should not sit in a cache the user cannot see or clear from inside the app.

   Every fetch here passes {cache: 'reload'}, which forces the browser to hit
   the network and skip its own HTTP disk cache for the freshness decision —
   still storing the response afterward, just never trusting a cached copy to
   answer "is this current?" A plain fetch() does not do that: it will
   silently resolve from disk cache without a network round trip if the
   browser's own heuristic freshness window hasn't lapsed, which starves both
   the install step (stale shell baked in on first cache) and the runtime
   network-first path (a code fix that never reaches an open tab) — found
   2026-08-06 debugging a date-handling fix that two ordinary reloads did not
   pick up. Bump CACHE on any shell change so activate's cleanup still runs. */

const CACHE = 'cycliq-shell-v5';
const SHELL = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/insights.js',
  '/static/social.js',
  '/static/import.js',
  '/static/quiz.js',
  '/static/icon.svg',
  '/static/fonts/bricolage-grotesque-latin.woff2',
  '/static/fonts/hanken-grotesk-latin.woff2',
  '/manifest.json',
];

async function cacheShellFresh() {
  const cache = await caches.open(CACHE);
  await Promise.all(
    SHELL.map(async (url) => {
      const response = await fetch(url, { cache: "reload" });
      await cache.put(url, response);
    }),
  );
}

self.addEventListener('install', (event) => {
  event.waitUntil(cacheShellFresh().then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.pathname.startsWith('/api/')) return;

  event.respondWith(
    fetch(event.request, { cache: 'reload' })
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((c) => c.put(event.request, copy)).catch(() => {});
        return response;
      })
      .catch(() => caches.match(event.request).then((hit) => hit || caches.match('/'))),
  );
});
