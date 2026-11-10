"""User-facing strings (English / Spanish)."""

from __future__ import annotations

import os

MSG = {
    "en": {
        "ok": "✅ Your connection looks healthy.",
        "local": "🏠 The problem is on YOUR side: between this device and your router(s).",
        "access": "📡 The problem is in your ISP's access network (its first hop after your router).",
        "isp": "🌐 The problem is inside your ISP's network or its upstream: every destination is affected.",
        "remote": "🎯 Only some destinations are affected: that's not your ISP's fault.",
        "dns": "🔤 Pings and connections are fine, but your DNS resolver is failing or slow.",
        "no_data": "❔ Not enough data yet.",
        "wifi": "You are measuring over Wi-Fi. Plug in a cable to rule out the Wi-Fi itself.",
        "wifi_latency": "High latency to your own router over Wi-Fi: interference or weak signal is likely.",
        "isp_hop_icmp": "Your ISP's first hop drops ICMP replies to itself, but traffic through it is fine. That is NOT loss.",
        "icmp_only": "Some anchors lose ICMP but TCP connections to them are fine: ICMP is being deprioritized, not real loss.",
        "dns_partial": "One of your DNS resolvers is failing; the others are fine.",
        "jitter": "High jitter: calls and games may suffer even without packet loss.",
        "measuring": "Measuring for {s}s",
        "net": "Network", "gateway": "Gateway (your router)", "iface": "Interface", "wireless": "Wi-Fi",
        "wired": "cable", "dns_srv": "DNS servers", "pubip": "Public IPv4", "isp_name": "ISP", "isphop": "ISP first hop",
        "cgnat": "CGNAT", "yes": "yes", "no": "no", "dnat": "Double NAT", "ipv6": "IPv6",
        "v6works": "working", "v6none": "not available", "v6broken": "public address present but not working",
        "engine": "Probe engine",
        "target": "Target", "role": "Role", "loss": "Loss", "med": "Median", "jit": "Jitter",
        "hop_ok": "ok", "hop_real": "REAL LOSS", "hop_icmp": "ignored (ICMP deprioritized)", "hop_none": "no reply",
        "seg_home": "home", "seg_isp": "ISP", "seg_beyond": "beyond",
        "path_ok": "Destination reached with {l}% loss: the path is fine. Loss on intermediate hops is ICMP handling, not real loss.",
        "path_bad": "Real loss of {l}% reaching the destination. It starts at hop {h} ({host}{asn}).",
        "path_unreach": "The destination did not answer.",
        "cgnat_warn": "You are behind CGNAT ({hops}): port forwarding and hosting from home will not work over IPv4.",
        "dnat_warn": "Double NAT ({hops}): you have a router behind another router. Port forwarding needs to be set on both.",
        "asn_hint": "Tip: run `isitmyisp update-asn` once to show ISP names offline (downloads a public dataset, no per-IP queries).",
        "asn_downloading": "Downloading the public IP-to-ASN dataset from iptoasn.com…",
        "asn_done": "Saved to {p}. ASN lookups are now offline.",
        "opened": "⚠️  Incident opened", "closed": "✅ Incident closed", "rediscover": "🔄 Network changed, re-discovering",
        "stop_hint": "(Ctrl+C to stop)",
    },
    "es": {
        "ok": "✅ Tu conexión se ve sana.",
        "local": "🏠 El problema está de TU lado: entre este equipo y tu(s) router(s).",
        "access": "📡 El problema está en la red de acceso de tu ISP (su primer salto después de tu router).",
        "isp": "🌐 El problema está dentro de la red de tu ISP o en su salida: afecta a todos los destinos.",
        "remote": "🎯 Solo algunos destinos fallan: no es culpa de tu ISP.",
        "dns": "🔤 Los pings y las conexiones andan bien, pero tu servidor DNS falla o está lento.",
        "no_data": "❔ Todavía no hay datos suficientes.",
        "wifi": "Estás midiendo por Wi-Fi. Conectate por cable para descartar el Wi-Fi.",
        "wifi_latency": "Latencia alta hacia tu propio router por Wi-Fi: probablemente interferencia o señal débil.",
        "isp_hop_icmp": "El primer salto de tu ISP descarta respuestas ICMP a sí mismo, pero el tráfico que pasa por él está bien. NO es pérdida.",
        "icmp_only": "Algunos destinos pierden ICMP pero las conexiones TCP a ellos andan bien: el ICMP está despriorizado, no es pérdida real.",
        "dns_partial": "Uno de tus servidores DNS falla; los demás andan bien.",
        "jitter": "Jitter alto: las llamadas y los juegos pueden sufrir aunque no haya pérdida.",
        "measuring": "Midiendo durante {s}s",
        "net": "Red", "gateway": "Gateway (tu router)", "iface": "Interfaz", "wireless": "Wi-Fi",
        "wired": "cable", "dns_srv": "Servidores DNS", "pubip": "IPv4 pública", "isp_name": "ISP", "isphop": "Primer salto del ISP",
        "cgnat": "CGNAT", "yes": "sí", "no": "no", "dnat": "Doble NAT", "ipv6": "IPv6",
        "v6works": "funciona", "v6none": "no disponible", "v6broken": "hay dirección pública pero no funciona",
        "engine": "Motor de sondeo",
        "target": "Destino", "role": "Rol", "loss": "Pérdida", "med": "Mediana", "jit": "Jitter",
        "hop_ok": "ok", "hop_real": "PÉRDIDA REAL", "hop_icmp": "ignorado (ICMP despriorizado)", "hop_none": "no responde",
        "seg_home": "casa", "seg_isp": "ISP", "seg_beyond": "afuera",
        "path_ok": "El destino llega con {l}% de pérdida: el camino está bien. La pérdida en saltos intermedios es manejo de ICMP, no pérdida real.",
        "path_bad": "Pérdida real de {l}% hasta el destino. Empieza en el salto {h} ({host}{asn}).",
        "path_unreach": "El destino no respondió.",
        "cgnat_warn": "Estás detrás de CGNAT ({hops}): por IPv4 no vas a poder abrir puertos ni publicar servicios desde tu casa.",
        "dnat_warn": "Doble NAT ({hops}): tenés un router detrás de otro. Para abrir puertos hay que configurarlo en los dos.",
        "asn_hint": "Tip: corré `isitmyisp update-asn` una vez para ver los nombres de los ISP sin conexión (baja un dataset público, sin consultas por IP).",
        "asn_downloading": "Descargando el dataset público IP→ASN de iptoasn.com…",
        "asn_done": "Guardado en {p}. Las consultas de ASN ahora son offline.",
        "opened": "⚠️  Incidente abierto", "closed": "✅ Incidente cerrado", "rediscover": "🔄 La red cambió, re-descubriendo",
        "stop_hint": "(Ctrl+C para detener)",
    },
}


def pick(arg: str | None) -> dict[str, str]:
    if arg in MSG:
        return MSG[arg]
    env = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    return MSG["es" if env.lower().startswith("es") else "en"]
