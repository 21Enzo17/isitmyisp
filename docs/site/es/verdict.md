---
title: Cómo decide el veredicto
nav: El veredicto
description: Qué mide isitmyisp, cómo distingue pérdida real de ruido y cómo decide de quién es la culpa.
---
# Cómo decide el veredicto

Esta página es para técnicos. Explica qué se mide y por qué el veredicto no culpa a nadie sin evidencia.

## Qué mide

En ventanas de 30 segundos, con un ping cada 2 segundos:

- **Tu router** (o los routers de tu red, si hay más de uno).
- **El primer salto del ISP**: el primer router fuera de tu red.
- **Varios destinos de internet** (por defecto 1.1.1.1, 8.8.8.8 y 9.9.9.9), por ICMP y por TCP (un handshake al puerto 443, sin datos).
- **Tus servidores DNS**, con consultas reales.
- Tus servicios, túneles y el router por SNMP, si los configuraste.

Con eso identifica los tramos del camino: tu red, la red de acceso del ISP, su backbone y lo que está más allá. Usa los tipos de dirección y los números de sistema autónomo (AS), no la posición de cada salto.

## Pérdida real o ruido de ICMP

Los routers le dan baja prioridad a los pings dirigidos a ellos mismos. Por eso `mtr` muestra "pérdida" en un salto intermedio aunque el tráfico que pasa a través de él ande perfecto. isitmyisp solo cuenta la pérdida que **persiste hasta el destino**, y exige que **ICMP y TCP coincidan**.

## No grita "¡lobo!"

- **Significancia estadística.** Un paquete perdido de 50 no es "2 % de pérdida". La pérdida tiene que ser significativa según un intervalo de Wilson al 95 %, con al menos 2 paquetes perdidos.
- **Línea de base propia.** La latencia se juzga contra lo normal de cada destino, no contra un número fijo: es anormal cuando es el doble de lo normal y al menos 30 ms más. Lo normal se aprende solo de las ventanas sanas y se conserva al reiniciar, así un problema en curso nunca pasa a ser "lo normal".
- **Histéresis.** Cada ventana dura 30 segundos. Un incidente se abre con 2 ventanas malas seguidas y se cierra con 2 buenas seguidas. Si el primer salto del ISP aparece afectado en una ventana y en la siguiente no, sigue siendo el mismo corte del ISP, no dos.
- **Cortes intermitentes.** Una conexión que se corta y vuelve (mala, buena, mala, buena…) nunca junta 2 ventanas malas seguidas, y es justo lo que el ISP tiene que saber. Por eso **3 ventanas malas dentro de los últimos 5 minutos** también abren un incidente, marcado como **intermitente** en el panel, las alertas y el informe, con cuántas veces se cortó ("se cortó y volvió 6 veces"). Se cierra recién después de 3 minutos seguidos sin cortes.

## De quién es la culpa

1. **Tu red:** pérdida o latencia anormal hacia tu propio router **que también se ve en internet**. Si solo el router "pierde" pings mientras internet anda a través de él, el router filtra ICMP (algo común en firewalls de empresa) y no se culpa a nadie.
2. **Tu ISP:** todos los destinos afectados. Si su primer salto también lo está, es la red de acceso; si no, es el backbone o su proveedor.
3. **Otros:** solo algunos destinos afectados. No es tu ISP.
4. **DNS:** todo anda salvo la resolución de nombres. Es tu servidor DNS.

Cuando un servicio que agregaste falla con internet sano, el veredicto es "ese servicio". Cuando la oficina está en el enlace de respaldo, se dice.

## Evidencia en cada incidente

Al abrir un incidente se toma una captura de `mtr` hacia el destino afectado y se guarda con el incidente. Si el camino cambia, se redescubre. La evidencia de los incidentes se guarda unos 13 meses, y las mediciones de cada destino, 35 días.

## Lo que la evidencia descarta

Cada incidente del ISP lista qué descarta la evidencia (tu LAN, el ruido de ICMP, un único sitio, un enlace lleno) y qué no puede descartar. Si no hay datos del router por SNMP, el enlace lleno queda como "no se puede descartar". Mejor decirlo que prometer de más.
