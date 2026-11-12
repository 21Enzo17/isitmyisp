---
title: El panel
description: Cómo leer el panel de isitmyisp: el estado, los indicadores, el camino, las últimas 24 horas y cada tarjeta.
---
# El panel

El panel se actualiza solo cada 30 segundos. Arriba está la respuesta y debajo, la evidencia.

![El panel durante un problema en la red del ISP](/docs/img/es/incident.png)

## Los colores dicen de quién es

En todo el panel, los colores indican **responsabilidad**, no "bien o mal":

| Color | Significa |
|---|---|
| Verde | Anda bien |
| Naranja | El problema está de tu lado: tu Wi-Fi, tu red o tu router |
| Rojo | El problema está en la red de tu ISP |
| Gris | Otros: un servicio puntual, un sitio remoto, o no se puede saber |

Los colores siempre van acompañados de texto o de un ícono, así se entiende aunque no los distingas bien.

## Arriba: el estado y el tema

- **La píldora de estado** resume todo en dos palabras: "Conexión estable", "Falla tu ISP", "Problema de tu lado"…
- **El botón de la luna o el sol** cambia entre modo claro y oscuro, y lo recuerda en ese navegador. Hasta que lo toques, el panel sigue la configuración de tu sistema.

## El veredicto y los tres indicadores

A la izquierda está el veredicto en una frase ("Falla la red de tu ISP", "Internet anda bien"), con un ícono grande del color del responsable. Al lado hay tres indicadores, cada uno con un minigráfico de las últimas 24 horas:

- **Disponibilidad, 24 h:** qué parte del tiempo medido la conexión anduvo bien. La flecha compara con las 24 horas anteriores.
- **Sin cortes:** cuánto pasó desde el último problema en tu conexión. Si hay uno en curso, la tarjeta pasa a **"Con problemas hace"** y muestra su duración en rojo.
- **Latencia a internet:** la mediana de lo que tardan los destinos de internet en responder. Si bajó respecto del día anterior, la flecha es verde.

## Últimas 24 horas

Una línea de tiempo con varias filas que comparten el mismo eje:

- **Quién:** de quién fue la culpa en cada momento.
- **Pérdida** y **latencia** hacia internet.
- **Llamadas:** la calidad estimada, si las tenés configuradas.
- **Respaldo:** cuándo estuvo la oficina en el enlace secundario, si pasó.

Pasá el mouse por encima para ver los valores exactos de cada momento. Debajo hay una vista en tabla con los mismos datos.

## Destinos monitoreados

Cada destino que se mide, con su latencia actual y su minigráfico de las últimas 6 horas: tu router, el primer salto del ISP, los destinos de internet y tus servidores DNS. El punto de color dice cómo está. Si un destino pierde paquetes, el porcentaje aparece en rojo debajo de la latencia.

## Últimos eventos

Los incidentes recientes, del más nuevo al más viejo, con hace cuánto empezaron y cuánto duraron ("hace 2 h (5 min)"). Si un mismo problema se repite seguido, se agrupa en una sola línea (por ejemplo, "×4"). "Ver todos" lleva a **Incidentes**, con la evidencia completa de cada uno.

## Dónde está el problema

**El camino**: *Tu red → Tu ISP → Internet*, con la latencia y la pérdida de cada tramo. El punto donde está el problema aparece marcado con "La evidencia apunta acá". Si la oficina está en el enlace de respaldo, el tramo del ISP lo indica.

Debajo del camino están:

- **Qué hacer**, según quién es el responsable.
- **El incidente activo**, si hay uno, con su evidencia y **qué descarta la evidencia** (tu red local, el ruido de ICMP, un único sitio caído y, si conectaste el router por SNMP, el enlace lleno por tráfico propio) y qué no puede descartar.
- **El resumen del día** y los botones del **informe para tu ISP** (en HTML o PDF).
- **Cortes breves**: los problemas de menos de un minuto, que no llegan a ser incidente.

## Tu enlace, llamadas, servicios y túneles

- **Tu enlace (desde tu router):** cuánto de lo contratado se está usando ahora, si conectaste el router por SNMP. Por encima del 85 % se marca como lleno. Debajo, el último **test de velocidad** comparado con lo que contrataste.
- **Calidad para llamadas:** el MOS estimado (de 1 a 5) y si una llamada se escucharía bien ahora.
- **Servicios, dispositivos y túneles:** si cada uno responde, cuánto tarda y desde cuándo está así. Los [dispositivos del local](features.md#dispositivos-del-local) (posnet, impresora, cámaras…) muestran su tipo y su dirección.
