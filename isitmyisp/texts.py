"""Plain-language texts shared by the web UI and the alerts (no web dependencies here)."""

from __future__ import annotations

VERDICT = {
    "en": {"ok": "Healthy", "local": "Problem on your side", "access": "ISP access network problem",
           "isp": "ISP backbone / upstream problem", "remote": "Only some destinations affected",
           "dns": "DNS problem", "no_data": "No data", "stale": "Monitor not reporting",
           "config": "Tunnel down: configuration (path was clean)", "path_local": "Tunnel down: your connection",
           "path_remote": "Tunnel down: far site or the path to it", "unknown": "Tunnel down: undetermined",
           "service_down": "Service unreachable (your internet is fine)",
           "device_down": "Device not answering (your network is fine)",
           "saturation": "Link full: your own traffic", "failover": "Running on the backup link",
           "loop": "Loop or broadcast storm on your network",
           "speedtest": "Speed test running"},
    "es": {"ok": "Sana", "local": "Problema de tu lado", "access": "Problema en el acceso del ISP",
           "isp": "Problema en la red del ISP", "remote": "Solo algunos destinos fallan",
           "dns": "Problema de DNS", "no_data": "Sin datos", "stale": "El monitor no reporta",
           "config": "Túnel caído: configuración (camino limpio)", "path_local": "Túnel caído: tu conexión",
           "path_remote": "Túnel caído: el sitio remoto o el camino", "unknown": "Túnel caído: indeterminado",
           "service_down": "Servicio inaccesible (tu internet anda bien)",
           "device_down": "El dispositivo no responde (tu red anda bien)",
           "saturation": "Enlace lleno: tu propio tráfico", "failover": "Funcionando por el enlace de respaldo",
           "loop": "Loop o tormenta de broadcast en tu red",
           "speedtest": "Midiendo la velocidad"},
}

# What an ISP-side verdict rules out / can't rule out (stored per incident by classifier.assess)
RULED = {
    "en": {"home": "Your router and local network answered normally at the same time",
           "icmp_noise": "Real TCP connections were affected too (not just ping being deprioritized)",
           "single_destination": "Several independent networks were affected at once (not one website)",
           "saturation": "Your link was not full (read from your router: {link})",
           "router_overload": "Your router's CPU was not overloaded ({cpu}%)",
           "loop": "No sign of a loop or broadcast storm on your network (no duplicate replies, normal broadcast)"},
    "es": {"home": "Tu router y tu red local respondían normal al mismo tiempo",
           "icmp_noise": "Las conexiones TCP reales también fallaban (no es solo ping despriorizado)",
           "single_destination": "Fallaban varias redes independientes a la vez (no un sitio puntual)",
           "saturation": "Tu enlace no estaba lleno (leído de tu router: {link})",
           "router_overload": "La CPU de tu router no estaba sobrecargada ({cpu}%)",
           "loop": "Sin señales de loop ni tormenta de broadcast en tu red (sin respuestas duplicadas, broadcast normal)"},
}
NOT_RULED = {
    "en": {"saturation": "Saturation by your own traffic (downloads, backups): connect isitmyisp to your router (SNMP) to rule it out",
           "router_overload": "An overloaded router (CPU): not exposed by your router",
           "transit": "That the fault is in your ISP's own upstream providers; towards you, it is still your ISP's service"},
    "es": {"saturation": "Saturación por tu propio tráfico (descargas, backups): conectá isitmyisp a tu router (SNMP) para descartarlo",
           "router_overload": "Un router sobrecargado (CPU): tu router no lo informa",
           "transit": "Que la falla esté en los proveedores de tu ISP hacia afuera; frente a vos, sigue siendo el servicio de tu ISP"},
}

