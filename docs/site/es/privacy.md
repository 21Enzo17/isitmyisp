---
title: Privacidad
description: Cada conexión externa que hace isitmyisp, cuándo y qué manda. Sin nube ni telemetría.
---
# Privacidad

isitmyisp está pensado para correr meses en tu red. Por defecto **nunca manda tus datos ni las IP de tu camino a terceros**. No hay nube, cuentas externas ni telemetría: todo queda en el equipo donde corre.

## Cada conexión externa

| Conexión | Cuándo | Qué manda | Por defecto |
|---|---|---|---|
| ICMP a tu router, al primer salto del ISP, 1.1.1.1, 8.8.8.8 y 9.9.9.9 | siempre | ping (64 bytes) | sí |
| Un ping con TTL limitado hacia 1.1.1.1 | una vez por ventana | un ping que vence en el primer router del ISP (detecta el respaldo) | sí |
| TCP a 1.1.1.1, 8.8.8.8 y 9.9.9.9, puerto 443 | siempre | SYN y cierra (sin datos ni TLS) | sí |
| Consultas DNS a tus propios servidores | siempre | consultas A de www.google.com, www.cloudflare.com y www.wikipedia.org | sí |
| `mtr` a 1.1.1.1 | al descubrir el camino y en incidentes | sondas ICMP | sí |
| iptoasn.com | solo cuando apretás el botón en Configuración o corrés `update-asn` | una descarga HTTPS del dataset público (sin consultas por IP) | manual |
| Team Cymru whois | solo con `--asn-online` | las IP públicas de tu camino | **no** |
| api.ipify.org | solo con `--public-ip` | un pedido HTTPS (les revela tu IP pública) | **no** |
| Tus servicios | solo los que agregues | un GET HTTP (o conexión TCP) cada 30 s | **no** |
| speed.cloudflare.com | solo si activás el test de velocidad | descargas y subidas de unos 15 s; Cloudflare ve tu IP pública | **no** |
| Tu router por SNMP | solo si lo conectás | lectura de los contadores de la WAN y la CPU | **no** |
| Telegram, tu servidor SMTP o tu webhook | solo si activás alertas | el texto de la alerta | **no** |

**Consumo de datos:** alrededor de 1,3 GB por mes con la configuración por defecto.

## Lo que guarda y cuánto tiempo

- Mediciones por destino: **35 días**, lo justo para un informe mensual.
- Veredictos por ventana, incidentes y su evidencia: **unos 13 meses**.
- Lo viejo se borra solo, cada hora.
- Todo vive en el volumen de Docker `isitmyisp` (o en `~/.local/share/isitmyisp` sin Docker). Si lo borrás, no queda nada en ningún lado.

## La demo

La [demo pública](/es/isp/) son páginas estáticas generadas con datos inventados. No mide nada, no tiene cuentas y no guarda lo que hacés.
