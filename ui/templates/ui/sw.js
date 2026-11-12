/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Service worker (M4-T4): caches the app shell and the pages you view, so they
   load without a connection. Only same-origin GETs are cached; nothing is ever
   fetched from another host. Never cached: the admin, the API, the data download,
   the CSRF token, logout, and any response marked no-store. On logout the page
   copies are deleted (offline.js posts "purge-pages"). Check-ins made offline are
   queued by offline.js (IndexedDB), not here.
   Browsers only run service workers on secure (HTTPS) origins or on localhost, so in
   plain-HTTP LAN mode this file is not used; with LAN HTTPS (M6) it is. */
var CACHE = "twin-{{ version }}";
var SHELL = [{% for url in shell %}"{{ url|escapejs }}"{% if not forloop.last %}, {% endif %}{% endfor %}];
var OFFLINE = "{{ offline_url|escapejs }}";
var NEVER = ["/admin/", "/api/", "/my-data/", "/csrf-token/", "/logout/", "/sw.js", "/permissions/", "/statement/"];

function never(path) {
  return NEVER.some(function (prefix) { return path.indexOf(prefix) === 0; });
}

function storable(resp) {
  var cc = resp.headers.get("Cache-Control") || "", type = resp.headers.get("Content-Type") || "";
  return resp.ok && cc.indexOf("no-store") === -1 && type.indexOf("text/html") === 0
    && !resp.headers.get("Content-Disposition");
}

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

self.addEventListener("message", function (event) {
  if (!event.data || event.data.type !== "purge-pages") { return; }
  // Keep the shell (CSS, script, icons, offline page, manifest); delete every saved page.
  event.waitUntil(caches.open(CACHE).then(function (c) {
    return c.keys().then(function (reqs) {
      return Promise.all(reqs.filter(function (r) {
        return SHELL.indexOf(new URL(r.url).pathname) === -1;
      }).map(function (r) { return c["delete"](r); }));
    });
  }));
});

self.addEventListener("fetch", function (event) {
  var req = event.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || never(url.pathname)) { return; }
  if (req.mode === "navigate") {
    // Network first; keep a copy of each HTML page you view; offline: last copy, else the offline page.
    event.respondWith(fetch(req).then(function (resp) {
      if (storable(resp)) { var copy = resp.clone(); caches.open(CACHE).then(function (c) { c.put(req, copy); }); }
      return resp;
    })["catch"](function () {
      return caches.match(req).then(function (hit) { return hit || caches.match(OFFLINE); });
    }));
    return;
  }
  if (url.pathname.indexOf("/static/") !== 0 && url.pathname !== "{{ manifest_url|escapejs }}") { return; }
  // Static assets and the manifest: cache first.
  event.respondWith(caches.match(req).then(function (hit) {
    return hit || fetch(req).then(function (resp) {
      if (resp.ok) { var copy = resp.clone(); caches.open(CACHE).then(function (c) { c.put(req, copy); }); }
      return resp;
    });
  }));
});