ADVICE = {
    "en": {
        "local": "Check the Wi-Fi first: move closer to the router or plug in a cable. On cable, try another cable or port, then restart the router. Your ISP is not at fault here.",
        "access": "It's in your ISP's access network (fiber, ONT, local node). Restart the modem/ONT once. If it continues, file a complaint with the evidence report.",
        "isp": "It's inside your ISP's network: you can't fix it from your side. File a complaint attaching the evidence report.",
        "remote": "Your internet is fine. The problem is on that destination's side: wait, or contact that service.",
        "dns": "Set your router's DNS to 1.1.1.1 or 8.8.8.8. If you use your ISP's DNS, report it to them.",
        "stale": "Check that the isitmyisp container is running: docker ps.",
        "config": "The path to the far site is clean, so check the tunnel itself on both ends: DPD timeouts, IKE/IPsec lifetimes and rekey, NAT-T, MTU/MSS.",
        "path_local": "Your own connection is losing packets: fix that first (see the internet verdict).",
        "path_remote": "Your internet is fine but the far site's connection, or the path to it, is losing packets: check the far site's link or ISP.",
        "unknown": "The far end doesn't answer ping outside the tunnel, so the cause can't be separated. Allow ICMP on its public IP to get a verdict.",
        "device_down": "Your network and your internet work: it's the device. Check that it's on, its cable or its Wi-Fi, and restart it; if it keeps dropping, call its technician.",
        "service_down": "Your internet works: the problem is that service (its servers or its own provider). Check its status page or contact it; there is nothing to fix on your network.",
        "failover": "Your router moved the traffic to the backup link: the office still has internet, but your main ISP is down or failing. File a complaint with your main ISP; the report shows since when. Watch the backup's data plan if it has one.",
        "saturation": "Your own traffic is filling the link (a big download, a backup, video). Find who's using it (your router shows it), schedule backups at night, or prioritize critical traffic (QoS). Your ISP is not at fault.",
        "loop": "Something on your local network is sending frames round in a circle: usually a cable closing a loop between two switches (or both ends of a cable in the same switch), or a switch without STP. Unplug the switches or recent cables one by one until it stops, and turn on STP/loop protection if your switches have it. Your ISP is not at fault.",
    },
    "es": {
        "local": "Revisá primero el Wi-Fi: acercate al router o conectá un cable. Si es por cable, probá otro cable o puerto y reiniciá el router. Acá la culpa no es del ISP.",
        "access": "Es en la red de acceso de tu ISP (fibra, ONT, nodo de la zona). Reiniciá el módem/ONT una vez. Si sigue, reclamá con el informe de evidencia.",
        "isp": "Es dentro de la red de tu ISP: no lo podés arreglar de tu lado. Reclamá adjuntando el informe de evidencia.",
        "remote": "Tu internet anda bien. El problema es de ese destino: esperá o contactá a ese servicio.",
        "dns": "Poné en el router los DNS 1.1.1.1 u 8.8.8.8. Si usás los de tu ISP, avisales.",
        "stale": "Verificá que el contenedor de isitmyisp esté corriendo: docker ps.",
        "config": "El camino al otro sitio está limpio: revisá el túnel en ambos extremos (timeouts de DPD, lifetimes y rekey IKE/IPsec, NAT-T, MTU/MSS).",
        "path_local": "Tu propia conexión está perdiendo paquetes: resolvé eso primero (mirá el veredicto de internet).",
        "path_remote": "Tu internet anda bien, pero la conexión del otro sitio (o el camino hacia él) pierde paquetes: revisá el enlace o el ISP del otro sitio.",
        "unknown": "El otro extremo no responde ping por fuera del túnel, así que no se puede separar la causa. Permití ICMP en su IP pública para tener un veredicto.",
        "device_down": "Tu red y tu internet andan: es el aparato. Fijate que esté prendido, su cable o su Wi-Fi, y reinicialo; si se sigue cayendo, llamá a su técnico.",
        "service_down": "Tu internet anda: el problema es ese servicio (sus servidores o su proveedor). Mirá su página de estado o contactalo; no hay nada que arreglar en tu red.",
        "failover": "Tu router pasó el tráfico al enlace de respaldo: la oficina sigue con internet, pero tu ISP principal está caído o fallando. Reclamale a tu ISP principal; el informe muestra desde cuándo. Si el respaldo tiene tope de datos, cuidalo.",
        "saturation": "Tu propio tráfico está llenando el enlace (una descarga grande, un backup, video). Buscá quién lo usa (tu router lo muestra), programá los backups de noche o priorizá el tráfico crítico (QoS). Acá la culpa no es del ISP.",
        "loop": "Algo en tu red local está mandando tramas en círculo: casi siempre un cable que cierra un loop entre dos switches (o las dos puntas de un cable en el mismo switch), o un switch sin STP. Desconectá los switches o los cables nuevos de a uno hasta que pare, y activá STP o la protección de loops si tus switches la tienen. Acá la culpa no es del ISP.",
    },
}

