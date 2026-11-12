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

## Informe mensual por mail

Además de las alertas, isitmyisp puede mandarte **todos los meses el informe del mes anterior**, sin que tengas que entrar al panel. Se activa en **Configuración → Informe mensual por mail**:

- Elegís el día (del 1 al 28) y la hora del envío, y los destinatarios. Si los dejás vacíos, va a los mismos de las alertas por email.
- El mensaje trae un resumen corto: cuántos incidentes hubo y cuánto duraron, de quién fue la culpa, el peor día, cuánto te afectó con el local abierto (si cargaste el [horario](features.md#horario-de-atencion)), el tiempo en el enlace de respaldo, la calidad de las llamadas y la velocidad medida.
- Adjunto va el **informe completo**, en PDF (en la imagen de Docker) o en HTML, listo para reenviarle a tu ISP.
- Usa el servidor de mail que configuraste para las alertas.
- Se manda **una sola vez por mes**, aunque el equipo se reinicie. Si el envío falla, se reintenta cada 15 minutos y el error queda a la vista en Configuración.
- **"Mandar ahora"** te manda el informe del mes anterior para ver cómo llega. Esa prueba no cuenta como el envío del mes.

## Si una alerta no llega

- Apretá **Mandar prueba**: el resultado de cada canal aparece arriba.
- Si un envío real falla, el error queda a la vista en **Configuración → Alertas**.
- Las contraseñas y los tokens nunca se muestran de vuelta: si dejás el campo vacío, se conserva el que estaba guardado.
