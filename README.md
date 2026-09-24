# EmmSound Studio

**EmmSound Studio** es un reproductor de música y gestor de reproducción de escritorio desarrollado en **Python** con una interfaz gráfica basada en **Tkinter**. Se integra directamente con la **Web API de Spotify** para ofrecer control total de la reproducción, visualización de metadatos, gestión de bibliotecas y sincronización de letras de canciones.

## Características principales

* **Control de Reproducción Completo:** Reproducción, pausa, salto de pistas, modo repetición y ajuste fino de volumen mediante sliders interactivos.
* **Transiciones Inteligentes (Crossfade):** Transiciones suaves de audio entre canciones mediante atenuación y subida progresiva de volumen (fade out / fade in).
* **Integración con Spotify Web API:**
  * Búsqueda en vivo de pistas con filtros detallados.
  * Gestión de cola de reproducción personalizada con posibilidad de definir un segundo de inicio.
  * Exploración de biblioteca personal de playlists y agregado directo de canciones a listas colaborativas o propias.
  * Detección y transferencia de reproducción entre dispositivos activos en la red.
  * Sistema de Autoplay inteligente basado en pistas recomendadas y top tracks del artista.
* **Módulo de Letras Sincronizadas:** Consulta de la letra en tiempo real de la pista en curso, con historial local persistente.
* **Arquitectura Multihilo:** Despacho de llamadas de red y peticiones a la API en segundo plano (`threading` y colas `queue.Queue`), garantizando que la interfaz gráfica permanezca fluida y sin bloqueos.
* **Almacenamiento Seguro de Credenciales:** Manejo de autenticación OAuth 2.0 desacoplado del código fuente; las credenciales se almacenan localmente en el entorno del usuario.

## Tecnologías utilizadas

* **Lenguaje:** Python 3.x
* **Interfaz Gráfica:** Tkinter / ttk
* **Manejo de API:** [Spotipy](https://spotipy.readthedocs.io/) (Spotify Web API wrapper)
* **Procesamiento de Imágenes:** Pillow (PIL)
* **Descarga de Letras:** Syncedlyrics

## Instalación y uso

### 1. Clonar el repositorio
```bash
git clone [https://github.com/emmnqx/EmmSound.git](https://github.com/emmnqx/EmmSound.git)
cd EmmSound
