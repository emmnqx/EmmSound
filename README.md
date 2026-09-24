# EmmSound Studio
**EmmSound Studio** es un reproductor de música y gestor de reproducción de escritorio desarrollado en Python con interfaz gráfica Tkinter, integrado con la Web API de Spotify para control de reproducción, metadatos y letras sincronizadas.

## Características principales
* **Control de Reproducción:** Play, pausa, salto de pistas, repetición y volumen interactivo.
* **Crossfade inteligente:** Transiciones suaves de audio entre canciones (fade out / fade in).
* **Integración Spotify Web API:** Búsqueda en vivo, gestión de colas, navegación de playlists, transferencia entre dispositivos y sistema de autoplay.
* **Letras sincronizadas:** Consulta en tiempo real con historial local persistente.
* **Arquitectura multihilo:** Peticiones asíncronas en segundo plano para evitar bloqueos en la interfaz gráfica.
* **Gestión de credenciales:** Autenticación OAuth 2.0 desacoplada del código fuente.

## Tecnologías utilizadas
* **Lenguaje:** Python 3.x
* **GUI:** Tkinter / ttk
* **Librerías:** Spotipy, Pillow, Syncedlyrics

## Instalación y uso
1. Clonar el repositorio:
   `git clone https://github.com/emmnqx/EmmSound.git`
   `cd EmmSound`
2. Instalar dependencias:
   `pip install spotipy pillow syncedlyrics`
3. Configurar Spotify Developer:
   * Crear app en Spotify Developer Dashboard.
   * Añadir Redirect URI: `http://127.0.0.1:8500/callback`
   * Obtener Client ID y Client Secret.
4. Ejecutar:
   `python EmmSound.py`

## Licencia
Distribuido bajo fines demostrativos y educativos.
