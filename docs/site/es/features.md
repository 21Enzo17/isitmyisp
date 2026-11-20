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

- Corre semanalmente (por defecto, el domingo a las 3), todos los días a la hora que elijas, o solo cuando apretás "probar ahora".
- Respeta un presupuesto mensual de datos (5 GB por defecto).
- Nunca corre en el enlace de respaldo ni pasado el presupuesto.
- La prueba programada además espera si hay un incidente o el enlace está ocupado (más del 30 % por defecto). "Probar ahora" corre igual: la pediste vos.
- Mide contra speed.cloudflare.com, que ve tu IP pública.
- Mide también la latencia con el enlace lleno (bufferbloat) y avisa cuando el resultado lo limita tu Wi-Fi y no el ISP.
- Mientras corre, esas ventanas no cuentan para el veredicto.

### Dentro y fuera de tu ISP

Cloudflare solo no distingue un acceso lento de una salida lenta. En **Configuración → Tu conexión → Prueba de velocidad contra tu plan** podés agregar hasta tres servidores [iperf3](https://iperf.fr/) propios: un VPS, otra sucursal o un servidor dentro de la red de tu ISP. Uno por línea, como `host[:puerto]` (5201 por defecto).

Cada servidor se marca **dentro** o **fuera** de tu ISP por su sistema autónomo (ASN), comparado con el de tu ISP. Una dirección en el espacio CGNAT del ISP cuenta como dentro. Una dirección de la LAN o de una VPN no se puede distinguir, así que escribí `inside` u `outside` después (`10.8.0.1 outside`). Marcar por ASN necesita los datos de ASN (**Configuración → Tu conexión → ISP principal y enlace de respaldo**) o `--asn-online`.

Con un servidor de cada lado, el panel y el informe comparan la mejor bajada de cada uno:

| Resultado | Qué significa |
|---|---|
| **La salida del ISP** | Afuera da menos del 60 % de adentro, por ejemplo 300 Mbps hasta el ISP y 40 al resto de internet. El cuello de botella es su peering o su tránsito, no tu acceso. |
| **El acceso** | Adentro y afuera dan parecido, pero aun dentro del ISP llegás a menos del 60 % de tu plan. El límite es tu acceso. |
| **Sin cuello de botella en la salida** | Adentro y afuera dan parecido. |

Las protecciones siguen valiendo: el tope de datos por prueba se reparte entre Cloudflare y tus servidores, no corre en el enlace de respaldo, y la prueba programada sigue esperando si hay un incidente. Necesita el programa `iperf3` en la máquina (la imagen de Docker lo trae), y cada servidor ve tu IP pública.

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

## Usuarios

- **Administrador:** cambia la configuración, los usuarios y las alertas.
- **Lector:** ve el panel, los incidentes y los informes, y no cambia nada salvo su propia contraseña.

Los administradores invitan gente con links de un solo uso que vencen en 48 horas, resetean contraseñas y pueden desactivar una cuenta, lo que cierra sus sesiones al instante.

## Métricas y API

| Ruta | Qué |
|---|---|
| `/metrics` | Prometheus, con un token que está en **Configuración → Acceso** |
| `/api/status` | El estado actual en JSON (con sesión iniciada) |
| `/healthz` | Público; solo dice si está vivo |
| `/report?since=7d` | El informe en HTML |
| `/report.pdf?since=7d` | El informe en PDF |
