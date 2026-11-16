---
title: El chequeo de la red
nav: El chequeo
description: Once revisiones de tu red (CGNAT, doble NAT, IPv6, DNS, MTU, loops, la placa de red) con qué hacer en cada una.
---
# El chequeo de la red

El veredicto dice qué está fallando ahora. El chequeo revisa cómo está armada tu red aunque hoy ande todo: cosas que no cortan internet pero que después explican un problema. Tarda unos 15 segundos.

Cada revisión sale en **verde** (bien), **amarillo** (para mirar) o **rojo** (mal), con una frase y qué hacer. Si algo no se pudo medir, lo dice en vez de darlo por bueno.

## Cómo se corre

- **Solo**: el monitor lo corre una vez por día.
- **En el panel**: en **Chequeo**, con el botón **Revisar ahora**. El monitor lo toma en la siguiente vuelta.
- **En la terminal**:

```bash
isitmyisp doctor            # 15 segundos, el resultado en pantalla
isitmyisp doctor -s 30      # mirar 30 segundos la red local
isitmyisp doctor --json     # para scripts
isitmyisp doctor --save     # además guardarlo, para el panel y el informe
```

Sale con código 1 si alguna revisión dio rojo, así sirve en un script.

## Qué revisa

**Toda la red** (vale para cualquier equipo de tu casa u oficina):

| Revisión | Amarillo o rojo cuando |
|---|---|
| CGNAT | Tu ISP te pone detrás de una IP compartida (100.64.x.x). No podés abrir puertos ni tener una VPN entrante. |
| Doble NAT | Hay dos routers en cadena (por ejemplo, el del ISP y uno tuyo). Puede romper juegos, llamadas y VPN. |
| IPv6 | Tu router anuncia IPv6 pero no sale a internet: algunas apps tardan o fallan. |
| Velocidad del DNS | Tus DNS tardan 150 ms o más (amarillo, 400 ms rojo), o alguno no responde. |
| DNS interceptado | Una consulta a una dirección que no existe recibe respuesta: alguien (el router o el ISP) contesta por tus DNS. |
| Tamaño de paquete (MTU) | Los paquetes grandes se pierden sin aviso. Un MTU menor avisado (1492 en PPPoE) está bien. |
| Reinicios del router | El router se reinició en las últimas 24 horas (se lee por SNMP, si lo configuraste). |
| Loops y tormentas | Respuestas duplicadas, broadcast fuera de lo normal o la MAC del router que cambia (ver [loops](verdict.md#loops-y-tormentas-de-broadcast)). |

**Solo esta máquina** (la que corre isitmyisp):

| Revisión | Amarillo o rojo cuando |
|---|---|
| Velocidad del enlace | La placa negocia half duplex, o menos de lo que tenés contratado (por ejemplo, 100 Mb/s con un plan de 300). |
| Errores de la placa | Los errores de la placa de red subieron mientras se medía: cable, conector o puerto. |
| Wi-Fi o cable | isitmyisp mide por Wi-Fi, así que tus problemas de Wi-Fi se mezclan con los del resto. Conviene un cable. |

## La nota

Al lado de la lista sale una nota de la A a la F: cada amarillo suma 1 y cada rojo 2. Sin puntos es A; con 1, B; hasta 3, C; hasta 5, D; más, F. Es un resumen. Lo que importa es la lista y qué hacer en cada línea.

## En el informe

El [informe para el ISP](report.md) suma el último chequeo del período como **Revisado del lado del cliente**. Así el soporte ve que ya miraste tu red antes de reclamar.
