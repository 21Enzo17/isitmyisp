---
title: Funciones
description: Servicios, túneles, enlace de respaldo, calidad de llamadas, test de velocidad, el router por SNMP, el modo TV y los usuarios.
---
# Funciones

Todo se configura desde **Configuración** en el navegador y se aplica en el momento: no hay que reiniciar nada ni editar archivos.

## Tus servicios

"¿Es mi internet o está caído el banco?" Agregá cualquier servicio HTTP(S) o TCP y se chequea cada 30 segundos. Si falla mientras tu conexión anda bien, el veredicto dice que es ese servicio.

Para Argentina hay servicios listos para tildar: ARCA (Clave Fiscal, facturación electrónica WSFEv1, WSAA), Rentas Jujuy, Banco Macro, Banco Nación, Galicia, Santander, BBVA Argentina, Mercado Pago, Payway, Google Workspace, Microsoft 365, WhatsApp Web y Zoom.

Cada uno dice qué chequea exactamente. Algunos se chequean por TCP porque su HTTPS no se puede evaluar de forma justa: el servidor de facturación de ARCA usa una configuración TLS que los clientes modernos rechazan, y Santander bloquea a los clientes automáticos.

## Dispositivos del local

"¿Se cayó el posnet o internet?" Cargá los aparatos de tu red en **Configuración → Monitoreo → Dispositivos del local**: el posnet o la terminal de cobro, la impresora fiscal, el grabador de las cámaras, la central telefónica, los puntos de acceso Wi-Fi.

- Cada uno se chequea cada 30 segundos **por ping** o, si el aparato no responde ping, **conectándose a un puerto** en el que escuche: impresoras 9100, cámaras 554 (RTSP) u 80, centrales 5060.
- Si deja de responder **3 veces seguidas mientras tu router sí responde**, el panel, las alertas y el informe dicen que **es ese aparato**, no tu internet ni tu ISP: revisá que esté prendido, su cable o su Wi-Fi.
- Si lo que falla es tu propia red (el router no responde), no se culpa al aparato.
- Aparecen en la tarjeta **Servicios, dispositivos y túneles** del panel y en el modo TV.
- Acá, y solo acá, se aceptan direcciones privadas (192.168…, 10…, 172.16…) o nombres locales (`impresora.local`). Las direcciones de internet van en **Tus servicios**.

![Configuración → Monitoreo → Dispositivos del local, con un posnet, una impresora fiscal y el grabador de las cámaras](/docs/img/es/devices-settings.png)

## Horario de atención

Para un comercio, 20 minutos sin internet a las 3 de la mañana no son lo mismo que a las 11. Cargá tu horario en **Configuración → Avisos → Horario de atención** (o en el asistente): por día de la semana, con hasta dos turnos, como el horario cortado con siesta.

Con el horario cargado:

- **El panel** suma "Con el local abierto: 14 min" al resumen de las últimas 24 horas, y el modo TV muestra el indicador **En horario**.
- **El informe** agrega cuántas horas estuvo abierto el local en el período, cuánto de ese tiempo hubo problemas, y marca cada incidente como "en horario" o "fuera de horario".
- **Alertas retenidas** (opcional): con el local cerrado no te llega nada. Al abrir, recibís un solo resumen de lo que pasó, por ejemplo "Con el local cerrado: 2 problemas". Si un problema sigue cuando abrís, se avisa como siempre.

![Configuración → Avisos → Horario de atención: dos turnos de lunes a viernes y el sábado a la mañana](/docs/img/es/hours-settings.png)

Si un turno pasa la medianoche, cargalo en dos partes: hasta 24:00, y desde 00:00 el día siguiente. Los horarios usan la zona horaria del equipo donde corre isitmyisp.

## Túneles VPN

¿Se cayó el túnel a la sucursal por su configuración o por el camino? isitmyisp mide afuera y adentro del túnel a la vez:

- **Afuera** (`underlay`): la dirección pública del otro extremo.
- **Adentro** (`overlay`): una dirección del otro lado a la que se llega por el túnel.

