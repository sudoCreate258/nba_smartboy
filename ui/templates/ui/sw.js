/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Service worker (M4-T4): caches the app shell and the pages you view, so they
   load without a connection. Only same-origin GET requests are cached; nothing
   is ever fetched from another host. Check-ins made offline are queued by
   offline.js (IndexedDB), not here. */
var CACHE = "twin-{{ version }}";
var SHELL = [{% for url in shell %}"{{ url|escapejs }}"{% if not forloop.last %}, {% endif %}{% endfor %}];

self.addEventListener("install", function (event) {
  event.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL); }).then(function () {
    return self.skipWaiting();
  }));
});

self.addEventListener("activate", function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches["delete"](k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (event) {
  var req = event.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.indexOf("/admin/") === 0) { return; }
  if (req.mode === "navigate") {
    // Network first; keep a copy of each page you view; offline: last copy, else the offline page.
    event.respondWith(fetch(req).then(function (resp) {
      if (resp.ok) { var copy = resp.clone(); caches.open(CACHE).then(function (c) { c.put(req, copy); }); }
      return resp;
    })["catch"](function () {
      return caches.match(req).then(function (hit) { return hit || caches.match("{{ offline_url|escapejs }}"); });
    }));
    return;
  }
  // Static assets: cache first.
  event.respondWith(caches.match(req).then(function (hit) {
    return hit || fetch(req).then(function (resp) {
      if (resp.ok) { var copy = resp.clone(); caches.open(CACHE).then(function (c) { c.put(req, copy); }); }
      return resp;
    });
  }));
});
