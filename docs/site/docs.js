/* isitmyisp docs: an improvement, not a requirement. Without this file the search page is a full
   index you search with the browser's find (Ctrl+F), and Alt+K (the link's accesskey) leads to it.
   With it: Ctrl+K / Cmd+K from any page, and the index filters itself as you type. */
(function () {
  "use strict";
  var link = document.querySelector(".search-link");
  if (!link) return;
  var mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  var kbd = link.querySelector("kbd");
  kbd.textContent = mac ? "⌘ K" : "Ctrl K";
  kbd.hidden = false;
  link.setAttribute("aria-keyshortcuts", mac ? "Meta+K" : "Control+K");

  var input = document.getElementById("q");
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (input) { input.focus(); input.select(); } else { location.href = link.href; }
    }
  });
  if (!input) return;

  // the search page
  var form = input.form, count = document.getElementById("search-count");
  var items = Array.prototype.slice.call(document.querySelectorAll("#search-index li"));
  var groups = Array.prototype.slice.call(document.querySelectorAll("#search-index section"));
  var index = document.getElementById("search-index");
  form.hidden = false;
  function fold(s) { return s.normalize("NFD").replace(/[\u0300-\u036f]|-/g, "").toLowerCase(); }  // as build_docs.fold
  function visible() {   // in the order shown (run() moves the best pages up)
    return Array.prototype.slice.call(index.querySelectorAll("section:not([hidden]) li:not([hidden]) > a"));
  }
  var terms = [];
  function has(text) { return terms.every(function (w) { return text.indexOf(w) !== -1; }); }
  function run() {
    var q = input.value.trim(), n = 0;
    terms = fold(q).split(/\s+/).filter(Boolean);
    items.forEach(function (li) {
      li.hidden = !has(li.getAttribute("data-t"));
      if (!li.hidden) n++;
    });
    // pages whose section titles say it go first; otherwise the docs' own order
    var rank = groups.map(function (g, i) {
      var titled = Array.prototype.some.call(g.querySelectorAll("li:not([hidden]) b"), function (b) { return has(fold(b.textContent)); });
      g.hidden = !g.querySelector("li:not([hidden])");
      return { g: g, key: (titled && terms.length ? 0 : 1000) + i };
    });
    rank.sort(function (a, b) { return a.key - b.key; }).forEach(function (r) { index.appendChild(r.g); });
    count.hidden = !terms.length;
    count.textContent = !n ? count.dataset.none.replace("{q}", q)
      : n === 1 ? count.dataset.one : count.dataset.n.replace("{n}", n);
    try { history.replaceState(null, "", q ? "?q=" + encodeURIComponent(q) : location.pathname); } catch (err) { /* file:// */ }
  }
  input.value = new URLSearchParams(location.search).get("q") || "";
  input.addEventListener("input", run);
  form.addEventListener("submit", function (e) {   // Enter: the first result whose title says it, else the first
    e.preventDefault();
    var links = visible(), first = links.filter(function (a) { return has(fold(a.querySelector("b").textContent)); })[0] || links[0];
    if (first) location.href = first.href;
  });
  // arrows move between the results; Esc clears
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && document.activeElement === input && input.value) { input.value = ""; run(); return; }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    var links = visible(), i = links.indexOf(document.activeElement);
    if (document.activeElement !== input && i === -1) return;
    e.preventDefault();
    if (e.key === "ArrowDown") (links[i + 1] || links[i] || input).focus();
    else if (i <= 0) input.focus(); else links[i - 1].focus();
  });
  run();
  input.focus();
})();
