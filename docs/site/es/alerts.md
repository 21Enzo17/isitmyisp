---
title: Alertas
description: Avisos por Telegram, email o webhook cuando se cae internet, un servicio o un túnel.
---
# Alertas

Un mensaje cuando se cae internet, un servicio o un túnel. Cada uno dice **de quién es la culpa y qué hacer**. Se configuran en **Configuración → Alertas** (o en el asistente) y cada canal tiene un botón para mandar una prueba.

## Cuándo avisa

- **Solo si dura.** Por defecto avisa cuando el problema lleva al menos 2 minutos; podés cambiarlo de 0 a 240. Un corte de segundos no te despierta.
- **También cuando se resuelve**, con la duración total. Se puede apagar.
- **Con un link al panel**, si completás la dirección del panel. El asistente la completa sola con la dirección desde la que entraste.

## Telegram

1. Creá un bot hablándole a [@BotFather](https://t.me/BotFather) y copiá el token (algo como `123456789:AA…`).
2. Mandale cualquier mensaje a tu bot.
3. Conseguí tu chat id con [@userinfobot](https://t.me/userinfobot). Para un grupo o un canal, el id empieza con `-100…`, o usá `@nombre_del_canal`.

## Email

Cualquier servidor SMTP: el de tu dominio o el de tu proveedor de correo. Completá el servidor, el puerto (587 con STARTTLS o 465 con SSL), el usuario, la contraseña, el remitente y los destinatarios separados por comas.

Con Gmail hace falta una [contraseña de aplicación](https://support.google.com/accounts/answer/185833), no la contraseña de la cuenta.

## Webhook

Una URL que recibe un POST con el aviso. Las de Discord y Slack se detectan solas y reciben el formato de cada uno; cualquier otra recibe un JSON con el evento, el título, el texto y los datos del incidente. Sirve para Home Assistant, n8n o tu propio sistema.

## Si una alerta no llega

- Apretá **Mandar prueba**: el resultado de cada canal aparece arriba.
- Si un envío real falla, el error queda a la vista en **Configuración → Alertas**.
- Las contraseñas y los tokens nunca se muestran de vuelta: si dejás el campo vacío, se conserva el que estaba guardado.
