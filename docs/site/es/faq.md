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

También puede ser el servidor. Un test de velocidad mide el camino hasta su servidor, y con algunos ISP el techo es el propio Cloudflare: en una fibra de 1000 Mbps donde Cloudflare daba 490, M-Lab y el servidor de Ookla del propio ISP daban más de 900. Por eso tu plan se compara con la mejor cifra de cada prueba, y por eso podés sumar [otros motores](features.md#motores): M-Lab, tu propia herramienta o los resultados de una PC por cable.

Cloudflare solo no dice si lo lento es tu acceso o la salida del ISP al resto de internet. Con un servidor iperf3 propio dentro de tu ISP y otro fuera, el resultado dice dónde está el cuello de botella. Ver [Dentro y fuera de tu ISP](features.md#dentro-y-fuera-de-tu-isp). Y una [prueba en hora pico](features.md#hora-pico) muestra si la línea se pone lenta a la noche.

## No me llegan las alertas

Apretá **Mandar prueba** en **Configuración → Avisos → Alertas** y mirá el resultado de cada canal. Ver [Alertas](alerts.md#si-una-alerta-no-llega).

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

## ¿Cómo sabe que es el ISP y no mi red?

Mide a la vez tu router, el primer router del ISP y varios destinos de internet, por ICMP y por TCP. Si falla todo lo de afuera y tu router anda, es el ISP. Si tu router también falla, es tu red. Si falla un solo destino, no es tu ISP.

Para no culpar a nadie por un paquete suelto, la pérdida tiene que ser estadísticamente significativa (intervalo de Wilson al 95 %), la latencia se compara con lo normal de cada destino y un incidente necesita dos ventanas malas seguidas. La pérdida en un salto intermedio que no llega al destino no cuenta: es el router priorizando tráfico, no un corte.

¿Se puede equivocar? Sí. Sin datos del router por SNMP, por ejemplo, no puede descartar que el problema sea tu propio enlace lleno, y el informe lo dice así. Los detalles están en [cómo decide](verdict.md).

## ¿Por qué pide `--net=host` y `NET_RAW`?

`--net=host` es para medir tu red real. Sin eso el contenedor ve la red interna de Docker, y "tu router" pasa a ser el puente de Docker. `NET_RAW` es el permiso para hacer ping. No usa `--privileged`. Del equipo solo monta su volumen de datos y, en solo lectura, `/run/systemd/resolve`, para saber qué DNS usás.

## ¿Tengo que confiar en un `curl | sh`?

No hace falta. El instalador muestra cada comando de Docker antes de correrlo y pide confirmación. Con `--dry-run` solo los imprime. Y si preferís no usarlo, es un solo `docker run`, que está en [Instalación](install.md#a-mano-con-docker).

## ¿Lo hiciste con IA?

Sí, lo escribí con Claude Code y no lo escondo: está en cada commit. El diseño, qué mide y cómo decide son míos, y salen de años de soporte de redes escuchando "¿es la red o es el proveedor?". Cada cambio pasa por tests antes de entrar, y lo uso todos los días en mi red. Si encontrás algo raro, [abrí una issue](https://github.com/21Enzo17/isitmyisp/issues), y si es de seguridad, [por privado](security.md#reportar-un-problema-de-seguridad).

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
- **Mide un DNS que no es el tuyo** (`100.100.100.100`, `127.0.0.53`): son reenviadores locales de Tailscale o de systemd-resolved, y isitmyisp ya no los usa; si no encuentra otro, mide tu router. Si tus equipos usan otro DNS, como un AdGuard Home o un Pi-hole, ponelo en **Configuración → Medición → Servidores DNS** (por ejemplo `192.168.1.22`, o `127.0.0.1` si corre en el mismo equipo).
- **El panel no se abre desde otro equipo:** si lo instalaste con `--local`, solo responde en ese equipo. Volvé a correr el instalador sin esa opción.

## ¿Cuánto cuesta?

El software es libre y gratis ([MIT](https://github.com/21Enzo17/isitmyisp/blob/main/LICENSE)). Si querés que te lo instalen y te lo atiendan, se puede contratar como servicio.

## Encontré un error o quiero proponer algo

Abrí una [issue en GitHub](https://github.com/21Enzo17/isitmyisp/issues).