# `isitmyisp doctor`: the name of each check, its scope, and per case one sentence + what to do ("" = nothing)
DOCTOR_NAME = {
    "en": {"cgnat": "CGNAT", "double_nat": "Double NAT", "ipv6": "IPv6", "dns": "DNS speed",
           "dns_trap": "DNS interception", "mtu": "Packet size (MTU)", "router_uptime": "Router restarts",
           "loop": "Loops and storms", "link_speed": "Link speed", "nic_errors": "Card errors", "wifi": "Wi-Fi or cable"},
    "es": {"cgnat": "CGNAT", "double_nat": "Doble NAT", "ipv6": "IPv6", "dns": "Velocidad del DNS",
           "dns_trap": "DNS interceptado", "mtu": "Tamaño de paquete (MTU)", "router_uptime": "Reinicios del router",
           "loop": "Loops y tormentas", "link_speed": "Velocidad del enlace", "nic_errors": "Errores de la placa",
           "wifi": "Wi-Fi o cable"},
}
DOCTOR_SCOPE = {
    "en": {"network": "Whole network", "probe": "This machine only"},
    "es": {"network": "Toda la red", "probe": "Solo esta máquina"},
}
DOCTOR = {
    "en": {
        "cgnat_skip": ("Couldn't trace the path (mtr missing or blocked).", "Install mtr to check for CGNAT."),
        "cgnat_yes": ("You are behind CGNAT ({hops}): you share a public IPv4 with other customers.",
                      "Opening ports and hosting from home won't work over IPv4. Ask your ISP for a public IP, or use IPv6 or a tunnel."),
        "cgnat_no": ("No CGNAT on the path.", ""),
        "double_nat_skip": ("Couldn't trace the path (mtr missing or blocked).", ""),
        "double_nat_yes": ("Double NAT ({hops}): there's a router behind another router.",
                           "Put the ISP's modem in bridge mode, or set port forwarding on both."),
        "double_nat_no": ("A single router between you and the ISP.", ""),
        "ipv6_none": ("No IPv6 on this network (nothing to break).", ""),
        "ipv6_ok": ("IPv6 announced and working.", ""),
        "ipv6_broken": ("IPv6 is announced but doesn't work: pages can take seconds to start loading.",
                        "Turn IPv6 off in the router, or report it to your ISP."),
        "dns_none": ("No DNS server found on this machine.", "Check the network settings (DHCP) of the router."),
        "dns_dead": ("Your DNS servers don't answer: {servers}.", "Set 1.1.1.1 or 8.8.8.8 as DNS in your router."),
        "dns_some_dead": ("Some DNS servers don't answer ({servers}); the rest do: {ms}.",
                          "Remove the dead one from your router's DNS settings."),
        "dns_slow": ("Your DNS servers are slow: {ms}.", "Every new site waits for this. Try 1.1.1.1 or 8.8.8.8 in your router."),
        "dns_ok": ("Your DNS servers answer fast: {ms}.", ""),
        "dns_trap_skip": ("Couldn't test.", ""),
        "dns_trap_yes": ("Someone answers DNS queries sent to an address with no server ({ip}): your DNS traffic is intercepted.",
                         "Usually the ISP or the router redirecting port 53. Harmless if it works; if DNS acts up, use DNS over HTTPS."),
        "dns_trap_no": ("DNS queries reach the server you chose.", ""),
        "mtu_skip": ("Couldn't test (ping blocked).", ""),
        "mtu_blackhole": ("Packets larger than {mtu} bytes vanish without a word (an MTU black hole).",
                          "Some sites hang halfway through loading. Set MTU {mtu} (or MSS clamping) on your router."),
        "mtu_lower": ("The path takes packets of up to {mtu} bytes (your card sends {iface}) and says so when they're too big.",
                      "Normal on PPPoE and tunnels; nothing to do."),
        "mtu_ok": ("Full-size packets ({mtu} bytes) go through.", ""),
        "router_uptime_skip": ("Connect your router (Settings → SNMP) to see when it last restarted.", ""),
        "router_uptime_recent": ("Your router restarted {ago} ago.",
                                 "If you didn't restart it, check its power supply and temperature, or look at its log."),
        "router_uptime_ok": ("Your router has been up for {ago}.", ""),
        "loop_skip": ("Couldn't watch the local network from here.", ""),
        "loop_yes": ("Signs of a loop or a broadcast storm: {signals}.",
                     "Look for a cable plugged into two ports of the same switch or between two switches; unplug one."),
        "loop_no": ("No sign of loops or broadcast storms in {s} s.", ""),
        "link_speed_skip": ("Not measured on Wi-Fi, or the card doesn't say.", ""),
        "link_speed_half": ("This card is at {speed} Mb/s half duplex: it can't send and receive at once.",
                            "Change the cable or the port; force full duplex on the switch if it keeps happening."),
        "link_speed_below_plan": ("This card negotiated {speed} Mb/s, below your {plan} Mb/s plan.",
                                  "Usually the cable (needs all 8 wires, Cat5e or better) or a 100 Mb/s port on the switch."),
        "link_speed_slow": ("This card negotiated only {speed} Mb/s.",
                            "If your plan is faster, check the cable (Cat5e or better) and the switch port."),
        "link_speed_ok": ("This card is at {speed} Mb/s.", ""),
        "nic_errors_skip": ("The card doesn't report errors.", ""),
        "nic_errors_growing": ("{n} new errors on {iface} in {s} s.", "Change the cable and the switch port of this machine."),
        "nic_errors_ok": ("No new errors on the card.", ""),
        "wifi_yes": ("This machine is on Wi-Fi ({iface}): what it measures includes the Wi-Fi.",
                     "For the monitor, plug the probe in with a cable so the Wi-Fi isn't blamed on the ISP."),
        "wifi_no": ("This machine is on a cable.", ""),
    },
    "es": {
        "cgnat_skip": ("No se pudo trazar el camino (falta mtr o está bloqueado).", "Instalá mtr para ver si hay CGNAT."),
        "cgnat_yes": ("Estás detrás de CGNAT ({hops}): compartís la IPv4 pública con otros clientes.",
                      "Por IPv4 no vas a poder abrir puertos ni publicar servicios. Pedile una IP pública al ISP, o usá IPv6 o un túnel."),
        "cgnat_no": ("No hay CGNAT en el camino.", ""),
        "double_nat_skip": ("No se pudo trazar el camino (falta mtr o está bloqueado).", ""),
        "double_nat_yes": ("Doble NAT ({hops}): hay un router detrás de otro.",
                           "Poné el módem del ISP en modo bridge, o abrí los puertos en los dos."),
        "double_nat_no": ("Un solo router entre vos y el ISP.", ""),
        "ipv6_none": ("No hay IPv6 en esta red (nada que se pueda romper).", ""),
        "ipv6_ok": ("IPv6 anunciado y funcionando.", ""),
        "ipv6_broken": ("IPv6 está anunciado pero no anda: las páginas pueden tardar segundos en empezar a cargar.",
                        "Apagá IPv6 en el router, o reportáselo al ISP."),
        "dns_none": ("Esta máquina no tiene ningún servidor DNS.", "Revisá la configuración de red (DHCP) del router."),
        "dns_dead": ("Tus servidores DNS no responden: {servers}.", "Poné 1.1.1.1 o 8.8.8.8 como DNS en el router."),
        "dns_some_dead": ("Algunos DNS no responden ({servers}); los otros sí: {ms}.",
                          "Sacá el que no anda de la configuración de DNS del router."),
        "dns_slow": ("Tus servidores DNS son lentos: {ms}.", "Cada sitio nuevo espera esto. Probá 1.1.1.1 o 8.8.8.8 en el router."),
        "dns_ok": ("Tus servidores DNS responden rápido: {ms}.", ""),
        "dns_trap_skip": ("No se pudo probar.", ""),
        "dns_trap_yes": ("Alguien responde consultas DNS mandadas a una dirección sin servidor ({ip}): tu tráfico DNS está interceptado.",
                         "Suele ser el ISP o el router redirigiendo el puerto 53. Si anda, no molesta; si el DNS falla, usá DNS sobre HTTPS."),
        "dns_trap_no": ("Las consultas DNS llegan al servidor que elegiste.", ""),
        "mtu_skip": ("No se pudo probar (ping bloqueado).", ""),
        "mtu_blackhole": ("Los paquetes de más de {mtu} bytes desaparecen sin aviso (un agujero negro de MTU).",
                          "Algunos sitios se cuelgan a mitad de carga. Configurá MTU {mtu} (o MSS clamping) en el router."),
        "mtu_lower": ("El camino acepta paquetes de hasta {mtu} bytes (tu placa manda {iface}) y avisa cuando son grandes.",
                      "Normal con PPPoE y túneles; no hay que hacer nada."),
        "mtu_ok": ("Los paquetes de tamaño completo ({mtu} bytes) pasan.", ""),
        "router_uptime_skip": ("Conectá tu router (Configuración → SNMP) para ver cuándo se reinició.", ""),
        "router_uptime_recent": ("Tu router se reinició hace {ago}.",
                                 "Si no lo reiniciaste vos, revisá la fuente y la temperatura, o mirá su log."),
        "router_uptime_ok": ("Tu router está prendido hace {ago}.", ""),
        "loop_skip": ("No se pudo mirar la red local desde acá.", ""),
        "loop_yes": ("Señales de un loop o una tormenta de broadcast: {signals}.",
                     "Buscá un cable enchufado en dos puertos del mismo switch o entre dos switches, y desenchufá uno."),
        "loop_no": ("Sin señales de loops ni tormentas de broadcast en {s} s.", ""),
        "link_speed_skip": ("No se mide por Wi-Fi, o la placa no lo informa.", ""),
        "link_speed_half": ("Esta placa está a {speed} Mb/s half duplex: no puede mandar y recibir a la vez.",
                            "Cambiá el cable o el puerto; si sigue, forzá full duplex en el switch."),
        "link_speed_below_plan": ("Esta placa negoció {speed} Mb/s, menos que tu plan de {plan} Mb/s.",
                                  "Casi siempre es el cable (necesita los 8 hilos, Cat5e o mejor) o un puerto de 100 Mb/s en el switch."),
        "link_speed_slow": ("Esta placa negoció solo {speed} Mb/s.",
                            "Si tu plan es más rápido, revisá el cable (Cat5e o mejor) y el puerto del switch."),
        "link_speed_ok": ("Esta placa está a {speed} Mb/s.", ""),
        "nic_errors_skip": ("La placa no informa errores.", ""),
        "nic_errors_growing": ("{n} errores nuevos en {iface} en {s} s.", "Cambiá el cable y el puerto del switch de esta máquina."),
        "nic_errors_ok": ("Sin errores nuevos en la placa.", ""),
        "wifi_yes": ("Esta máquina está por Wi-Fi ({iface}): lo que mide incluye el Wi-Fi.",
                     "Para el monitor, conectá la sonda por cable así el Wi-Fi no se le achaca al ISP."),
        "wifi_no": ("Esta máquina está por cable.", ""),
    },
}


