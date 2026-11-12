/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Offline queue for check-in forms (M4-T4). Progressive enhancement: without this
   script the forms post normally. With it, a check-in that cannot reach the
   instance is kept in IndexedDB on this phone and sent when the instance is
   reachable again. The server stores each record once (same content = same CID),
   so a replay that already arrived is answered "already saved".
   Replay rules: each send first fetches a current CSRF token (Django rotates it at
   login); a permanent refusal (invalid, stale correction, gone) marks that item with
   its reason and the queue moves on; no connection or a logged-out session stops the
   queue until the next try (every minute, when the app is shown again, or when the
   phone comes online). Logout deletes the saved pages; unsent check-ins stay and are
   sent after the next login. */
(function () {
  "use strict";
  if (!("indexedDB" in window) || !window.fetch || !window.Promise) { return; }

  var DB = "twin-offline", STORE = "queue", RETRY_MS = 60000;

  function open() {
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB, 1);
      req.onupgradeneeded = function () { req.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true }); };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function tx(mode, fn) {
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        var t = db.transaction(STORE, mode), req = fn(t.objectStore(STORE));
        t.oncomplete = function () { resolve(req && req.result); };
        t.onerror = function () { reject(t.error); };
      });
    });
  }

  function all() { return tx("readonly", function (s) { return s.getAll(); }).then(function (r) { return r || []; }); }
  function add(item) { return tx("readwrite", function (s) { return s.add(item); }); }
  function remove(id) { return tx("readwrite", function (s) { return s["delete"](id); }); }
  function put(item) { return tx("readwrite", function (s) { return s.put(item); }); }

  function status(text) {
    var el = document.getElementById("queue-status");
    if (!el) { return; }
    el.textContent = text;
    el.hidden = !text;
  }

  function describe(items, note) {
    var waiting = items.filter(function (i) { return !i.error; }).length;
    var parts = [];
    if (waiting) { parts.push(waiting + " check-in(s) saved on this phone, waiting to be sent."); }
    items.filter(function (i) { return i.error; }).forEach(function (i) {
      parts.push(i.label + " (saved " + i.queued.slice(0, 16).replace("T", " ") + ") could not be saved: " + i.error);
    });
    if (note && waiting) { parts.push(note); }
    return parts.join(" ");
  }

  function readJson(resp) {
    return resp.json().then(function (d) { return d || {}; }, function () { return {}; });
  }

  function freshToken() {
    return fetch("/csrf-token/", { credentials: "same-origin", headers: { "X-Offline-Replay": "queue" } })
      .then(function (resp) {
        if (!resp.ok || (resp.headers.get("Content-Type") || "").indexOf("application/json") !== 0) {
          throw { stop: "login" };
        }
        return readJson(resp).then(function (d) { return d.token; });
      });
  }

  function withToken(body, token) {
    var params = new URLSearchParams(body);
    params.set("csrfmiddlewaretoken", token);
    return params.toString();
  }

  /* Resolves "sent" or "failed" (permanent, item marked); rejects {stop: "network"|"login"}. */
  function send(item) {
    return freshToken().then(function (token) {
      return fetch(item.url, {
        method: "POST", body: withToken(item.body, token), credentials: "same-origin", redirect: "manual",
        headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Offline-Replay": "queue" }
      });
    }, function (err) { throw (err && err.stop) ? err : { stop: "network" }; })
      .then(function (resp) {
        if (resp.status === 200) { return remove(item.id).then(function () { return "sent"; }); }
        if (resp.status === 403 || resp.type === "opaqueredirect" || resp.status === 0) { throw { stop: "login" }; }
        if (resp.status >= 500) { throw { stop: "network" }; }  // the instance had a problem: try again later
        return readJson(resp).then(function (d) {
          item.error = d.message || ("the instance refused it (HTTP " + resp.status + ").");
          return put(item).then(function () { return "failed"; });
        });
      }, function (err) { throw (err && err.stop) ? err : { stop: "network" }; });
  }

  var flushing = false;
  function flush() {
    if (flushing) { return Promise.resolve(); }
    flushing = true;
    var note = "";
    return all().then(function (items) {
      var chain = Promise.resolve();
      items.filter(function (i) { return !i.error; }).forEach(function (item) {
        chain = chain.then(function () { return send(item); });
      });
      return chain;
    }).then(null, function (err) {
      note = err && err.stop === "login" ? "Log in again to send them." : "They will be sent when the instance is reachable.";
    }).then(all).then(function (items) { status(describe(items, note)); })
      .then(function () { flushing = false; }, function () { flushing = false; });
  }

  function nativeSubmit(form) {
    // Let the browser post the form itself (server-rendered errors, or the login page).
    form.removeAttribute("data-offline");
    HTMLFormElement.prototype.submit.call(form);
  }

  function onSubmit(event) {
    var form = event.target;
    if (!form.matches) { return; }
    if (form.matches("form[data-logout]")) { return onLogout(event, form); }
    if (!form.matches("form[data-offline]")) { return; }
    event.preventDefault();
    var body = new URLSearchParams(new FormData(form)).toString();
    var item = { url: form.getAttribute("action") || location.pathname, body: body,
                 label: form.getAttribute("data-offline"), queued: new Date().toISOString() };
    fetch(item.url, {
      method: "POST", body: body, credentials: "same-origin", redirect: "manual",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Offline-Replay": "live" }
    }).then(function (resp) {
      if (resp.status === 200) {
        return readJson(resp).then(function (d) {
          if (d.redirect) { location.href = d.redirect; } else { nativeSubmit(form); }
        });
      }
      nativeSubmit(form);  // field errors, stale, logged out, server error: let the server render it
    }, function () {
      // No connection to the instance: keep it on this phone.
      add(item).then(all).then(function (items) { status(describe(items)); });
      var note = document.createElement("p");
      note.className = "msg";
      note.setAttribute("role", "status");
      note.textContent = item.label + " saved on this phone. It will be sent when the instance is reachable.";
      form.parentNode.insertBefore(note, form);
      form.reset();
    });
  }

  function onLogout(event, form) {
    // Delete saved pages (they hold health data); keep unsent check-ins for the next login.
    if (navigator.serviceWorker && navigator.serviceWorker.controller) {
      navigator.serviceWorker.controller.postMessage({ type: "purge-pages" });
    }
    if (window.caches) {
      event.preventDefault();
      caches.keys().then(function (keys) {
        return Promise.all(keys.map(function (k) {
          return caches.open(k).then(function (c) {
            return c.keys().then(function (reqs) {
              return Promise.all(reqs.filter(function (r) {
                return new URL(r.url).pathname.indexOf("/static/") !== 0;
              }).map(function (r) { return c["delete"](r); }));
            });
          });
        }));
      }).then(function () { HTMLFormElement.prototype.submit.call(form); },
              function () { HTMLFormElement.prototype.submit.call(form); });
    }
  }

  document.addEventListener("submit", onSubmit);
  window.addEventListener("online", flush);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) { flush(); } });
  setInterval(flush, RETRY_MS);
  if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("/sw.js").then(null, function () { /* the app still works without it */ });
  }
  flush();
}());
