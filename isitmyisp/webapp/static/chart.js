// Drag across the enlarged chart to zoom into that stretch; double-click to zoom out.
//
// The only script in isitmyisp, and optional: without it the chart still zooms and moves with plain
// links (buttons, and a click on a column). It reads the view's range from data attributes, measures
// nothing, stores nothing and talks to no one; it only builds the link of the stretch you selected.
(function () {
  "use strict";
  var box = document.querySelector(".zoomable");
  if (!box) return;
  document.documentElement.classList.add("js");
  var cols = box.querySelector(".hv");
  var sel = box.querySelector(".drag-sel");
  if (!cols || !sel) return;

  var start = +box.dataset.start, end = +box.dataset.end, now = +box.dataset.now, first = +box.dataset.first;
  var who = box.dataset.who || "";
  var grid = box.dataset.grid ? box.dataset.grid.split(",") : null;   // the static demo: only these views exist
  var SPANS = {"15m": 900, "1h": 3600, "3h": 10800, "6h": 21600, "12h": 43200, "24h": 86400,
               "2d": 172800, "7d": 604800, "30d": 2592000};
  var MIN_RANGE = 300;
  var x0 = null, dragged = false;

  function tsAt(clientX) {
    var r = cols.getBoundingClientRect();
    var f = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    return start + f * (end - start);
  }

  function place(a, b) {
    var r = cols.getBoundingClientRect(), outer = box.getBoundingClientRect();
    var left = Math.min(a, b), right = Math.max(a, b);
    left = Math.max(left, r.left); right = Math.min(right, r.right);
    sel.style.left = (left - outer.left) + "px";
    sel.style.width = Math.max(0, right - left) + "px";
    sel.style.top = (r.top - outer.top) + "px";
    sel.style.height = r.height + "px";
  }

  function target(a, b) {
    if (b - a < MIN_RANGE) { var m = (a + b) / 2; a = m - MIN_RANGE / 2; b = m + MIN_RANGE / 2; }
    if (!grid) {                                   // the app: any from/to range
      var q = "from=" + Math.floor(a) + "&to=" + Math.ceil(b) + (who ? "&who=" + encodeURIComponent(who) : "");
      return box.dataset.base + "?" + q;
    }
    // the static demo: the smallest pre-rendered view that holds the selection
    var mid = (a + b) / 2, len = b - a;
    var spans = grid.filter(function (s) { return SPANS[s] >= len; });
    var span = spans.length ? spans[0] : grid[grid.length - 1], size = SPANS[span];
    var k = Math.max(0, Math.floor((now - mid) / size));
    if (now - k * size <= first) k = Math.max(0, k - 1);
    var path = location.pathname, i = path.indexOf("/chart/");
    var base = path.slice(0, i + 7) + (who ? who + "/" : "");
    return base + span + "-" + k + "/";
  }

  cols.addEventListener("pointerdown", function (e) {
    if (e.button !== 0) return;
    e.preventDefault();                            // no text selection, no native drag of the column's link
    x0 = e.clientX; dragged = false;
    cols.setPointerCapture(e.pointerId);
  });
  // the columns are links: dragging one would start the browser's own "drag a link" and cancel ours
  cols.addEventListener("dragstart", function (e) { e.preventDefault(); });
  cols.addEventListener("pointermove", function (e) {
    if (x0 === null) return;
    if (!dragged && Math.abs(e.clientX - x0) < 6) return;
    dragged = true;
    sel.hidden = false;
    box.classList.add("dragging");
    place(x0, e.clientX);
  });
  cols.addEventListener("pointerup", function (e) {
    if (x0 === null) return;
    var a = tsAt(Math.min(x0, e.clientX)), b = tsAt(Math.max(x0, e.clientX));
    if (Math.abs(e.clientX - x0) >= 6) dragged = true;   // even if no move event came in between
    x0 = null;
    if (!dragged) return;                          // a plain click: nothing (see the click handler)
    box.classList.remove("dragging");
    location.href = target(a, b);
  });
  cols.addEventListener("pointercancel", function () {
    x0 = null; dragged = false; sel.hidden = true; box.classList.remove("dragging");
  });
  // with the script, zooming in is dragging (like Grafana): a plain click on a column stays put, so a
  // double-click can zoom out; without it, each column is a link that zooms in
  cols.addEventListener("click", function (e) { e.preventDefault(); dragged = false; }, true);
  box.addEventListener("dblclick", function (e) {
    var out = document.querySelector(".chart-nav a.z-out");
    if (out) { e.preventDefault(); location.href = out.href; }
  });
})();