def doctor_text(key: str, params: dict, lang: str = "en") -> tuple[str, str]:
    """(sentence, what to do) for one doctor check, in ``lang`` (English if missing)."""
    text, advice = DOCTOR.get(lang, DOCTOR["en"]).get(key) or DOCTOR["en"][key]
    if lang != "en" and "signals" in params:     # evidence lines are English (see report.EVIDENCE_ES)
        from .report import localize_evidence
        params = {**params, "signals": "; ".join(localize_evidence(x, lang) for x in params["signals"].split("; "))}
    try:
        return text.format(**params), advice.format(**params)
    except (KeyError, IndexError):
        return text, advice


# "Check from this device" (#66): per verdict, (headline, what to do); {probe} is the probe's verdict name
DEVCHECK = {
    "en": {
        "fine": ("The network is fine from this device too.",
                 "If an app or a site still fails, it's that app or that service, not your connection."),
        "device_link": ("The problem is between this device and the router: the probe, with the same router, was fine.",
                        ("Get closer to the router or use a cable; try another cable or switch port; restart the device. "
                        "The ISP is not to blame.")),
        "device_path": ("This device reaches the router fine but not the internet, while the probe did.",
                        ("Look at this device: a VPN, a firewall or antivirus, a proxy or a browser extension. "
                        "The network and the ISP are fine.")),
        "shared": ("The probe saw the same at the same time ({probe}): it's not this device.",
                   "Follow the probe's verdict on the dashboard."),
        "no_probe": ("The probe wasn't measuring at that time, so there is nothing to compare with.",
                     "Check that the monitor is running and try again."),
    },
    "es": {
        "fine": ("Desde este equipo la red también anda bien.",
                 "Si una app o una página sigue fallando, es esa app o ese servicio, no tu conexión."),
        "device_link": ("El problema está entre este equipo y el router: la sonda, con el mismo router, andaba bien.",
                        ("Acercate al router o usá un cable; probá otro cable u otro puerto del switch; reiniciá el equipo. "
                        "La culpa no es del ISP.")),
        "device_path": ("Este equipo llega bien al router pero no a internet, y la sonda sí.",
                        ("Revisá este equipo: una VPN, un firewall o antivirus, un proxy o una extensión del navegador. "
                        "La red y el ISP andan.")),
        "shared": ("La sonda vio lo mismo al mismo tiempo ({probe}): no es este equipo.",
                   "Seguí el veredicto de la sonda en el panel."),
        "no_probe": ("La sonda no estaba midiendo en ese momento, así que no hay con qué comparar.",
                     "Fijate que el monitor esté corriendo y probá de nuevo."),
    },
}


