---
title: Funciones
description: Servicios, túneles, enlace de respaldo, calidad de llamadas, test de velocidad, el router por SNMP, el modo TV y los usuarios.
---
# Funciones

Todo se configura desde **Configuración** en el navegador y se aplica en el momento: no hay que reiniciar nada ni editar archivos.

## Tus servicios

"¿Es mi internet o está caído el banco?" Agregá cualquier servicio HTTP(S) o TCP y se chequea cada 30 segundos. Si falla mientras tu conexión anda bien, el veredicto dice que es ese servicio.

Para Argentina hay servicios listos para tildar: ARCA (Clave Fiscal, facturación electrónica WSFEv1, WSAA), Rentas Jujuy, Banco Macro, Banco Nación, Galicia, Santander, Mercado Pago, Payway, Google Workspace, Microsoft 365, WhatsApp Web y Zoom.

Cada uno dice qué chequea exactamente. Algunos se chequean por TCP porque su HTTPS no se puede evaluar de forma justa: el servidor de facturación de ARCA usa una configuración TLS que los clientes modernos rechazan, y Santander bloquea a los clientes automáticos.

## Dispositivos del local

"¿Se cayó el posnet o internet?" Cargá los aparatos de tu red en **Configuración → Dispositivos del local**: el posnet o la terminal de cobro, la impresora fiscal, el grabador de las cámaras, la central telefónica, los puntos de acceso Wi-Fi.

- Cada uno se chequea cada 30 segundos **por ping** o, si el aparato no responde ping, **conectándose a un puerto** en el que escuche: impresoras 9100, cámaras 554 (RTSP) u 80, centrales 5060.
- Si deja de responder **3 veces seguidas mientras tu router sí responde**, el panel, las alertas y el informe dicen que **es ese aparato**, no tu internet ni tu ISP: revisá que esté prendido, su cable o su Wi-Fi.
- Si lo que falla es tu propia red (el router no responde), no se culpa al aparato.
- Aparecen en la tarjeta **Servicios, dispositivos y túneles** del panel y en el modo TV.
- Acá, y solo acá, se aceptan direcciones privadas (192.168…, 10…, 172.16…) o nombres locales (`impresora.local`). Las direcciones de internet van en **Tus servicios**.

## Horario de atención

Para un comercio, 20 minutos sin internet a las 3 de la mañana no son lo mismo que a las 11. Cargá tu horario en **Configuración → Horario de atención** (o en el asistente): por día de la semana, con hasta dos turnos, como el horario cortado con siesta.

Con el horario cargado:

- **El panel** suma "Con el local abierto: 14 min" al resumen de las últimas 24 horas, y el modo TV muestra el indicador **En horario**.
- **El informe** agrega cuántas horas estuvo abierto el local en el período, cuánto de ese tiempo hubo problemas, y marca cada incidente como "en horario" o "fuera de horario".
- **Alertas retenidas** (opcional): con el local cerrado no te llega nada. Al abrir, recibís un solo resumen de lo que pasó, por ejemplo "Con el local cerrado: 2 problemas". Si un problema sigue cuando abrís, se avisa como siempre.

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

## Enlace de respaldo (failover)

Con un router con dos proveedores, isitmyisp nota en alrededor de un minuto cuándo el tráfico pasa al enlace de respaldo y cuándo vuelve. Lo detecta viendo cuál es el primer router del ISP en el camino. El panel muestra "en respaldo" y el informe dice desde cuándo hasta cuándo el ISP principal no estuvo llevando el tráfico.

![El panel mientras la oficina está en el enlace de respaldo](/docs/img/es/failover.png)

## Calidad de llamadas

¿Una llamada se escucharía bien ahora? Un MOS estimado de 1 a 5 (modelo E de la UIT-T G.107), calculado con la latencia, el jitter y la pérdida que ya mide. Si tenés central telefónica o proveedor SIP, configurá su dirección para medir contra él. Es una estimación, no una llamada real, y el panel lo aclara.

## Test de velocidad

**Está apagado por defecto, a propósito.** Llena tu enlace durante unos segundos y consume datos, así que viene desactivado, explica por qué y te pide que aceptes los riesgos antes de activarlo.

![La configuración del test de velocidad: qué hace y por qué puede ser un problema](/docs/img/es/speed-test-settings.png)

Cuando está activado:

- Corre semanalmente (por defecto, el domingo a las 3) o cuando apretás "probar ahora".
- Respeta un presupuesto mensual de datos (5 GB por defecto).
- No corre en el enlace de respaldo, durante un incidente ni con el enlace ocupado (más del 30 % por defecto).
- Mide contra speed.cloudflare.com, que ve tu IP pública.
- Mide también la latencia con el enlace lleno (bufferbloat) y avisa cuando el resultado lo limita tu Wi-Fi y no el ISP.
- Mientras corre, esas ventanas no cuentan para el veredicto.

## El router por SNMP

La objeción favorita de cualquier ISP es "saturaste tu propio enlace". Si conectás tu router por SNMP (versión 2c, solo lectura), isitmyisp lee el uso de la interfaz WAN y la CPU en cada ventana. Así descarta esa objeción, o te dice que tenía razón. Necesita las velocidades contratadas para saber cuándo el enlace está lleno.

## Modo TV

Un tablero para una pantalla en la pared de la oficina: letras grandes, se actualiza solo, sin menús ni inicio de sesión. Se abre con un link que generás (y podés revocar) en **Configuración → Modo TV**. Tiene dos vistas:

- **Tablero** (por defecto): el camino, las llamadas, el enlace, la línea de 24 horas, cada destino, servicios, túneles e incidentes recientes. Lo que falla se nombra arriba en rojo, y las listas largas rotan en cada actualización.
- **Simple** (`?layout=simple`): solo el veredicto, para el mostrador.

## Usuarios

- **Administrador:** cambia la configuración, los usuarios y las alertas.
- **Lector:** ve el panel, los incidentes y los informes, y no cambia nada salvo su propia contraseña.

Los administradores invitan gente con links de un solo uso que vencen en 48 horas, resetean contraseñas y pueden desactivar una cuenta, lo que cierra sus sesiones al instante.

## Métricas y API

| Ruta | Qué |
|---|---|
| `/metrics` | Prometheus, con un token que está en Configuración |
| `/api/status` | El estado actual en JSON (con sesión iniciada) |
| `/healthz` | Público; solo dice si está vivo |
| `/report?since=7d` | El informe en HTML |
| `/report.pdf?since=7d` | El informe en PDF |
