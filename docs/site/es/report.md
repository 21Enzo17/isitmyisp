---
title: El informe para el ISP
nav: El informe
description: Qué tiene el informe de evidencia, qué prueba, qué no, y cómo usarlo en un reclamo.
---
# El informe para el ISP

El informe junta en un archivo todo lo que pasó en un período: qué falló, cuánto tiempo, dónde y con qué evidencia. Se saca desde **Informes** en el panel, en HTML o PDF, para el período que elijas.

![El informe: resumen, dónde estuvieron los problemas, línea de tiempo, calidad de llamadas e incidentes](/docs/img/es/report.png)

## Lo que tiene

**Para vos:**

- Un resumen en criollo: "3 incidentes, 1 h 6 min en total; 2 fueron dentro de la red de tu ISP".
- Una línea de tiempo y dónde estuvo cada problema: tu red, el ISP u otros.
- El tiempo en el enlace de respaldo, la calidad de las llamadas y la velocidad medida contra la contratada.

**Para el soporte y el NOC del ISP:**

- Un mensaje listo para pegar en el reclamo, con **solo los incidentes dentro de su red**. No les mandás tus problemas de Wi-Fi.
- Para cada uno, el salto y el sistema autónomo (AS) donde empieza la pérdida, que es la forma en que ellos ubican una falla.
- Cada captura de `mtr` que se tomó durante el incidente.
- La metodología: qué se midió, cómo y qué se descartó.

## Lo que prueba y lo que no

El informe no exagera, y eso es lo que lo hace difícil de ignorar:

- **Prueba** que hubo pérdida o latencia anormal, cuándo, cuánto duró y en qué tramo del camino empezó, con ICMP y TCP de acuerdo.
- **Descarta** tu red local cuando el router respondía bien; el ruido de ICMP, porque solo cuenta la pérdida que llega hasta el destino; un único sitio caído, porque mide varios destinos; y, si conectaste el router por SNMP, el enlace lleno por tráfico propio.
- **No prueba** lo que no midió. Si no hay datos del router, dice que no puede descartar un enlace saturado.

## Cómo usarlo en un reclamo

1. Sacá el informe del período del problema (los últimos 7 días, o desde la fecha en que empezó).
2. Al llamar o escribir al soporte, pegá el mensaje para el NOC y adjuntá el PDF.
3. Si te piden "reiniciar el módem", el informe muestra que tu red local estaba bien mientras fallaba la de ellos.
4. Guardá el número de reclamo. Si el problema sigue, el informe del período siguiente muestra que no se resolvió.

> El informe es tu evidencia técnica, no un dictamen legal. Si escalás el reclamo a defensa del consumidor, sirve como respaldo de lo que viviste.

## Desde la terminal

```bash
docker exec isitmyisp isitmyisp report --since 7d -o /data/informe.html
docker exec isitmyisp isitmyisp report --since 2026-11-01 --until 2026-11-08 --pdf -o /data/informe.pdf
```

Los informes generados desde datos de demo lo dicen en cada página.
