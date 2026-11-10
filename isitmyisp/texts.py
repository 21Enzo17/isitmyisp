"""Plain-language texts shared by the web UI and the alerts (no web dependencies here)."""

from __future__ import annotations

VERDICT = {
    "en": {"ok": "Healthy", "local": "Problem on your side", "access": "ISP access network problem",
           "isp": "ISP backbone / upstream problem", "remote": "Only some destinations affected",
           "dns": "DNS problem", "no_data": "No data", "stale": "Monitor not reporting",
           "config": "Tunnel down: configuration (path was clean)", "path_local": "Tunnel down: your connection",
           "path_remote": "Tunnel down: far site or the path to it", "unknown": "Tunnel down: undetermined",
           "service_down": "Service unreachable (your internet is fine)"},
    "es": {"ok": "Sana", "local": "Problema de tu lado", "access": "Problema en el acceso del ISP",
           "isp": "Problema en la red del ISP", "remote": "Solo algunos destinos fallan",
           "dns": "Problema de DNS", "no_data": "Sin datos", "stale": "El monitor no reporta",
           "config": "Túnel caído: configuración (camino limpio)", "path_local": "Túnel caído: tu conexión",
           "path_remote": "Túnel caído: el sitio remoto o el camino", "unknown": "Túnel caído: indeterminado",
           "service_down": "Servicio inaccesible (tu internet anda bien)"},
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
        "service_down": "Your internet works: the problem is that service (its servers or its own provider). Check its status page or contact it; there is nothing to fix on your network.",
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
        "service_down": "Tu internet anda: el problema es ese servicio (sus servidores o su proveedor). Mirá su página de estado o contactalo; no hay nada que arreglar en tu red.",
    },
}
