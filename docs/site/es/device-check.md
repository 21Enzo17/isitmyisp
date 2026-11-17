---
title: Chequear desde este equipo
nav: Desde este equipo
description: Medí desde tu PC o tu celular y comparalo con la sonda en los mismos minutos: ¿es el Wi-Fi de ese equipo, el equipo mismo o la red?
---
# Chequear desde este equipo

La sonda mide desde un solo lugar: la máquina donde corre isitmyisp. Si la sonda anda bien pero tu celular no, el problema está entre ese celular y el router, y la sonda sola no lo ve. Este chequeo mide desde el equipo que tenés en la mano y lo cruza con lo que vio la sonda en los mismos minutos.

## Cómo se corre

Abrí el panel desde el equipo que querés probar (la PC, el celular, la notebook) y entrá en **Este equipo**. Tocá **Empezar** y esperá unos 15 segundos sin cerrar la página.

El navegador mide:

- **Hasta la sonda**: 20 pedidos chicos para la latencia, el jitter y la pérdida dentro de tu red, y una descarga y una subida para la velocidad en la red local.
- **Hasta internet**: pedidos HTTPS a los destinos en internet (**Configuración → Monitoreo → Medición → Destinos en internet**), para ver cuánto tardan en contestar. No se lee nada de esos sitios, solo el tiempo.

Necesita JavaScript, solo en esta página. El resto del panel sigue funcionando sin JavaScript.

## Qué te dice

| Resultado | Qué significa |
|---|---|
| **La red anda bien** | Desde este equipo y desde la sonda todo bien. Si una app sigue fallando, es esa app o ese servicio. |
| **Entre este equipo y el router** | La sonda andaba bien, pero hasta este equipo hubo pérdida, demora o poca velocidad. Es el Wi-Fi, un cable o un puerto del switch. No es el ISP. |
| **Este equipo** | La red local anda, la sonda sale bien a internet, pero este equipo no. Revisá una VPN, un firewall o antivirus, un proxy o una extensión del navegador. |
| **La sonda vio lo mismo** | El problema es compartido: vale el veredicto del panel (el router o el ISP). |
| **Sin datos de la sonda** | El monitor no estaba midiendo, así que no hay con qué comparar. |

Se marca como malo en la red local con 10 % de pérdida o más, 100 ms o más de mediana, 50 ms o más de jitter, o menos de 5 Mb/s de bajada o de subida. Hacia internet, con 20 % o más de pedidos fallidos.

La velocidad que mide es la de la red local (del equipo a la sonda), no la de internet. Si la sonda está en un Raspberry Pi o por Wi-Fi, la velocidad puede quedar limitada por la sonda.

Un destino que nunca contesta por HTTPS mientras los otros sí (algunas IP no tienen web) no cuenta como pérdida: se deja afuera. Lo mismo si la sonda tampoco llegaba a ese destino.

## Qué se guarda

Cada resultado se guarda con la hora, el sistema y el navegador ("Android · Chrome") y lo que se midió. La IP del equipo no se guarda: solo una huella corta para contar cuántos equipos distintos probaron. En **Este equipo** ves los últimos 30 días.

## En el informe

El [informe para el ISP](report.md) suma los chequeos del período como **Probado desde N equipos**. Así el soporte ve que el problema se repite en varios equipos, o que ya descartaste el Wi-Fi.
