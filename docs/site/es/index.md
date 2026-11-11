---
title: isitmyisp · Documentación
nav: Qué es
description: isitmyisp te dice si un problema de internet es del Wi-Fi, del router o del ISP, y arma la evidencia para reclamar.
---
# ¿Es tu Wi-Fi, tu router o tu ISP?

isitmyisp es un monitor de conexión que se instala en tu red y la mide de forma continua. Cuando algo falla, te dice **dónde** está el problema, te lo explica sin tecnicismos y arma la evidencia que tu proveedor necesita para no responderte "reiniciá el módem".

<div class="cards" markdown>
<div markdown>
### Instalarlo
Un comando en una Raspberry Pi o cualquier equipo con Linux. [Instalar](install.md)
</div>
<div markdown>
### Probarlo sin instalar
La demo completa con datos de ejemplo, en el navegador. [Ver la demo](/es/isp/)
</div>
<div markdown>
### Entender el panel
Qué significa cada color, cada número y cada veredicto. [El panel](dashboard.md)
</div>
<div markdown>
### Reclamarle al ISP
El informe con la evidencia y cómo presentarlo. [El informe](report.md)
</div>
</div>

![El panel durante un problema en la red del ISP: el camino desde tu red hasta internet con el ISP marcado](/docs/img/es/incident.png)

## Para quién es

- **Comercios y oficinas chicas**, donde internet es la caja, el posnet, los teléfonos y la facturación. Una cajita (una Raspberry Pi alcanza) te dice de quién fue la culpa de cada corte y te da el informe para reclamar.
- **Técnicos y proveedores de IT** que atienden esas oficinas: un veredicto que le podés mostrar al cliente, el estado del enlace de respaldo y la calidad de las llamadas de un vistazo, y un informe que el ISP no puede ignorar.
- **Casas** que se cansaron del "reiniciá el módem" y quieren pruebas.

## Qué responde

**¿De quién es la culpa?** El panel muestra el camino *Tu red → Tu ISP → Internet* y marca el tramo donde está el problema. No se asusta con pings sueltos: para culpar a alguien, la falla tiene que ser estadísticamente significativa, sostenida, y verse tanto en ICMP como en TCP. [Cómo decide](verdict.md)

**¿Qué descartamos?** En cada problema del ISP, el informe lista lo que la evidencia descarta (tu red local, un sitio puntual, el enlace lleno por tus propias descargas) y lo que no puede descartar. Así no promete más de lo que puede probar.

**¿La oficina anda como tiene que andar?** Detecta cuándo pasás al enlace de respaldo, estima si una llamada se escucharía bien, chequea los servicios de los que depende tu negocio (ARCA, bancos, Mercado Pago…) y vigila los túneles VPN a tus sucursales. [Funciones](features.md)

**¿Quién me avisa?** Alertas por Telegram, email o webhook, solo cuando el problema dura, diciendo de quién es la culpa y qué hacer. [Alertas](alerts.md)

## Lo que no hace

- **No manda tus datos a ningún lado.** No hay nube ni telemetría: todo queda en tu equipo. Cada conexión externa está [listada](privacy.md).
- **No reemplaza a tu monitoreo de servidores.** "Tus servicios" existe para separar "mi internet" de "el servicio", no para competir con herramientas como Uptime Kuma.
- **No adivina.** Cuando la evidencia no alcanza, el veredicto lo dice.

isitmyisp es software libre ([licencia MIT](https://github.com/21Enzo17/isitmyisp/blob/main/LICENSE)), hecho por alguien que trabajó en el NOC de un ISP.
