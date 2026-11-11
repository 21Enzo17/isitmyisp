---
title: Seguridad
description: Cuentas, modos de acceso, encabezados de seguridad y cómo recuperar el acceso.
---
# Seguridad

El panel tiene la configuración de tu red y la evidencia de tus incidentes, así que está protegido como corresponde. La autenticación usa bibliotecas auditadas, no criptografía casera.

| | |
|---|---|
| **Cuentas** | Sesiones de Flask-Login, contraseñas con **Argon2id** y límite de intentos de inicio de sesión |
| **Primer administrador** | Se crea con un token de un solo uso que aparece en el registro, así nadie en tu red puede adueñarse de la instancia antes que vos |
| **CSRF** | Token en cada formulario y control de que el pedido venga del mismo origen |
| **Encabezados** | CSP estricta (sin ningún script), `X-Frame-Options: DENY`, cookies `HttpOnly` y `SameSite` |
| **Servidor** | Waitress, un servidor WSGI de producción; ignora los `X-Forwarded-*` que no vienen de un proxy de confianza |

El panel **no usa JavaScript**: ni siquiera los gráficos, cuyo hover es CSS puro. Así la política de seguridad puede prohibir todos los scripts.

## Modos de acceso

Se eligen en **Configuración → Acceso**:

- **Local** (por defecto): cuentas con contraseña, de administrador o de lector. Ver [Usuarios](features.md#usuarios).
- **Proxy:** confía en un encabezado de usuario (`Remote-User`) que pone **Authelia, Authentik, oauth2-proxy o Tailscale**, solo desde las direcciones de proxy que indiques. Así tenés SSO, doble factor y passkeys. El panel no te deja pasar a este modo si tu propio pedido no está llegando por el proxy, para que no te quedes afuera.
- **Ninguno:** solo se permite mientras el panel escucha en localhost, y la configuración queda de solo lectura.

## Exponerlo fuera de tu red

No publiques el puerto 8080 en internet. Para verlo desde afuera, usá una VPN (WireGuard, Tailscale) o un proxy con HTTPS y autenticación. Detrás de HTTPS, agregá `-e ISITMYISP_SECURE_COOKIES=1` para que las cookies solo viajen cifradas.

## Si te quedaste afuera

Desde la consola del equipo:

```bash
docker exec -it isitmyisp isitmyisp admin reset-password <usuario>
docker exec -it isitmyisp isitmyisp admin auth-mode local
docker exec -it isitmyisp isitmyisp admin setup-token
```

## Reportar un problema de seguridad

Si encontrás una vulnerabilidad, no abras una issue pública: escribí por privado al autor desde [GitHub](https://github.com/21Enzo17).
