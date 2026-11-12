# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **The owner of a small business** (shop, office, clinic, public office) in Jujuy, Argentina, where the internet is the till, the card terminal, the phones and the e-invoicing. They are not technical. They open the dashboard when "internet is slow" or when they need to claim to the ISP, and they want one answer: whose fault is it, and what do I do.
- **The technician** who installs and looks after it (the author, selling it as a service; later, other IT providers). Reads the detail, the evidence, the tunnels and the TV board on a wall screen.
- **The ISP's support and NOC**, indirectly: they receive the evidence report and must not be able to wave it away.

## Product Purpose

A self-hosted monitor that tells whether a connection problem is the Wi-Fi, the router or the ISP, says it in plain language, and builds the evidence the ISP needs to escalate a ticket. Success: a non-technical owner understands the verdict in a second, and an ISP accepts the report.

## Positioning

Built by someone who worked in an ISP's NOC. The verdict is statistical and honest: it needs ICMP and TCP to agree, ignores ICMP deprioritisation, judges latency against each target's own baseline, and every ISP incident lists what the evidence rules out and what it can't. Colour means responsibility (your side / your ISP / others), not good or bad.

## Operating Context

- Runs on a Raspberry Pi or mini PC wired to the router, for months. One site, one or two links (backup link detection).
- The dashboard is opened from a desktop or a phone, in a shop or office in daylight; the TV board runs on a wall screen all day.
- Business hours matter: downtime while open counts more than downtime at night.
- Evidence is a printed or PDF report attached to a claim.

## Capabilities and Constraints

- No JavaScript anywhere in the UI, strict CSP (no scripts, styles from self). Charts are SVG with CSS-only hover.
- Spanish first (rioplatense voseo), English second. Both must fit.
- Light and dark themes are both required (user decision); the TV board is a dark, dense NOC screen.
- Self-hosted fonts only (font-src 'self').
- The responsibility palette (good / you / ISP / other) was validated for colour-vision deficiency and carries meaning; it must stay distinct from any brand colour.

## Brand Commitments

- Name: isitmyisp. Logo: three nodes on a line (your network, ISP, internet), in docs/brand/.
- Voice: plain, direct, honest; never over-claims; says what it can't know.
- Visual reference pinned by the user: a monitoring dashboard with an icon sidebar (active item filled blue), a status pill, a verdict card with a large status icon, KPI cards with sparklines and change, and cards for the chart, destinations and events, in light and dark with a theme button. The user rejected a top-bar "technical report" direction and amber alert-style banners.

## Evidence on Hand

- Synthetic demo data (isitmyisp/demo.py), clearly labelled as such; the public demo at isitmyisp.enzo-meneghini.com.
- No real customers, testimonials or benchmarks yet: never invent them.

## Product Principles

1. One answer first: whose fault, and what to do. Everything else is evidence below it.
2. Honest over impressive: show what was measured and what wasn't.
3. Colour is reserved for responsibility and state.
4. Built for the counter and the wall: legible from a distance, in daylight.
5. Nothing decorative that a technician would call fake.

## Accessibility & Inclusion

Colour is never the only signal (text and icon always accompany it). Contrast for daylight use; keyboard focus visible; works at 375 px.
