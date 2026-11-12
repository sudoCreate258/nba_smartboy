/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Offline queue for check-in forms (M4-T4). Progressive enhancement: without this
   script the forms post normally. With it, a check-in that cannot reach the
   instance is kept in IndexedDB on this phone and sent when the instance is
   reachable again. The server stores each record once (same content = same CID),
   so a replay that already arrived is answered "already saved". */
(function () {
  "use strict";
  if (!("indexedDB" in window) || !window.fetch) { return; }

  var DB = "twin-offline", STORE = "queue";

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
        var t = db.transaction(STORE, mode), store = t.objectStore(STORE), out = fn(store);
        t.oncomplete = function () { resolve(out && out.result !== undefined ? out.result : out); };
        t.onerror = function () { reject(t.error); };
      });
    });
  }

  function all() { return tx("readonly", function (s) { return s.getAll(); }); }
  function add(item) { return tx("readwrite", function (s) { s.add(item); }); }
  function remove(id) { return tx("readwrite", function (s) { s["delete"](id); }); }
  function put(item) { return tx("readwrite", function (s) { s.put(item); }); }

  function status(text) {
    var el = document.getElementById("queue-status");
    if (!el) { return; }
    el.textContent = text;
    el.hidden = !text;
  }

  function describe(items) {
    var waiting = items.filter(function (i) { return !i.error; }).length;
    var failed = items.filter(function (i) { return i.error; });
    var parts = [];
    if (waiting) { parts.push(waiting + " check-in(s) saved on this phone, waiting to be sent."); }
    failed.forEach(function (i) { parts.push(i.label + " could not be saved: " + i.error + " Enter it again."); });
    return parts.join(" ");
  }

  function send(item) {
    return fetch(item.url, {
      method: "POST", body: item.body, credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Offline-Replay": "queue" }
    }).then(function (resp) {
      if (resp.status === 403) { throw new Error("login"); }
      return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
    });
  }

  var flushing = false;
  function flush() {
    if (flushing) { return Promise.resolve(); }
    flushing = true;
    return all().then(function (items) {
      var chain = Promise.resolve();
      items.filter(function (i) { return !i.error; }).forEach(function (item) {
        chain = chain.then(function () {
          return send(item).then(function (r) {
            if (r.ok) { return remove(item.id); }
            item.error = (r.data && r.data.message) || "the instance rejected it.";
            return put(item);
          });
        });
      });
      return chain;
    }).then(all).then(function (items) { status(describe(items)); })
      .catch(function (err) {
        all().then(function (items) {
          status(describe(items) + (err && err.message === "login" ? " Log in again to send them." : ""));
        });
      })
      .then(function () { flushing = false; });
  }

  function nativeSubmit(form) {
    // Let the browser post the form itself (server-rendered errors, or the login page).
    form.removeAttribute("data-offline");
    HTMLFormElement.prototype.submit.call(form);
  }

  function onSubmit(event) {
    var form = event.target;
    if (!form.matches || !form.matches("form[data-offline]")) { return; }
    event.preventDefault();
    var body = new URLSearchParams(new FormData(form)).toString();
    var item = { url: form.action || location.pathname, body: body, label: form.getAttribute("data-offline"),
                 queued: new Date().toISOString() };
    fetch(item.url, {
      method: "POST", body: body, credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Offline-Replay": "live" }
    }).then(function (resp) {
      if (resp.status === 200) {
        return resp.json().then(function (data) { location.href = data.redirect; },
                                function () { nativeSubmit(form); });
      }
      nativeSubmit(form);  // 400 (field errors) or 403 (logged out): nothing was stored
    }, function () {
      // Offline or unreachable: keep it on this phone.
      add(item).then(all).then(function (items) { status(describe(items)); });
      var note = document.createElement("p");
      note.className = "msg";
      note.setAttribute("role", "status");
      note.textContent = item.label + " saved on this phone. It will be sent when the instance is reachable.";
      form.parentNode.insertBefore(note, form);
      form.reset();
    });
  }

  document.addEventListener("submit", onSubmit);
  window.addEventListener("online", flush);
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(function () { /* still works without it */ });
  }
  flush();
}());
