---
title: Instalar
description: Cómo instalar isitmyisp con un comando, a mano con Docker o sin Docker.
---
# Instalar

isitmyisp corre en un equipo con Linux que quede siempre prendido y **conectado por cable al router**: una Raspberry Pi, una mini PC o un servidor. Si arrancás de cero con una Raspberry, seguí la [guía de Raspberry Pi](raspberry-pi.md).

## Con un comando

```bash
curl -fsSL https://isitmyisp.enzo-meneghini.com/install.sh | sh
```

El instalador es corto y podés [leerlo antes](https://isitmyisp.enzo-meneghini.com/install.sh). Muestra cada comando y te pregunta antes de ejecutarlo:

1. Si falta Docker, ofrece instalarlo con el instalador oficial (`get.docker.com`).
2. Descarga la imagen de isitmyisp. Si todavía no hay una publicada para tu versión, la construye desde el código, lo que tarda unos minutos más.
3. Arranca el monitor y espera a que esté sano.
4. Te muestra el link para crear la cuenta de administrador.

Después, el [asistente de primeros pasos](first-steps.md) hace el resto desde el navegador.

### Opciones

Las opciones se pasan después de `sh -s --`, por ejemplo `curl … | sh -s -- --local`.

| Opción | Qué hace |
|---|---|
| `--local` | El panel queda solo en este equipo (por defecto se ve desde tu red local, con usuario y contraseña) |
| `--port 9090` | Otro puerto para el panel (por defecto 8080) |
| `--lang es` / `--lang en` | Idioma (por defecto, el del sistema) |
| `--tz America/Argentina/Jujuy` | Zona horaria de los informes (por defecto, la del equipo) |
| `--version 0.1.0` | Una versión puntual (por defecto, la última) |
| `--build` | Construir la imagen desde el código en vez de descargarla |
| `--dry-run` | Mostrar los comandos sin ejecutar nada |
| `-y` | No preguntar (para scripts) |
| `--uninstall` | Borrar el contenedor; las mediciones quedan en el volumen |

### Actualizar

Volvé a correr el mismo comando. Reemplaza el contenedor y conserva los datos, que viven en el volumen de Docker `isitmyisp`.

## A mano, con Docker

Si preferís escribir el comando vos:

> Hasta que se publique la imagen en GHCR, construila primero con `docker build -t ghcr.io/21enzo17/isitmyisp:latest https://github.com/21Enzo17/isitmyisp.git` (tarda unos minutos) y después corré el comando de abajo.

```bash
docker run -d --name isitmyisp --restart unless-stopped \
  --net=host --cap-add=NET_RAW \
  -e TZ=America/Argentina/Jujuy -v isitmyisp:/data \
  -v /run/systemd/resolve:/run/systemd/resolve:ro \
  ghcr.io/21enzo17/isitmyisp:latest --lang es monitor --web 0.0.0.0:8080
```

| Parte | Por qué |
|---|---|
| `--net=host` | Para ver tu router y tu camino reales. Dentro de la red de Docker, el "router" sería Docker |
| `--cap-add=NET_RAW` | Permiso para hacer ping. No hace falta modo privilegiado ni nada más del equipo |
| `-v isitmyisp:/data` | Donde quedan las mediciones, los incidentes y la configuración |
| `-v /run/systemd/resolve…` | Opcional: deja ver tus DNS reales en equipos con systemd-resolved |
| `TZ` | La hora que muestran los informes |
| `--web 0.0.0.0:8080` | El panel en tu red local. Con `127.0.0.1:8080` queda solo en el equipo; con `off`, sin panel |

Al arrancar por primera vez, el registro (`docker logs isitmyisp`) muestra un **token de un solo uso** para crear el administrador. Así nadie más en tu red puede adueñarse de la instancia antes que vos.

## Sin Docker

Hace falta Linux, `fping` (recomendado) o el `ping` de iputils, y `mtr`. El núcleo que mide no tiene dependencias de Python; el panel web y el PDF son extras.

```bash
pip install 'isitmyisp[web,pdf] @ git+https://github.com/21Enzo17/isitmyisp.git'
isitmyisp --lang es monitor --web 0.0.0.0:8080
```

También sirve para mirar puntualmente desde la terminal:

```bash
isitmyisp discover          # router, ISP, DNS, CGNAT, IPv6 y los tramos del camino
isitmyisp status -s 30      # medir 30 segundos y dar un veredicto
isitmyisp mtr 8.8.8.8       # mtr separando pérdida real de ruido ICMP
isitmyisp report --since 7d # el informe en HTML
```

## Probar sin instalar

La [demo](/es/isp/) muestra el panel completo con un día de datos de ejemplo. También podés correrla en tu equipo, sin medir nada (con la imagen ya construida o descargada):

```bash
docker run --rm -p 127.0.0.1:8090:8080 ghcr.io/21enzo17/isitmyisp:latest \
  --lang es demo --scenario isp --bind 0.0.0.0:8080
```