| Por el túnel | Por afuera | Veredicto |
|---|---|---|
| anda | — | arriba |
| falla | limpio | **configuración del túnel**: DPD, tiempos de vida y renegociación de IKE/IPsec, NAT-T, MTU/MSS |
| falla | también pierde, tu internet bien | **la otra sede o el camino hasta ella** |
| falla | también pierde, tu internet mal | **tu conexión** |
| falla | el otro extremo nunca responde ping | no se puede saber (filtra ICMP) |

Si las caídas por configuración se repiten a intervalos regulares, el informe lo marca: casi siempre son tiempos de renegociación distintos en cada extremo.

### Túneles inestables

Un túnel puede no caerse nunca "del todo" y aun así cortar las llamadas o las transferencias: cortes de 30 segundos que no llegan a ser una caída, o caídas que vuelven cada una o dos horas. isitmyisp cuenta cada corte adentro del túnel, aunque dure una sola medición:

- **Con 3 cortes o más sin una hora tranquila entre ellos**, el túnel queda **inestable**: abre un solo incidente (no uno por corte) y avisa una sola vez, con la causa probable. Se cierra después de una hora sin cortes, en el último corte.
- **La causa probable** sale de lo mismo que la tabla de arriba, mirando todos los cortes juntos: si se repiten cada tanto con el camino limpio, **tiempos de vida o renegociación** ("se repiten cada 2 h"); sin un patrón y con el camino limpio, **la configuración del túnel**; con el camino perdiendo también, **la otra sede** o **tu conexión**; si el otro extremo no responde ping, no se puede saber. Si el proveedor cambió el camino al otro sitio justo antes, también lo dice.
- La página de túneles muestra los cortes de las últimas 24 horas hora por hora, cuántos fueron demasiado cortos para contar como caída y qué revisar. En el panel y en el modo TV el túnel aparece en ámbar, "Inestable", en vez de "Arriba". El informe tiene una sección "Inestabilidad dentro de los túneles".

## Enlace de respaldo (failover)

Con un router con dos proveedores, isitmyisp nota en alrededor de un minuto cuándo el tráfico pasa al enlace de respaldo y cuándo vuelve. Lo detecta viendo cuál es el primer router del ISP en el camino. El panel muestra "en respaldo" y el informe dice desde cuándo hasta cuándo el ISP principal no estuvo llevando el tráfico.

![El panel mientras la oficina está en el enlace de respaldo](/docs/img/es/failover.png)

## IP pública fija

Si pagás por una IP pública fija, ponela en Configuración → Tu conexión. Cada 10 minutos isitmyisp le pregunta tu IP pública a api.ipify.org y, si dos veces seguidas no es la tuya, abre un incidente y avisa con la IP que tenés ahora; se cierra solo cuando vuelve la tuya. Vacío (lo normal), no se pregunta nada ni se avisa nada: en la mayoría de las conexiones la IP cambia cada tanto y es normal.

## Cambios de camino

Tu proveedor puede mandar tu tráfico por otro camino sin que te enteres: otra salida, otro carrier, una vuelta más larga. Cada 10 minutos isitmyisp traza el camino (3 rondas de `mtr`) a cada destino de internet, al otro extremo de cada túnel y a cada uno de tus servicios, y nota cuando el proveedor lo cambia. Un salto que no contesta, o el balanceo entre routers de la misma red, no es un cambio; un camino nuevo necesita dos trazas seguidas.

- **Cuando el camino nuevo es claramente más lento**, abre un incidente y avisa: "Tu proveedor cambió el camino: ahora es más lento", con la latencia de antes y de después (al menos +15 ms y +25 %, o 1 punto más de pérdida, 15 minutos después del cambio). Se cierra cuando el camino vuelve o la latencia se recupera.
- **Cuando se abre cualquier incidente**, traza en el momento lo que ese incidente usa y dice qué muestra el camino: que es el de siempre y dónde se corta (dentro de tu proveedor o más allá), o que el proveedor lo cambió unos minutos antes. Esa línea va en el aviso, en la página de incidentes y en el informe.
- El panel lista los cambios de los últimos 7 días con el camino de antes y el de ahora, y el informe tiene una sección "Cambios de camino". Solo los que empeoraron algo (más lento, con pérdida o que ya no llega) se muestran abiertos y se marcan en el gráfico; el resto queda plegado en "sin efecto". Un camino que va y vuelve sin costar nada es balanceo: después de la primera vez se aprende como un solo camino y no se cuenta más como cambio. El ir y venir se marca inestable solo cuando perjudica.