def devcheck_text(rec: dict, lang: str = "en") -> tuple[str, str]:
    """(headline, what to do) for one device check, in ``lang``."""
    text, advice = DEVCHECK.get(lang, DEVCHECK["en"])[rec["code"]]
    probe = (rec.get("probe") or {}).get("bad")
    return text.format(probe=VERDICT.get(lang, VERDICT["en"]).get(probe, probe or "")), advice


# Where the speed bottleneck is: speedtest.locate() compares the best download inside the ISP's
# network with the best one outside it. Shared by the dashboard and the report.
SPEEDWHERE = {
    "en": {
        "exit": ("Up to the ISP {inside} Mbps, to the rest of the internet {outside}: the bottleneck is the ISP's exit "
                 "(its peering or transit), not your access."),
        "access": ("Even inside the ISP's network the speed is {inside} Mbps, well under the plan: the limit is the access "
                   "link, not the rest of the internet."),
        "even": "Up to the ISP {inside} Mbps, to the rest of the internet {outside}: about the same, no bottleneck at its exit.",
    },
    "es": {
        "exit": ("Hasta el ISP {inside} Mbps, al resto de internet {outside}: el cuello de botella es la salida del ISP "
                 "(su peering o su tránsito), no el acceso."),
        "access": ("Aun dentro de la red del ISP la velocidad es {inside} Mbps, bastante menos que el plan: el límite es "
                   "el acceso, no el resto de internet."),
        "even": "Hasta el ISP {inside} Mbps, al resto de internet {outside}: parecido, no hay cuello de botella en su salida.",
    },
}

SPEEDSIDE = {"en": {"inside": "inside your ISP", "outside": "outside your ISP", "private": "LAN or VPN", None: "unknown"},
             "es": {"inside": "dentro de tu ISP", "outside": "fuera de tu ISP", "private": "LAN o VPN", None: "sin saber"}}


def speed_where_text(where: dict | None, lang: str = "en") -> str:
    """One sentence on where the speed bottleneck is, or "" when only one side was measured."""
    if not where:
        return ""
    text = SPEEDWHERE.get(lang, SPEEDWHERE["en"])[where["code"]]
    return text.format(inside=f"{where['inside']:.0f}", outside=f"{where['outside']:.0f}")


def speed_side(where: str | None, lang: str = "en") -> str:
    sides = SPEEDSIDE.get(lang, SPEEDSIDE["en"])
    return sides.get(where, sides[None])
