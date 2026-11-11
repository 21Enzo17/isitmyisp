---
title: isitmyisp en una Raspberry Pi
nav: Raspberry Pi
description: De una Raspberry Pi nueva a la página de configuración en unos 15 minutos.
---
# isitmyisp en una Raspberry Pi

De una Raspberry Pi nueva a la página de configuración en unos 15 minutos.

## Qué hace falta

- **Raspberry Pi 4 o 5** (con 2 GB alcanza). Una Pi 3 funciona, pero es lenta para el PDF.
- **Fuente oficial** de la Pi. Con una fuente floja, la Pi se reinicia sola y esos cortes quedan registrados como si fueran caídas.
- **Tarjeta microSD de 16 GB o más**, idealmente "high endurance", porque la base de datos escribe cada 30 segundos. Si va a medir durante meses, mejor un SSD por USB.
- **Cable de red directo al router.** La sonda tiene que medir la conexión, no su propio Wi-Fi. Si va por Wi-Fi, el panel lo avisa y es más difícil distinguir un problema del Wi-Fi de uno del ISP.

## 1. Grabar el sistema (5 min)

Con [Raspberry Pi Imager](https://www.raspberrypi.com/software/):

1. Dispositivo: tu modelo. Sistema: **Raspberry Pi OS Lite (64-bit)** (está en "Raspberry Pi OS (other)").
2. En **Editar ajustes**:
   - Nombre del equipo: `isitmyisp`.
   - Usuario y contraseña: los elegís vos.
   - Zona horaria: `America/Argentina/Jujuy` (o la tuya). Es la hora que van a mostrar los informes.
   - Wi-Fi: dejalo vacío si vas a usar cable.
   - En la pestaña **Servicios**: activá SSH.
3. Grabá la tarjeta.

## 2. Encender y entrar (2 min)

Poné la tarjeta, conectá el cable de red y la fuente. Un minuto después, desde tu PC:

```bash
ssh tu-usuario@isitmyisp.local
```

Si `isitmyisp.local` no responde, buscá la IP de la Pi en la lista de dispositivos del router.

## 3. Instalar (5 a 10 min)

```bash
curl -fsSL https://isitmyisp.enzo-meneghini.com/install.sh | sh
```

Antes de hacer nada, el instalador muestra cada comando y te pregunta. Esto es lo que hace:

- Si falta Docker, lo instala con el instalador oficial (`get.docker.com`).
- Descarga la imagen. Mientras no haya imagen publicada para tu versión, la construye en la Pi, lo que tarda unos minutos más.
- Arranca el monitor: red del equipo, permiso para hacer ping, datos en un volumen de Docker y el panel en el puerto 8080 de tu red local.

Si preferís leerlo antes, abrí el link en el navegador: es texto plano y corto.

## 4. Configurar desde el navegador (3 min)

Al terminar, el instalador muestra un link como este:

```
http://192.168.1.50:8080/setup?token=…
```

Abrilo desde cualquier PC de la red. Ahí creás la cuenta de administrador y el [asistente](first-steps.md) te pide:

- las velocidades que contrataste;
- los servicios que usás (ARCA, bancos, pagos…);
- dónde querés que te lleguen las alertas.

Todo se puede saltar y completar más tarde.

**Reservá la IP de la Pi en el router** (la opción "DHCP estático" o "reserva"): así la dirección del panel no cambia.

## Después

| Para… | Hacé esto |
|---|---|
| Actualizar | Volvé a correr el instalador. Los datos se conservan. |
| Ver el registro | `docker logs -f isitmyisp` |
| Sacar un informe | Desde el panel, en **Informes**, o con `docker exec isitmyisp isitmyisp report --since 7d -o /data/informe.html` |
| Desinstalar | `curl -fsSL https://isitmyisp.enzo-meneghini.com/install.sh \| sh -s -- --uninstall` (los datos quedan en el volumen) |
| Dejar el panel solo en la Pi | Instalar con `sh -s -- --local` |
| Olvidé la contraseña | `docker exec -it isitmyisp isitmyisp admin reset-password <usuario>` |
