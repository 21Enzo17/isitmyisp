---
title: Preguntas frecuentes
nav: Preguntas
description: Dudas comunes y solución de problemas.
---
# Preguntas frecuentes

## ¿Me va a hacer lenta la conexión?

No. Son pings chicos cada 2 segundos a unos pocos destinos, alrededor de 1,3 GB por mes. Lo único que usa ancho de banda de verdad es el [test de velocidad](features.md#test-de-velocidad), que está apagado salvo que lo actives.

## ¿Lo puedo conectar por Wi-Fi?

Se puede, pero no conviene. Si la sonda está por Wi-Fi, un problema del Wi-Fi se mezcla con uno del ISP. Conectala por cable al router; el panel avisa cuando está por Wi-Fi.

## ¿Funciona con cualquier proveedor?

Sí. No necesita nada del ISP: mide desde tu lado. Detecta el ISP por su número de sistema autónomo (AS), también si estás detrás de CGNAT o de doble NAT.

## ¿Tengo que dejar una PC prendida?

Tiene que haber un equipo prendido todo el tiempo, pero puede ser una Raspberry Pi, que consume como un cargador de celular. Ver la [guía de Raspberry Pi](raspberry-pi.md).

## El panel dice "Midiendo…" o "Chequeando…" hace rato

- **Recién instalado:** las primeras ventanas tardan uno o dos minutos.
- **Siempre:** el monitor no está corriendo. Revisá el estado con `docker ps` y el registro con `docker logs isitmyisp`.
- **En un servicio puntual:** todavía no hay ningún chequeo completo de ese servicio. Debería resolverse en 30 segundos.

## El router "pierde" pings pero internet anda

Es normal en muchos routers y firewalls de empresa: le dan baja prioridad a los pings dirigidos a ellos. isitmyisp lo detecta y no lo cuenta como problema. Ver [cómo decide](verdict.md).

## ¿Por qué el test de velocidad da menos que lo contratado?

Puede ser el ISP o algo de tu lado: otros equipos usando internet en ese momento, o el Wi-Fi del equipo que mide. El resultado avisa cuando el límite parece ser tu Wi-Fi. Si conectaste el router por SNMP, también muestra todo lo que pasaba por la WAN durante el test.

## No me llegan las alertas

Apretá **Mandar prueba** en **Configuración → Alertas** y mirá el resultado de cada canal. Ver [Alertas](alerts.md#si-una-alerta-no-llega).

## Olvidé la contraseña

```bash
docker exec -it isitmyisp isitmyisp admin reset-password <usuario>
```

## ¿Cómo actualizo?

Volvé a correr el [instalador](install.md#actualizar). Los datos se conservan.

## ¿Cómo lo desinstalo?

```bash
curl -fsSL https://isitmyisp.enzo-meneghini.com/install.sh | sh -s -- --uninstall
```

Las mediciones quedan en el volumen `isitmyisp`. Para borrarlas también: `docker volume rm isitmyisp`.

## ¿En qué se diferencia de Uptime Kuma, SmokePing o PingPlotter?

| | Qué te dice |
|---|---|
| **Uptime Kuma** | Si un sitio o servicio responde. No sabe si la culpa es de tu red, de tu ISP o del servicio. |
| **SmokePing / PingPlotter** | Gráficos de latencia y pérdida hacia cada destino. Leerlos y concluir quién falla queda a tu cargo, y la "pérdida" en saltos intermedios suele ser ruido. |
| **isitmyisp** | **De quién es la culpa**, en una frase: tu Wi-Fi o tu router, la red de tu ISP, un servicio puntual o tu DNS. Separa la pérdida real del ruido de ICMP, detecta cortes intermitentes y el enlace de respaldo, dice si saturaste tu propio enlace (con el router conectado por SNMP) y arma el informe que el ISP no puede ignorar. |

Se complementan: muchos usan Uptime Kuma para sus servicios e isitmyisp para la conexión.

## ¿Cómo hago un backup, o lo paso a otro equipo?

Todo está en el volumen de Docker `isitmyisp`: la configuración, los usuarios y las mediciones. Para guardarlo en un archivo:

```bash
docker stop isitmyisp
docker run --rm --entrypoint tar -v isitmyisp:/data -v "$PWD":/backup 21enzo03/isitmyisp czf /backup/isitmyisp-backup.tgz -C /data .
docker start isitmyisp
```

En el equipo nuevo, instalalo con el [instalador](install.md), detenelo y restaurá el archivo:

```bash
docker stop isitmyisp
docker run --rm --entrypoint tar -v isitmyisp:/data -v "$PWD":/backup 21enzo03/isitmyisp xzf /backup/isitmyisp-backup.tgz -C /data
docker start isitmyisp
```

## El monitor no arranca o no ve mi red

- **"Operation not permitted" al hacer ping:** al contenedor le falta el permiso para hacer ping. Corré el [instalador](install.md) de nuevo o agregá `--cap-add=NET_RAW`.
- **Ve una sola dirección rara en lugar de tu router:** falta `--net=host`. Sin eso mide la red interna de Docker, no la tuya.
- **En Docker Desktop (Mac o Windows):** `--net=host` no ve la red real del equipo, así que el camino y el router salen mal. Usalo en Linux: una Raspberry Pi, una mini PC o un servidor.
- **El panel no se abre desde otro equipo:** si lo instalaste con `--local`, solo responde en ese equipo. Volvé a correr el instalador sin esa opción.

## ¿Cuánto cuesta?

El software es libre y gratis ([MIT](https://github.com/21Enzo17/isitmyisp/blob/main/LICENSE)). Si querés que te lo instalen y te lo atiendan, se puede contratar como servicio.

## Encontré un error o quiero proponer algo

Abrí una [issue en GitHub](https://github.com/21Enzo17/isitmyisp/issues).
