---
title: Primeros pasos
description: Crear la cuenta de administrador y dejar isitmyisp útil desde el primer día con el asistente.
---
# Primeros pasos

Ya está midiendo desde que arrancó. Lo que falta es contarle tres cosas de tu negocio para que el veredicto sea útil desde el primer día. El asistente las pide en unos minutos.

## 1. Crear el administrador

Abrí el link que mostró el instalador (`http://<ip-del-equipo>:8080/setup?token=…`) desde cualquier PC de la red. Elegí un usuario y una contraseña de al menos 10 caracteres.

> ¿Perdiste el link? El token aparece en el registro: `docker logs isitmyisp`. Si pasaron más de 24 horas, pedí uno nuevo con `docker exec isitmyisp isitmyisp admin setup-token`.

## 2. El asistente

Después de crear la cuenta se abre **Primeros pasos**. Cada paso se puede saltar, y todo se puede cambiar después en **Configuración**, donde también hay un botón para volver a abrir el asistente.

### Tu plan

Arriba aparece lo que ya detectó: tu router, tu ISP con su número de sistema autónomo (AS), si estás detrás de CGNAT y si la sonda está conectada por Wi-Fi. Abajo te pide las **velocidades que contrataste**, que están en la factura o en el contrato.

Con esas velocidades, isitmyisp distingue un enlace lleno por tus propias descargas de un ISP que falla. También las usa para comparar el [test de velocidad](features.md#test-de-velocidad), que está apagado salvo que lo actives.

### Tus servicios

Una lista de servicios listos para tildar: ARCA (Clave Fiscal, facturación electrónica, WSAA), Rentas Jujuy, los bancos principales, Mercado Pago, Payway, Google Workspace, Microsoft 365, WhatsApp Web y Zoom. Cada uno dice exactamente qué chequea.

Si uno se cae mientras internet anda bien, el panel dice que es ese servicio y no tu conexión. Tus propios sistemas (el ERP, el servidor de una sucursal) se agregan desde Configuración.

### Alertas

Telegram o un webhook (Discord, Slack, Home Assistant…), con un botón para **mandar una prueba**. La dirección del panel que va en los mensajes se completa sola. El email se configura en Configuración. Más detalles en [Alertas](alerts.md).

### Listo

Un resumen de lo configurado y de lo que quedó pendiente, con links a lo opcional: túneles, el router por SNMP, el test de velocidad, el modo TV y los usuarios.

## 3. Reservar la IP del equipo

En el router, reservá la dirección del equipo donde corre isitmyisp. La opción suele llamarse "DHCP estático", "reserva" o "IP fija". Así el link del panel no cambia.

## Y ahora

Dejalo midiendo. A las pocas horas ya tiene una línea de base de tu conexión; a los pocos días, un historial que podés mostrarle al ISP. Mientras tanto:

- Aprendé a leer [el panel](dashboard.md).
- Sumá a alguien más con acceso de solo lectura, desde **Configuración → Usuarios**.
- Poné el [modo TV](features.md#modo-tv) en una pantalla de la oficina.
