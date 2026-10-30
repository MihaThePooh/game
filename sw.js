/* Service worker игры: ставит её на телефон приложением и даёт играть без
   сети. Игра — один файл, так что кэшировать почти нечего.
   Сеть вперёд, кэш запасной: обновления приходят сами, последняя версия
   работает офлайн. */
var CACHE = 'run-v4';
// run-N.js — скрипты страницы, их выносит scripts/stage.py: без них офлайн нечем играть.
var SHELL = ['./', 'run-1.js', 'run-2.js', 'icons/icon-192.png', 'icons/icon-512.png'];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) { return c.addAll(SHELL); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(names.map(function (n) {
        return n === CACHE ? null : caches.delete(n);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  var url = new URL(e.request.url);
  // Сохранение на сервере — всегда свежее, из кэша его не отдавать.
  if (e.request.method !== 'GET' || url.origin !== self.location.origin ||
      url.pathname.indexOf('/api/') === 0) { return; }
  e.respondWith(
    fetch(e.request).then(function (res) {
      var copy = res.clone();
      caches.open(CACHE).then(function (c) { c.put(e.request, copy); });
      return res;
    }).catch(function () {
      return caches.match(e.request).then(function (hit) {
        return hit || caches.match('./');
      });
    })
  );
});
