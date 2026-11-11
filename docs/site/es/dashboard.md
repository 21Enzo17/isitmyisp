---
title: El panel
description: Cómo leer el panel de isitmyisp, el camino, los colores, la línea de 24 horas y cada sección.
---
# El panel

El panel se actualiza solo cada 30 segundos. Arriba está la respuesta y abajo, la evidencia.

![El panel completo](/docs/img/es/dashboard-dark.png)

## Los colores dicen de quién es

En todo el panel, los colores indican **responsabilidad**, no "bien o mal":

| Color | Significa |
|---|---|
| Verde | Anda bien |
| Amarillo | El problema está de tu lado: tu Wi-Fi, tu red o tu router |
| Rojo | El problema está en la red de tu ISP |
| Gris | Otros: un servicio puntual, un sitio remoto, o no se puede saber |

Los colores siempre van acompañados de texto o de un ícono, así se entiende aunque no los distingas bien.

## El veredicto y el camino

Arriba de todo está el veredicto en una frase ("Falla la red de tu ISP", "Internet anda bien"…) y qué hacer.

Debajo está **el camino**: *Tu red → Tu ISP → Internet*, con la latencia y la pérdida de cada tramo. El tramo donde está el problema aparece marcado con "acá". Si la oficina está en el enlace de respaldo, el tramo del ISP lo indica.

## Qué descartamos

Cuando el problema es del ISP, una lista dice **qué descarta la evidencia** y **qué no puede descartar**:

- **Puede descartar:** tu red local, el ruido de ICMP, un único sitio caído y, si conectaste el router por SNMP, el enlace lleno por tráfico propio.
- **No puede descartar:** lo que no midió. Si no está conectado al router, no puede saber si el enlace estaba lleno, y lo dice.

Es lo que le da credibilidad frente al ISP.

## Las últimas 24 horas

Una línea de tiempo con varias filas que comparten el mismo eje:

- **Quién:** de quién fue la culpa en cada momento.
- **Pérdida** y **latencia** hacia internet.
- **Llamadas:** la calidad estimada, si las tenés configuradas.
- **Respaldo:** cuándo estuvo la oficina en el enlace secundario, si pasó.

Pasá el mouse por encima para ver los valores exactos de cada momento. Cada gráfico tiene también una vista en tabla.

## Tu red, punto por punto

Cada destino que se mide, con el último valor y las últimas 6 horas: tu router, el primer salto del ISP, los destinos de internet (por ping y por TCP) y tus servidores DNS.

## El enlace, la velocidad y las llamadas

- **Uso del enlace:** cuánto de lo contratado se está usando ahora, si conectaste el router por SNMP. Por encima del 85 % se marca como lleno.
- **Velocidad:** el último test, comparado con lo que contrataste.
- **Llamadas:** el MOS estimado (de 1 a 5) y si una llamada se escucharía bien ahora.

## Servicios y túneles

El estado de cada servicio y de cada túnel que agregaste: si responde, cuánto tarda y desde cuándo está así.

## Últimos incidentes

Los incidentes recientes, con la hora, la causa, la duración y si siguen abiertos. Si un mismo problema se repite seguido, se agrupa en una sola fila (por ejemplo, "×4"). El detalle completo, con la evidencia de cada uno, está en **Incidentes**.