Los caminos se comparan por red (/24) y por organización, así que no necesita la base de ASN para funcionar, pero con ella (Configuración → Tu conexión) nombra cada red.

## Calidad de llamadas

¿Una llamada se escucharía bien ahora? Un MOS estimado de 1 a 5 (modelo E de la UIT-T G.107), calculado con la latencia, el jitter y la pérdida que ya mide. Si tenés central telefónica o proveedor SIP, configurá su dirección para medir contra él. Es una estimación, no una llamada real, y el panel lo aclara.

## Test de velocidad

**Está apagado por defecto, a propósito.** Llena tu enlace durante unos segundos y consume datos, así que viene desactivado, explica por qué y te pide que aceptes los riesgos antes de activarlo.

![La configuración del test de velocidad: qué hace y por qué puede ser un problema](/docs/img/es/speed-test-settings.png)

Cuando está activado:

- Corre semanalmente (por defecto, el domingo a las 3), todos los días a la hora que elijas, o solo cuando apretás "probar ahora". Si querés, también en [hora pico](#hora-pico).
- Respeta un presupuesto mensual de datos (5 GB por defecto). Un plan rápido necesita más: 1000/600 Mbps con Cloudflare y M-Lab y la prueba en hora pico usa unos 3 GB por prueba, 40 GB al mes. Si el presupuesto no alcanza, la prueba se corta antes y mide menos de lo que tenés, y Ajustes y el panel te avisan cuánto poner.
- Nunca corre en el enlace de respaldo ni pasado el presupuesto.
- La prueba programada además espera si hay un incidente o el enlace está ocupado (más del 30 % por defecto). "Probar ahora" corre igual: la pediste vos.
- Mide contra speed.cloudflare.com, que ve tu IP pública, y contra cualquier otro [motor](#motores) que actives.
- Tu plan se compara con la **mejor cifra** de cada prueba, venga del motor que venga. Un servidor solo puede medir menos que tu línea, nunca más, así que un servidor lejano y lento nunca se lee como que tu ISP no cumple.
- Mide también la latencia con el enlace lleno (bufferbloat) y avisa cuando el resultado lo limita tu Wi-Fi y no el ISP.
- Mientras corre, esas ventanas no cuentan para el veredicto.

### Motores

Cada motor mide el camino hasta su propio servidor, así que cada uno te dice algo distinto. El motor principal lo elegís vos, en el asistente de **Primeros pasos** o en Configuración: **Cloudflare** (por defecto), **M-Lab** o **los dos**. Los demás se suman. Todos los que actives corren en la misma prueba, uno detrás de otro, y el presupuesto se reparte entre ellos: con un solo motor, cada prueba gasta la mitad que con dos.

| Motor | Qué mide | Qué comparte | Por defecto |
|---|---|---|---|
| **Cloudflare** | Hacia internet: el camino al servidor de Cloudflare más cercano. Con algunos ISP el techo es el propio Cloudflare (su servidor, o su peering con ese ISP). | Cloudflare ve tu IP pública. | sí, salvo que elijas solo M-Lab |
| **M-Lab** | El servidor NDT7 de [Measurement Lab](https://www.measurementlab.net/) más cercano: la plataforma abierta detrás del test de velocidad de Google, con servidores en muchas más ciudades. | **M-Lab publica cada prueba como datos abiertos, con tu IP pública.** Necesita su propio consentimiento. | **no** |
| **Tu propio comando** | Lo que mida tu herramienta, por ejemplo el servidor de tu propio ISP con la CLI de Ookla. | Lo que comparta esa herramienta. | **no** |
| **Otra máquina** | Una prueba que corrió en otro lado, por ejemplo en una PC por cable, y que se le manda a isitmyisp. | Nada más desde acá. | **no** |
| **Tus servidores iperf3** | Dentro o fuera de tu ISP: ver [más abajo](#dentro-y-fuera-de-tu-isp). | Cada servidor ve tu IP pública. | **no** |

La cifra de Cloudflare es el percentil 90 de las tasas de cada medio segundo, después de un segundo de calentamiento y con seis conexiones, como la informa speed.cloudflare.com. Si Cloudflare está limitando tu IP (HTTP 429), el resultado lo dice.

#### M-Lab

Se elige como motor (solo, o junto con Cloudflare) en **Primeros pasos** o en **Configuración → Tu conexión → Prueba de velocidad contra tu plan**, marcando también su casilla: M-Lab publica cada prueba, con tu IP pública, como datos abiertos para investigación. En una fibra de 1000 Mbps donde Cloudflare no pasaba de 490, M-Lab Buenos Aires midió 930.

#### Tu propio motor

isitmyisp puede correr una herramienta de test de velocidad que vos instalaste y leer su JSON. No trae ninguna ni acepta licencias por vos: la de Ookla, por ejemplo, solo permite uso personal, así que la aceptás en tu propio comando. El comando se configura solo en el archivo de configuración (o en la variable `ISITMYISP_SPEEDTEST_COMMAND`), nunca desde la web, así que ni una página de admin ni un formulario falsificado pueden hacerle correr nada.

```toml
[speedtest]
command = ["speedtest", "-f", "json", "--accept-license", "--accept-gdpr"]
name = "Ookla"         # opcional, cómo se muestra
format = "auto"        # auto | ookla | speedtest-cli | librespeed | iperf3 | json
timeout = 120          # segundos
```

Entiende la CLI de Ookla (`speedtest -f json`), el speedtest-cli de Python (`--json`), librespeed-cli (`--json`), iperf3 (`-J`) y un formato simple para tus scripts: `{"download_mbps": 930, "upload_mbps": 600, "ping_ms": 2.1, "server": "Nombre"}`. Corre como lista de argumentos, nunca a través de una shell, después de los motores incluidos, con el mismo horario y las mismas protecciones. Sus datos no se pueden topear, así que se descuentan del presupuesto después. Con Docker, montá la herramienta dentro del contenedor.

Con el comando configurado, la elección de motor en **Configuración → Tu conexión** suma una cuarta opción, **Solo tu propio comando**: la prueba corre únicamente tu herramienta, sin Cloudflare ni M-Lab, y el plan se compara solo con su resultado.

#### Desde otra máquina

La máquina que corre isitmyisp no siempre es la indicada para medir: una Raspberry Pi por Wi-Fi, o un procesador que no llega a 1 Gbps. Cualquier otra máquina puede mandarle sus resultados. En **Configuración → Tu conexión → Resultados de otra máquina**, generá un token. Después, desde esa máquina (por ejemplo, con un cron en una PC por cable):

```sh
speedtest -f json | curl -H "Authorization: Bearer <token>" --data-binary @- \
  "http://<isitmyisp>:8080/api/speedtest?name=PC"
```

Acepta cualquier formato que lea el motor propio (`?format=` si no lo puede adivinar), y `?wireless=1` si esa máquina está por Wi-Fi. Un resultado enviado se muestra aunque el test propio de esta máquina esté apagado, no usa presupuesto y está limitado a 6 por minuto. El token no es el de Prometheus; podés generar uno nuevo o apagarlo cuando quieras.

### Hora pico

Marcá **Probar también en hora pico** (21:00 por defecto) para tener una segunda prueba, los mismos días, a la hora en que todos están conectados. El panel la compara con la de siempre: "En hora pico: 450 Mbps, 50% de los 900 Mbps de la prueba de siempre". Por debajo del 80 % dice que la línea se pone lenta a la noche. Con los mismos motores, eso es congestión del ISP, sea cual sea el techo del motor. Duplica las pruebas, así que cada una tiene la mitad del presupuesto, y no corre si tu propio enlace está ocupado, como cualquier prueba programada.

### Dentro y fuera de tu ISP

Cloudflare solo no distingue un acceso lento de una salida lenta. En **Configuración → Tu conexión → Prueba de velocidad contra tu plan** podés agregar hasta tres servidores [iperf3](https://iperf.fr/) propios: un VPS, otra sucursal o un servidor dentro de la red de tu ISP. Uno por línea, como `host[:puerto]` (5201 por defecto).

Cada servidor se marca **dentro** o **fuera** de tu ISP por su sistema autónomo (ASN), comparado con el de tu ISP. Una dirección en el espacio CGNAT del ISP cuenta como dentro. Una dirección de la LAN o de una VPN no se puede distinguir, así que escribí `inside` u `outside` después (`10.8.0.1 outside`). Marcar por ASN necesita los datos de ASN (**Configuración → Tu conexión → ISP principal y enlace de respaldo**) o `--asn-online`.

Con un servidor de cada lado, el panel y el informe comparan la mejor bajada de cada uno:

| Resultado | Qué significa |
|---|---|
| **La salida del ISP** | Afuera da menos del 60 % de adentro, por ejemplo 300 Mbps hasta el ISP y 40 al resto de internet. El cuello de botella es su peering o su tránsito, no tu acceso. |
| **El acceso** | Adentro y afuera dan parecido, pero aun dentro del ISP llegás a menos del 60 % de tu plan. El límite es tu acceso. |
| **Sin cuello de botella en la salida** | Adentro y afuera dan parecido. |

Las protecciones siguen valiendo: el tope de datos por prueba se reparte entre los motores y tus servidores, no corre en el enlace de respaldo, y la prueba programada sigue esperando si hay un incidente. Necesita el programa `iperf3` en la máquina (la imagen de Docker lo trae), y cada servidor ve tu IP pública.

## El router por SNMP

La objeción favorita de cualquier ISP es "saturaste tu propio enlace". Si conectás tu router por SNMP (versión 2c, solo lectura), isitmyisp lee el uso de la interfaz WAN y la CPU en cada ventana. Así descarta esa objeción, o te dice que tenía razón. Necesita tu plan contratado (**Configuración → Tu conexión → Tu plan contratado**) para saber cuándo el enlace está lleno.

También lee el broadcast y el multicast que recibe cada interfaz del router: una tormenta en la LAN (un loop entre switches) se ve ahí, al lado de la CPU. Ver [loops y tormentas de broadcast](/docs/es/verdict/#loops-y-tormentas-de-broadcast).

## Modo TV

Un tablero para una pantalla en la pared de la oficina: letras grandes, se actualiza solo, sin menús ni inicio de sesión. Lo podés ver en la [demo](/es/isp/tv/).

![El tablero del modo TV durante un problema en la red del ISP](/docs/img/es/tv.png)

**Para ponerlo en una tele**, sin escribir nada largo con el control remoto:

1. En la tele abrí la dirección del panel seguida de **/tv**, por ejemplo `192.168.1.50:8080/tv`.
2. La tele muestra un código corto, como **C4R-HN9**.
3. Desde tu celular o tu PC, en **Configuración → Acceso → Modo TV**, escribí ese código y ponele un nombre a la pantalla ("Tele del mostrador").
4. En unos segundos la tele muestra el tablero, y queda vinculada: si se apaga o se reinicia, vuelve sola al tablero.

![Lo que muestra la tele antes de vincularla: un código corto y los pasos](/docs/img/es/tv-code.png)

![Configuración → Acceso → Modo TV: donde se escribe el código](/docs/img/es/tv-settings.png)

Para que la tele llegue al panel, el panel tiene que verse desde tu red, que es lo que hace el instalador por defecto. Si lo instalaste con `--local`, volvé a correrlo sin esa opción (ver [Instalar](install.md)); tus datos se conservan.

El código vence a los 10 minutos y sirve una sola vez. En **Configuración → Acceso → Modo TV** ves las pantallas vinculadas y podés desvincular cualquiera. Si preferís pegar un link, hay también un **link directo** secreto que se puede revocar.

Tiene dos vistas:

- **Tablero** (por defecto): el veredicto y tres indicadores (la nota del [chequeo de la red](/docs/es/doctor/) con su primer problema, o la disponibilidad de 24 horas si todavía no corrió; tiempo sin cortes o con problemas; latencia), la disponibilidad de los últimos 30 días día por día, las últimas 24 horas junto a los últimos eventos y la calidad para llamadas, la última prueba de velocidad contra tu plan (si la tenés activada), cada destino medido y tus servicios, dispositivos y túneles. Cada bloque aparece solo cuando tiene datos. Lo que falla se nombra arriba en rojo, los destinos con pérdida se marcan en rojo y las listas largas rotan en cada actualización (lo caído o inestable queda fijo). Un [cambio de camino](#cambios-de-camino) que sigue empeorando las cosas va arriba en una línea, si no pasa nada más grave; durante una caída baja al pie de los últimos eventos. Se acomoda a cualquier pantalla, de 720p a 4K, sin barras de desplazamiento.
- **Simple** (`?layout=simple`): solo el veredicto, para el mostrador. [Verla en la demo](/es/isp/tv/simple/).

![La vista simple del modo TV](/docs/img/es/tv-simple.png)

## Modo celular

El panel en una sola columna, para cuando el problema te agarra lejos de la computadora. Tiene lo mismo que el panel, ordenado para decidir rápido: de quién es la culpa y por qué, el camino salto por salto, qué cambió, las últimas 24 horas, qué está afectado, la capacidad y qué podés hacer. Lo abrís con el botón **Vista celular** que aparece arriba del panel en pantallas chicas, o yendo a la dirección del panel seguida de **/phone**, por ejemplo `192.168.1.50:8080/phone`. Pide el mismo inicio de sesión que el panel.

![El modo celular durante un problema en la red del ISP](/docs/img/es/phone.png)

- **El veredicto** dice desde qué hora pasa y cuánto lleva. Debajo, **Por qué lo decimos** despliega la evidencia y lo que se descartó.
- **Tu conexión** muestra tu red, tu ISP (con su ASN y la IP del salto, para dictárselos al soporte) e internet, cada uno con su latencia de las últimas 6 horas. **Cada destino** despliega ping y TCP 443 lado a lado: si el ping se pierde y el TCP contesta, el ISP está descartando ping, no tráfico.
- **Qué cambió** aparece solo si cambió algo: un [cambio de camino](#cambios-de-camino) con la latencia de antes y de ahora, el paso al [enlace de respaldo](#enlace-de-respaldo-failover) o una [IP pública](#ip-publica-fija) distinta de la fija.
- **Qué está afectado** agrupa servicios, túneles y dispositivos: lo que falla por nombre, el resto como un número. Si algo falla, sube antes del camino.
- **Capacidad** muestra la carga del enlace y la CPU del router (si tenés [SNMP](#el-router-por-snmp)) y la última [prueba de velocidad](#test-de-velocidad), plegada.
- Al pie: probar desde ese celular, la última hora en detalle, el informe y el panel completo.

Se actualiza solo cada minuto, sin JavaScript, y respeta el tema claro u oscuro.

## Usuarios

- **Administrador:** cambia la configuración, los usuarios y las alertas.
- **Lector:** ve el panel, los incidentes y los informes, y no cambia nada salvo su propia contraseña.

Los administradores invitan gente con links de un solo uso que vencen en 48 horas, resetean contraseñas y pueden desactivar una cuenta, lo que cierra sus sesiones al instante.

## Métricas y API

| Ruta | Qué |
|---|---|
| `/metrics` | Prometheus, con un token que está en **Configuración → Acceso**. Qué exporta, un dashboard de Grafana listo para importar y reglas de alerta están en [`contrib/grafana`](https://github.com/21Enzo17/isitmyisp/tree/main/contrib/grafana) |
| `POST /api/speedtest` | Un resultado de test de velocidad de [otra máquina](#desde-otra-maquina), con su propio token |
| `/api/status` | El estado actual en JSON (con sesión iniciada) |
| `/healthz` | Público; solo dice si está vivo |
| `/report?since=7d` | El informe en HTML |
| `/report.pdf?since=7d` | El informe en PDF |
