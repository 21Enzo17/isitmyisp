// "Check from this device": measure from this PC or phone for ~15 s and hand the numbers to the probe,
// which compares them with its own windows of the same minutes and stores the result (#66).
//
// Optional, like chart.js: the page says what it needs without it. It talks only to the probe that
// served it and, for the internet part, to the anchors set in Settings (HTTPS, no-cors: nothing is
// read from them, only how long they take to answer). No cookies or storage of its own.
(function () {
  "use strict";
  var box = document.getElementById("dev-run");
  var btn = document.getElementById("dev-start");
  if (!box || !btn || !window.fetch || !window.performance) return;
  document.documentElement.classList.add("js");
  var bar = document.getElementById("dev-progress"), step = document.getElementById("dev-step");
  var steps = (box.dataset.steps || "").split("|");
  var anchors = (box.dataset.anchors || "").split(" ").filter(Boolean);

  function now() { return performance.now(); }
  function show(i, pct) { step.textContent = steps[i] || ""; bar.value = pct; }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  // one request, timed; null if it failed or took longer than `limit` ms
  function timed(url, opts, limit) {
    var ctl = new AbortController(), t0 = now();
    var timer = setTimeout(function () { ctl.abort(); }, limit);
    opts = Object.assign({cache: "no-store", signal: ctl.signal, credentials: "same-origin"}, opts || {});
    return fetch(url, opts).then(function (r) {
      return (opts.mode === "no-cors" ? Promise.resolve() : r.arrayBuffer()).then(function () {
        clearTimeout(timer);
        return opts.mode === "no-cors" || r.ok ? now() - t0 : null;
      });
    }).catch(function () { clearTimeout(timer); return null; });
  }

  async function lan() {
    var out = [];
    for (var i = 0; i < 20; i++) {
      out.push(await timed(box.dataset.ping + "?n=" + i, {}, 2000));
      bar.value = 2 + i;
      await sleep(150);
    }
    return out;
  }

  // download then upload: a small transfer to size a bigger one of about 1.5 s
  async function transfer(up) {
    var mbps = null, size = 1 << 20;
    for (var round = 0; round < 2; round++) {
      var ms;
      if (up) {
        ms = await timed(box.dataset.up, {method: "POST", body: new Blob([new Uint8Array(size)]),
          headers: {"X-CSRFToken": box.dataset.csrf, "Content-Type": "application/octet-stream"}}, 15000);
      } else {
        ms = await timed(box.dataset.down + "?bytes=" + size, {}, 15000);
      }
      if (ms === null) return mbps;
      mbps = size * 8 / (ms / 1000) / 1e6;
      size = Math.min(64 << 20, Math.max(1 << 20, Math.round(mbps * 1e6 / 8 * 1.5)));
    }
    return mbps;
  }

  async function internet() {
    var out = {};
    for (var round = 0; round < 6; round++) {
      await Promise.all(anchors.map(function (a) {
        return timed("https://" + a + "/?isitmyisp=" + round + "-" + Date.now(), {mode: "no-cors", credentials: "omit"}, 4000)
          .then(function (ms) { (out[a] = out[a] || []).push(ms); });
      }));
      bar.value = 70 + round * 4;
      await sleep(300);
    }
    for (var a in out) out[a].shift();   // the first one pays for the TLS handshake
    return out;
  }

  btn.addEventListener("click", async function () {
    btn.disabled = true;
    bar.hidden = false;
    var t0 = now();
    try {
      show(0, 1);
      var res = {lan: await lan()};
      show(1, 25);
      res.down_mbps = await transfer(false);
      show(2, 45);
      res.up_mbps = await transfer(true);
      show(3, 65);
      res.inet = await internet();
      show(4, 95);
      res.seconds = (now() - t0) / 1000;
      var r = await fetch(box.dataset.result, {method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRFToken": box.dataset.csrf}, body: JSON.stringify(res)});
      if (!r.ok) throw new Error(r.status);
      window.location.assign((await r.json()).url);
    } catch (e) {
      step.textContent = box.dataset.failed;
      bar.hidden = true;
      btn.disabled = false;
    }
  });
})();
