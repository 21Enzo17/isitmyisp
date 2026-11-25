"""Validation and delivery errors in the UI's language.

The core raises its errors in English (the CLI and the logs read them as they are). The web shows
them in the page's language: each English message has a pattern here, and its Spanish wording.
A message with no pattern is shown as it came, so a new error is never lost, only untranslated;
tests/test_errtext.py finds every message the core can raise and fails when one has no pattern.
"""

from __future__ import annotations

import re
from collections.abc import Callable

Q = r"""['"]?(.*?)['"]?"""          # a value the core quotes with repr(), or not

_ES: list[tuple[str, str | Callable[..., str]]] = [
    # settings: monitoring
    (r"between 1 and 6 anchors", "Poné entre 1 y 6 destinos de internet."),
    (rf"anchor {Q} is not an IP address", "«{0}» no es una dirección IP."),
    (rf"anchor {Q} must be a public address", "{0} tiene que ser una dirección pública de internet."),
    (r"interval must be a number", "El intervalo tiene que ser un número."),
    (r"interval must be between 0\.5 and 10 seconds", "El intervalo tiene que estar entre 0,5 y 10 segundos."),
    (r"window must be a whole number", "La ventana tiene que ser un número entero."),
    (r"window must be between 10 and 300 seconds", "La ventana tiene que estar entre 10 y 300 segundos."),
    (r"language must be en or es", "El idioma tiene que ser English o Español."),
    (r"auth mode must be one of .*", "Elegí un modo de acceso de la lista."),
    (r"proxy header must be a header name like Remote-User",
     "El encabezado del proxy tiene que ser un nombre de encabezado, como Remote-User."),
    (rf"trusted proxy {Q} is not an IP or CIDR", "Proxy de confianza «{0}»: no es una IP ni un rango (CIDR)."),
    (rf"calls destination {Q} must be an IP address", "El destino de llamadas «{0}» tiene que ser una dirección IP."),
    (rf"calls destination {Q} must be a public address",
     "El destino de llamadas {0} tiene que ser una dirección pública de internet."),
    (rf"static IP {Q} is not an IP address", "La IP fija «{0}» no es una dirección IP."),
    (rf"static IP {Q} must be a public IPv4 address", "La IP fija {0} tiene que ser una IPv4 pública."),
    (r"at most 3 DNS servers", "Poné como máximo 3 servidores DNS."),
    (rf"DNS server {Q} is not an IP address", "Servidor DNS «{0}»: no es una dirección IP."),
    (rf"DNS server {Q}: use an IPv4 address", "Servidor DNS {0}: usá una dirección IPv4."),
    (rf"DNS server {Q} is not a usable address", "Servidor DNS {0}: esa dirección no sirve como servidor."),
    # settings: your link (SNMP) and your plan
    (r"port and speeds must be numbers", "El puerto y las velocidades tienen que ser números."),
    (r"invalid port or speed", "El puerto tiene que estar entre 1 y 65535 y las velocidades ser números positivos."),
    (r"router address must be an IP", "La dirección del router tiene que ser una IP."),
    (r"a read-only community is required", "Falta la comunidad de solo lectura (hasta 64 caracteres)."),
    (r"set the contracted download and upload speeds .*",
     "Poné la bajada y la subida contratadas: hacen falta para saber si el enlace está lleno."),
    # router reading (SNMP): "List interfaces" and the link card
    (rf"bad OID {Q}", "Dato del router inválido ({0})."),
    (r"unexpected PDU type .*", "El router respondió algo que no es SNMP."),
    (r"malformed SNMP response", "El router respondió algo que no se pudo leer."),
    (r"SNMP error status (.+?)", "El router devolvió el error SNMP {0}."),
    (r"cannot reach (.+?): .*", "No se pudo llegar a {0}."),
    (r"no answer from (.+?) \(wrong community, ACL or SNMP disabled\?\)",
     "{0} no respondió (¿la comunidad es otra, hay una ACL o el SNMP está apagado?)."),
    (rf"interface {Q} not found on the router", "El router no tiene una interfaz «{0}»."),
    (r"router does not expose 64-bit interface counters .*",
     "El router no ofrece contadores de 64 bits por interfaz (IF-MIB ifHC*)."),
    (r"invalid literal for int\(\) .*", "El puerto tiene que ser un número."),
    # tunnels
    (rf"tunnel {Q}: (\w+) must be an IP address, got {Q}",
     lambda name, what, value: f"Túnel «{name}»: "
     + ("la dirección por dentro del túnel" if what == "overlay" else "la IP pública del otro extremo")
     + f" tiene que ser una dirección IP (pusiste «{value}»)."),
    (rf"duplicate tunnel name {Q}", "Ya hay un túnel que se llama «{0}»."),
    (rf"tunnel {Q}: both 'underlay' and 'overlay' are required",
     "Túnel «{0}»: faltan la IP del otro extremo y la dirección por dentro."),
    (rf"tunnel {Q}: type must be one of .*", "Túnel «{0}»: elegí un tipo de la lista."),
    # config file: your own speed test command
    (r"\[speedtest\] must be a table", "En el archivo de configuración, [speedtest] tiene que ser una sección."),
    (r"\[speedtest\] command is empty", "[speedtest] command está vacío."),
    (r"\[speedtest\] command must be a list of strings, or one string",
     "[speedtest] command tiene que ser una lista de textos, o un texto."),
    (r"\[speedtest\] command: (.+)", "[speedtest] command no se puede leer: {0}."),
    (r"\[speedtest\] format must be one of .*",
     "[speedtest] format tiene que ser auto, ookla, speedtest-cli, librespeed, iperf3 o json."),
    (r"\[speedtest\] timeout must be a number of seconds", "[speedtest] timeout tiene que ser un número de segundos."),
    (r"\[speedtest\] timeout must be between 5 and 600 seconds",
     "[speedtest] timeout tiene que estar entre 5 y 600 segundos."),
    # services
    (r"service name is required \(max 40 characters\)", "Ponele un nombre al servicio (hasta 40 caracteres)."),
    (rf"duplicate service name {Q}", "Ya hay un servicio que se llama «{0}»."),
    (r"type must be http or tcp", "El tipo tiene que ser HTTP(S) o TCP."),
    (r"(.*): URL must look like https://www\.example\.com/",
     "{0}: la dirección tiene que ser como https://www.ejemplo.com/"),
    (r"(.*): TCP target must look like host:port .*",
     "{0}: el destino TCP tiene que ser servidor:puerto (por ejemplo erp.ejemplo.com:443)."),
    (r"at most (.+?) services", "Como máximo {0} servicios."),
    # devices
    (r"device name is required \(max 40 characters\)", "Ponele un nombre al dispositivo (hasta 40 caracteres)."),
    (rf"duplicate device name {Q}", "Ya hay un dispositivo que se llama «{0}»."),
    (r"kind must be one of .*", "Elegí un tipo de dispositivo de la lista."),
    (r"(.*): use the device's address on your network .*",
     ("{0}: usá la dirección del dispositivo en tu red (por ejemplo 192.168.1.50) o su nombre local; "
     "las direcciones de internet van en Tus servicios.")),
    (r"(.*): the port must be a number between 1 and 65535", "{0}: el puerto tiene que ser un número entre 1 y 65535."),
    (r"at most (.+?) devices", "Como máximo {0} dispositivos."),
    # business hours
    (rf"{Q} is not a time like 08:30", "«{0}» no es una hora como 08:30."),
    (r"24:00 is the latest time", "La hora más tarde es 24:00."),
    (r"every shift needs an opening and a closing time", "Cada turno necesita hora de apertura y de cierre."),
    (r"(.*): closing must be after opening .*",
     ("{0}: el cierre tiene que ser después de la apertura (si pasa la medianoche: hasta 24:00, "
     "y desde 00:00 el día siguiente).")),
    (r"at most (.+?) shifts a day", "Como máximo {0} turnos por día."),
    (r"shifts of the same day overlap", "Hay turnos del mismo día que se superponen."),
    (r"set at least one day with opening hours, or turn business hours off",
     "Poné al menos un día con horario, o apagá el horario del local."),
    # alerts: settings
    (r"minutes must be a whole number", "Los minutos tienen que ser un número entero."),
    (r"minutes must be between 0 and 240", "Los minutos tienen que estar entre 0 y 240."),
    (r"public URL must start with http:// or https://", "La dirección pública tiene que empezar con http:// o https://."),
    (r"Telegram bot token looks wrong .*", "El token del bot de Telegram no parece correcto (es como 123456789:AA…)."),
    (r"Telegram chat id must be a number .*",
     "El chat de Telegram tiene que ser un número (por ejemplo 123456789 o -100…) o @canal."),
    (r"email security must be starttls, ssl or none", "La seguridad del email tiene que ser STARTTLS, SSL o ninguna."),
    (r"SMTP port must be a number", "El puerto SMTP tiene que ser un número."),
    (r"SMTP server is required", "Falta el servidor SMTP."),
    (r"sender must be an email address", "El remitente tiene que ser una dirección de email."),
    (r"recipients must be email addresses separated by commas",
     "Los destinatarios tienen que ser direcciones de email separadas por comas."),
    (r"webhook URL must start with http:// or https://", "La dirección del webhook tiene que empezar con http:// o https://."),
    # alerts: sending (the test button, the last delivery)
    (r"Telegram answered (.+?): check the bot token and chat id",
     "Telegram respondió {0}: revisá el token del bot y el chat."),
    (r"Telegram answered (.+?)", "Telegram respondió {0}."),
    (r"Telegram unreachable: .*", "No se pudo conectar con Telegram."),
    (r"email failed: (.*)", "No se pudo mandar el email ({0})."),
    (r"webhook answered (.+?)", "El webhook respondió {0}."),
    (r"webhook unreachable: .*", "No se pudo conectar con el webhook."),
    # speed test
    (r"to turn the speed test on, confirm that you understand what it does",
     "Para prender la prueba de velocidad, confirmá que entendés lo que hace."),
    (r"schedule must be weekly, daily or manual", "La frecuencia tiene que ser semanal, diaria o a mano."),
    (r"weekday, hour, budget and busy limit must be numbers",
     "El día, la hora, el presupuesto y el límite de uso tienen que ser números."),
    (r"weekday 0-6 and hour 0-23", "La hora tiene que estar entre 0 y 23."),
    (r"the monthly budget must be between 0\.5 and 500 GB", "El presupuesto mensual tiene que estar entre 0,5 y 500 GB."),
    (r"the busy limit must be between 5 and 100 %", "El límite de uso tiene que estar entre 5 y 100 %."),
    (rf"iperf3 server: {Q} is not a host name or address", "Servidor iperf3: «{0}» no es un nombre ni una dirección."),
    (r"iperf3 server: port (.*)", "Servidor iperf3: el puerto {0} no sirve."),
    (rf"iperf3 server: {Q} \(host\[:port\] and, optionally, inside or outside\)",
     "Servidor iperf3: «{0}» (escribí servidor[:puerto] y, si querés, inside u outside)."),
    (rf"iperf3 server: {Q}", "Servidor iperf3: «{0}» no se entiende."),
    (r"at most (.+?) iperf3 servers", "Como máximo {0} servidores iperf3."),
    (r"the engine must be cloudflare, mlab, both or command",
     "El motor tiene que ser Cloudflare, M-Lab, los dos o tu propio comando."),
    (r"to use M-Lab, confirm that it publishes each test with your public IP",
     "Para usar M-Lab, confirmá que entendés que publica cada prueba con tu IP pública."),
    (r"the peak-hour test needs a different hour from the usual one",
     "La prueba en hora pico necesita una hora distinta de la de siempre."),
    # monthly report
    (r"day and hour must be whole numbers", "El día y la hora tienen que ser números enteros."),
    (r"the day must be between 1 and 28 .*", "El día tiene que estar entre 1 y 28 (todos los meses lo tienen)."),
    (r"the hour must be between 0 and 23", "La hora tiene que estar entre 0 y 23."),
    (r"set up the email server first .*", "Primero configurá el servidor de email (Configuración, Alertas, Email)."),
    (r"no recipients: add them here or in the alert email settings",
     "No hay destinatarios: agregalos acá o en el email de las alertas."),
]

_COMPILED = {"es": [(re.compile(p + r"\Z", re.DOTALL), text) for p, text in _ES]}


def localize(message: str | None, lang: str) -> str | None:
    """The message in `lang`, or as it came when there's no wording for it."""
    if not message or lang not in _COMPILED:
        return message
    for pattern, text in _COMPILED[lang]:
        m = pattern.match(message)
        if m:
            return text(*m.groups()) if callable(text) else text.format(*m.groups())
    return message


def known(message: str, lang: str = "es") -> bool:
    return any(p.match(message) for p, _ in _COMPILED.get(lang, []))
