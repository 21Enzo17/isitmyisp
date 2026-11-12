---
version: 1
slug: "isitmyisp-webapp-templates-dashboard-html"
primary_target: "isitmyisp/webapp/templates/dashboard.html"
related_targets: ["isitmyisp/webapp/templates/base.html","isitmyisp/webapp/static/style.css"]
---

# Dashboard (and the app shell)

Mode: Operate. Visitor: the shop owner (one answer, in a second) and the technician (the evidence below it). Must keep: no JavaScript, strict CSP, the responsibility colours, every fact the page shows.

## Direction contract

seed: none (pinned). The user pinned a reference image (a monitoring dashboard with sidebar, KPI cards and cards for chart, destinations and events, in light and dark) after rejecting a "technical report" direction with a top bar. Follow the reference's design, not its content.

THESIS: a familiar, polished monitoring app: the verdict and three figures first, then cards. Convention is the commitment, executed at full craft.

OWN-WORLD: blue accent (#2563eb light, #2f6bff dark); light = #f4f6fb ground and white cards with a soft shadow; dark = deep navy ground and navy cards with hairline borders. 14 px card corners, 12 px controls. Sidebar with icons, the active item filled. Status colours only for state (green, orange, red), never as page decoration; no amber banners.

STORY: status pill and theme button; verdict with a large status icon beside availability, time without outages and latency (each with a sparkline and change vs the day before); where the problem is (the path); the 24 h chart, destinations and latest events; calls, link and services.

FIRST VIEWPORT: status pill, verdict card with icon, three KPI cards, the path card.

SIGNATURE: the KPI row with real sparklines and day-over-day change.

REACH: the other pages, the TV board and the docs take the same palette and card language next.
