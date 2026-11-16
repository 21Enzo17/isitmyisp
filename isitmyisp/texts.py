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
           "speedtest": "Speed test running"},
    "es": {"ok": "Sana", "local": "Problema de tu lado", "access": "Problema en el acceso del ISP",
           "isp": "Problema en la red del ISP", "remote": "Solo algunos destinos fallan",
           "dns": "Problema de DNS", "no_data": "Sin datos", "stale": "El monitor no reporta",
           "config": "Túnel caído: configuración (camino limpio)", "path_local": "Túnel caído: tu conexión",
           "path_remote": "Túnel caído: el sitio remoto o el camino", "unknown": "Túnel caído: indeterminado",
           "service_down": "Servicio inaccesible (tu internet anda bien)",
           "device_down": "El dispositivo no responde (tu red anda bien)",
           "saturation": "Enlace lleno: tu propio tráfico", "failover": "Funcionando por el enlace de respaldo",
           "speedtest": "Midiendo la velocidad"},
}

# What an ISP-side verdict rules out / can't rule out (stored per incident by classifier.assess)
RULED = {
    "en": {"home": "Your router and local network answered normally at the same time",
           "icmp_noise": "Real TCP connections were affected too (not just ping being deprioritized)",
           "single_destination": "Several independent networks were affected at once (not one website)",
           "saturation": "Your link was not full (read from your router: {link})",
           "router_overload": "Your router's CPU was not overloaded ({cpu}%)"},
    "es": {"home": "Tu router y tu red local respondían normal al mismo tiempo",
           "icmp_noise": "Las conexiones TCP reales también fallaban (no es solo ping despriorizado)",
           "single_destination": "Fallaban varias redes independientes a la vez (no un sitio puntual)",
           "saturation": "Tu enlace no estaba lleno (leído de tu router: {link})",
           "router_overload": "La CPU de tu router no estaba sobrecargada ({cpu}%)"},
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
    },
}


# The default internet destinations, by name: "Quad9 (9.9.9.9)" says more than the address alone.
ANCHOR_NAMES = {"1.1.1.1": "Cloudflare", "1.0.0.1": "Cloudflare", "2606:4700:4700::1111": "Cloudflare",
                "8.8.8.8": "Google", "8.8.4.4": "Google", "2001:4860:4860::8888": "Google",
                "9.9.9.9": "Quad9", "149.112.112.112": "Quad9", "2620:fe::fe": "Quad9"}

REMOTE_SUMMARY = {
    "en": {"one": "{bad} had trouble.", "many": "{bad} had trouble.",
           "fine": " {ok} answered fine: your connection worked.", "and": "and"},
    "es": {"one": "{bad} tuvo problemas.", "many": "{bad} tuvieron problemas.",
           "fine": " {ok} respondieron bien: tu conexión funcionó.", "and": "y"},
}


def anchor_label(target: str) -> str:
    name = ANCHOR_NAMES.get(target)
    return f"{name} ({target})" if name else target


def remote_summary(evidence: list[str], lang: str) -> str:
    """One plain sentence for "only some destinations failed", from the evidence lines
    ('9.9.9.9: 100.0% loss (15/15)', '1.1.1.1: OK'): who failed, who didn't, and that your
    connection worked. Empty when the lines don't say who answered."""
    t = REMOTE_SUMMARY.get(lang, REMOTE_SUMMARY["en"])
    bad, ok = [], []
    for line in evidence:
        target, sep, why = line.partition(": ")
        if not sep or " " in target:
            continue
        (ok if why.strip() == "OK" else bad).append(target)
    if not bad or not ok:
        return ""

    def join(xs: list[str]) -> str:
        xs = [anchor_label(x) for x in xs]
        return xs[0] if len(xs) == 1 else f"{', '.join(xs[:-1])} {t['and']} {xs[-1]}"
    fine = t["fine"].format(ok=join(ok))
    if len(ok) == 1:       # "respondió bien" / "answered fine" reads the same for one in English
        fine = fine.replace("respondieron", "respondió")
    return t["one" if len(bad) == 1 else "many"].format(bad=join(bad)) + fine
