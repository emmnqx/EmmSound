import os
import io
import re
import sys
import json
import queue
import threading
import webbrowser
import urllib.request

if sys.platform == "win32":
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException


def reiniciar_segundo_inicial(entry_widget, valor="0"):
    entry_widget.delete(0, "end")
    entry_widget.insert(0, valor)

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".emmsound_studio")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
CACHE_PATH = os.path.join(CONFIG_DIR, "token_cache.json")

def cargar_configuracion():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    client_id = (datos.get("client_id") or "").strip()
    client_secret = (datos.get("client_secret") or "").strip()

    if not client_id or not client_secret:
        return None

    return {"client_id": client_id, "client_secret": client_secret}


def guardar_configuracion(client_id, client_secret):

    os.makedirs(CONFIG_DIR, exist_ok=True)

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {"client_id": client_id, "client_secret": client_secret},
            f, ensure_ascii=False, indent=2
        )


REDIRECT_URI = 'http://127.0.0.1:8500/callback'

SCOPE = (
    "user-read-currently-playing "
    "user-read-playback-state "
    "user-modify-playback-state "
    "playlist-read-private "
    "playlist-read-collaborative "
    "playlist-modify-public "
    "playlist-modify-private"
)

ARCHIVO_LETRAS = "letras.txt"
ARCHIVO_LETRA_ACTUAL = "letra_actual.txt"
DURACION_CROSSFADE = 1.5
PASOS_CROSSFADE = 5
INTERVALO_ACTUALIZACION_MS = 3000
MARGEN_FIN_CANCION_MS = INTERVALO_ACTUALIZACION_MS + 2000
CANCIONES_AUTOPLAY_RECOMENDADAS = 5
TAMANO_PORTADA = 96
TIMEOUT_PETICIONES = 10
NEGRO_FONDO = "#0B0B0B"
NEGRO_PANEL = "#151515"
NEGRO_PANEL_2 = "#1D1D1D"
VERDE = "#1DB954"
VERDE_HOVER = "#22D25F"
VERDE_OSCURO = "#14532D"
BLANCO = "#F5F5F5"
GRIS_TEXTO = "#A6A6A6"
ROJO_SUAVE = "#E05252"
ROJO_HOVER = "#3A1F1F"
BORDE = "#2A2A2A"
CARACTERES_BARRA_DISPOSITIVO = "▃▄▅▆▇"
BARRA_DISPOSITIVO_INACTIVO = "▁▁▁▁"
F_TITULO = ("Segoe UI", 20, "bold")
F_SUBTITULO = ("Segoe UI", 13, "bold")
F_TEXTO = ("Segoe UI", 10)
F_TEXTO_B = ("Segoe UI", 10, "bold")
F_PEQUENA = ("Segoe UI", 8)
F_MONO = ("Consolas", 10)

class TrackInfo:

    def __init__(
        self,
        index,
        name,
        artist,
        album,
        uri,
        duration_ms=0,
        start_second=0,
        artwork_url=None,
        explicit=False
    ):

        self.index = index
        self.name = name
        self.artist = artist
        self.album = album
        self.uri = uri
        self.duration_ms = duration_ms
        self.start_second = start_second
        self.artwork_url = artwork_url
        self.explicit = bool(explicit)

    @property
    def nombre_mostrado(self):
        return f"{self.name}  🅴" if self.explicit else self.name

    @property
    def duracion_texto(self):

        segundos = self.duration_ms // 1000

        return (
            f"{segundos // 60:02d}:"
            f"{segundos % 60:02d}"
        )

    def __str__(self):

        return (
            f"{self.index}. {self.name} - "
            f"{self.artist} ({self.duracion_texto})"
        )

class GestorMinisterioSonido:

    def __init__(
        self,
        client_id,
        client_secret,
        redirect_uri,
        scope,
        cache_path=None
    ):

        self.sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=scope,
                open_browser=True,
                cache_path=cache_path
            ),
            requests_timeout=TIMEOUT_PETICIONES,
            retries=2
        )

        self.lista_canciones = []
        self.fila_reproduccion = []
        self.playlist_actual = []
        self.nombre_playlist = ""
        self.biblioteca_playlists = []
        self.ultimo_uri = None
        self.usuario_id = None

    def obtener_usuario_id(self):

        if self.usuario_id is None:
            perfil = self.sp.me()
            self.usuario_id = perfil.get('id')

        return self.usuario_id

    def crear_track_info(self, track, index):

        if not track:
            return None

        artistas = track.get('artists', [])

        artista = (
            artistas[0].get('name', 'Desconocido')
            if artistas else 'Desconocido'
        )

        album = track.get('album', {})
        imagenes = album.get('images', []) or []
        artwork_url = imagenes[0].get('url') if imagenes else None

        return TrackInfo(
            index=index,
            name=track.get('name', 'Desconocida'),
            artist=artista,
            album=album.get('name', 'Desconocido'),
            uri=track.get('uri'),
            duration_ms=track.get('duration_ms', 0),
            artwork_url=artwork_url,
            explicit=track.get('explicit', False)
        )

    def obtener_estado_actual(self):

        return self.sp.current_playback()

    def obtener_dispositivo_activo(self):

        dispositivos = self.sp.devices()

        for d in dispositivos.get('devices', []):

            if d.get('is_active'):
                return d

        return None

    def listar_dispositivos(self):

        resultado = self.sp.devices()

        return resultado.get('devices', [])

    def reproducir_en_dispositivo(self, device_id, forzar_reproduccion=True):
        self.sp.transfer_playback(
            device_id=device_id, force_play=forzar_reproduccion
        )

    def pausar(self):

        self.sp.pause_playback()

    def reanudar(self):

        self.sp.start_playback()

    def alternar_reproduccion(self):

        estado = self.obtener_estado_actual()

        if estado and estado.get('is_playing'):
            self.pausar()
            return False

        self.reanudar()
        return True

    def cambiar_volumen(self, cantidad):

        dispositivo = self.obtener_dispositivo_activo()

        if dispositivo is None:
            raise RuntimeError("No hay dispositivo activo.")

        if not dispositivo.get('supports_volume', False):
            raise RuntimeError(
                f"'{dispositivo.get('name')}' no permite "
                "controlar el volumen mediante la Web API."
            )

        actual = dispositivo.get('volume_percent')

        if actual is None:
            actual = 50

        nuevo = max(0, min(100, actual + cantidad))

        self.sp.volume(nuevo, device_id=dispositivo.get('id'))

        return nuevo

    def establecer_volumen(self, valor):

        dispositivo = self.obtener_dispositivo_activo()

        if dispositivo is None:
            raise RuntimeError("No hay dispositivo activo.")

        if not dispositivo.get('supports_volume', False):
            raise RuntimeError(
                f"'{dispositivo.get('name')}' no permite "
                "controlar el volumen mediante la Web API."
            )

        valor = max(0, min(100, int(valor)))

        self.sp.volume(valor, device_id=dispositivo.get('id'))

        return valor

    def buscar_canciones(self, query):
        resultados = self.sp.search(
            q=query, limit=10, type='track'
        )

        tracks = resultados['tracks']['items']

        self.lista_canciones = []

        for i, track in enumerate(tracks, start=1):

            objeto = self.crear_track_info(track, i)

            if objeto:
                self.lista_canciones.append(objeto)

        return self.lista_canciones

    def reproducir_cancion(self, track, segundo=0):

        dispositivo = self.obtener_dispositivo_activo()

        if dispositivo is None:
            raise RuntimeError("No hay dispositivo activo.")

        self.sp.start_playback(
            device_id=dispositivo.get('id'),
            uris=[track.uri],
            position_ms=int(segundo * 1000)
        )

        self.ultimo_uri = track.uri

    def agregar_a_fila(self, track, segundo=0):

        nuevo = TrackInfo(
            index=len(self.fila_reproduccion) + 1,
            name=track.name,
            artist=track.artist,
            album=track.album,
            uri=track.uri,
            duration_ms=track.duration_ms,
            start_second=segundo,
            explicit=getattr(track, 'explicit', False)
        )

        self.fila_reproduccion.append(nuevo)

        return nuevo

    def eliminar_de_fila(self, indice):

        if not (0 <= indice < len(self.fila_reproduccion)):
            raise IndexError("Número inválido.")

        return self.fila_reproduccion.pop(indice)

    def obtener_recomendaciones(self, uri_semilla, limite=CANCIONES_AUTOPLAY_RECOMENDADAS):
        coincidencia = re.match(r'^spotify:track:([A-Za-z0-9]+)$', uri_semilla or '')

        if not coincidencia:
            return []

        track_id = coincidencia.group(1)

        try:
            resultado = self.sp.recommendations(seed_tracks=[track_id], limit=limite)
            tracks = resultado.get('tracks', [])
        except SpotifyException:
            tracks = self._top_tracks_del_mismo_artista(track_id, limite)

        canciones = []

        for i, track in enumerate(tracks, start=1):

            objeto = self.crear_track_info(track, i)

            if objeto:
                canciones.append(objeto)

        return canciones

    def _top_tracks_del_mismo_artista(self, track_id, limite):
        track = self.sp.track(track_id)
        artistas = track.get('artists', [])

        if not artistas:
            return []

        artista_id = artistas[0].get('id')

        if not artista_id:
            return []

        resultado = self.sp.artist_top_tracks(artista_id)

        candidatos = [
            t for t in resultado.get('tracks', [])
            if t.get('id') != track_id
        ]

        return candidatos[:limite]
    def agregar_a_playlist(self, playlist_id, track_uri):

        self.sp.playlist_add_items(playlist_id, [track_uri])

    def obtener_biblioteca_playlists(self):

        playlists = []

        resultados = self.sp.current_user_playlists(limit=50)

        while resultados:

            playlists.extend(resultados.get('items', []))

            if resultados.get('next'):
                resultados = self.sp.next(resultados)
            else:
                break

        self.biblioteca_playlists = playlists

        return playlists

    def obtener_biblioteca_con_propietario(self):
        self.obtener_usuario_id()

        return self.obtener_biblioteca_playlists()

    def cargar_playlist(self, playlist_id, nombre, es_propia=True):
        if not es_propia:
            raise RuntimeError(
                f"'{nombre}' no es una playlist tuya (ni colaborativa). "
                "Desde 2026 Spotify ya no permite ver el contenido de "
                "playlists ajenas a través de la API — solo las que "
                "posees o en las que colaboras."
            )

        canciones = []
        numero = 1
        total_items = 0

        try:
            resultados = self.sp._get(
                f"playlists/{playlist_id}/items",
                limit=100,
                market='from_token',
                additional_types='track'
            )
        except SpotifyException:
            resultados = self.sp.playlist_items(
                playlist_id,
                limit=100,
                market='from_token',
                additional_types=('track',)
            )

        while resultados:

            for elemento in resultados.get('items', []):

                total_items += 1

                track = elemento.get('item') or elemento.get('track')

                if not track:
                    continue

                objeto = self.crear_track_info(track, numero)

                if objeto:
                    canciones.append(objeto)
                    numero += 1

            if resultados.get('next'):
                resultados = self.sp.next(resultados)
            else:
                break

        self.playlist_actual = canciones
        self.nombre_playlist = nombre

        return canciones, total_items

    @staticmethod
    def limpiar_letra(letra):
        patron_marca = re.compile(r'^(\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\])\s*(.*)$')

        lineas = []
        ultimo_texto = None

        for linea in (letra or '').splitlines():
            linea = re.sub(r'[ \t]+', ' ', linea).strip()

            coincidencia = patron_marca.match(linea)
            if coincidencia:
                marca, texto = coincidencia.group(1), coincidencia.group(2).strip()
            else:
                marca, texto = None, linea

            if not texto:
                if ultimo_texto != "":
                    lineas.append("")
                ultimo_texto = ""
                continue

            if texto == ultimo_texto:
                continue

            lineas.append(f"{marca} {texto}" if marca else texto)
            ultimo_texto = texto

        while lineas and lineas[-1] == "":
            lineas.pop()

        return "\n".join(lineas)

    def importar_letra_actual(self):
        try:
            import syncedlyrics
        except ImportError:
            raise RuntimeError(
                "Falta instalar la librería de letras.\n"
                "Ejecuta en tu terminal: pip install syncedlyrics"
            )

        estado = self.obtener_estado_actual()
        if not estado or not estado.get('item'):
            raise RuntimeError("No hay una canción reproduciéndose ahora mismo.")

        track = estado['item']
        titulo = track.get('name', '')
        artista = track['artists'][0]['name'] if track.get('artists') else ''
        letra = syncedlyrics.search(f"{titulo} {artista}")

        if not letra:
            raise RuntimeError(f"No se encontró letra para '{titulo}'.")

        letra = self.limpiar_letra(letra)
        encabezado = f"{titulo} - {artista}"
        separador = "=" * 60
        bloque_nuevo = f"{encabezado}\n{separador}\n{letra}\n"

        with open(ARCHIVO_LETRA_ACTUAL, "w", encoding="utf-8") as f:
            f.write(bloque_nuevo.strip() + "\n")
        contenido_previo = ""
        if os.path.exists(ARCHIVO_LETRAS):
            with open(ARCHIVO_LETRAS, "r", encoding="utf-8") as f:
                contenido_previo = f.read().rstrip()

        if contenido_previo:
            contenido_final = f"{contenido_previo}\n\n{bloque_nuevo}"
        else:
            contenido_final = bloque_nuevo

        with open(ARCHIVO_LETRAS, "w", encoding="utf-8") as f:
            f.write(contenido_final.strip() + "\n")

        return titulo, artista, letra

    def leer_letra_actual(self):

        if not os.path.exists(ARCHIVO_LETRA_ACTUAL):
            return ""

        with open(ARCHIVO_LETRA_ACTUAL, "r", encoding="utf-8") as f:
            return f.read()

    def leer_letras_guardadas(self):

        if not os.path.exists(ARCHIVO_LETRAS):
            return ""

        with open(ARCHIVO_LETRAS, "r", encoding="utf-8") as f:
            return f.read()

    def abrir_archivo_letras(self):

        if not os.path.exists(ARCHIVO_LETRAS):
            open(ARCHIVO_LETRAS, "w", encoding="utf-8").close()

        if os.name == "nt":
            os.startfile(os.path.abspath(ARCHIVO_LETRAS))
        elif os.name == "posix":
            os.system(f'xdg-open "{ARCHIVO_LETRAS}"')

    def preparar_crossfade(self):

        dispositivo = self.obtener_dispositivo_activo()

        if dispositivo is None:
            raise RuntimeError("No hay dispositivo activo.")

        if not dispositivo.get('supports_volume', False):
            raise RuntimeError(
                "El dispositivo activo no permite controlar "
                "el volumen mediante la Web API."
            )

        volumen_original = dispositivo.get('volume_percent')

        if volumen_original is None:
            volumen_original = 50

        return dispositivo, volumen_original

    def fijar_volumen_dispositivo(self, dispositivo_id, volumen):

        self.sp.volume(volumen, device_id=dispositivo_id)

    def siguiente_cancion(self, dispositivo_id):

        self.sp.next_track(device_id=dispositivo_id)

    def anterior_cancion(self, dispositivo_id):
        self.sp.previous_track(device_id=dispositivo_id)

    def establecer_repeticion(self, estado):
        self.sp.repeat('track' if estado else 'off')

class App(tk.Tk):

    def __init__(self):

        super().__init__()
        try:
            self.tk.call('tk', 'scaling', self.winfo_fpixels('1i') / 72.0)
        except Exception:
            pass

        self.title("EmmSound Studio ")
        self.geometry("1180x740")
        self.minsize(1000, 640)
        self.configure(bg=NEGRO_FONDO)
        self._ruta_icono = None
        try:
            import sys
            import os

            if hasattr(sys, '_MEIPASS'):
                ruta_icono = os.path.join(sys._MEIPASS, "icono.ico")
            else:
                ruta_icono = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icono.ico")

            self.iconbitmap(ruta_icono)
            self._ruta_icono = ruta_icono
            
        except Exception:
            pass
        self._arrastrando_volumen = False
        self._reproduciendo = False
        self._actualizando_estado = False
        self._transicionando = False
        self._transicion_token = None
        self._indice_fila_actual = None
        self.repetir_activo = False
        self._modo_reproduccion = None
        self._indice_playlist_actual = None
        self._ultima_uri_polling = None
        self._ultimo_progreso_polling = 0
        self._ultima_duracion_polling = 0
        self._ultimo_reproduciendo_polling = False
        self._ultima_uri_finalizada = None
        self._artwork_cache = {}
        self._artwork_photo = None
        self.gestor = None
        self._credenciales = None
        self._cola = queue.Queue()

        self._configurar_estilos()

        self.protocol("WM_DELETE_WINDOW", self._salir)

        self.after(80, self._procesar_cola)

        credenciales_guardadas = cargar_configuracion()

        if credenciales_guardadas:
            self._credenciales = credenciales_guardadas
            self._construir_pantalla_carga()
            self.after(150, self._iniciar_conexion)
        else:
            self._construir_pantalla_credenciales()

    def _procesar_cola(self):
        try:
            while True:
                funcion, args = self._cola.get_nowait()
                try:
                    funcion(*args)
                except Exception:
                    import traceback
                    traceback.print_exc()
        except queue.Empty:
            pass
        finally:
            self.after(80, self._procesar_cola)

    def _ejecutar_en_hilo(self, funcion, on_exito=None, on_error=None, boton=None):
        if boton is not None:
            try:
                boton.configure(state="disabled")
            except tk.TclError:
                pass

        def trabajo():

            try:
                resultado = funcion()
            except Exception as e:
                self._cola.put((self._resolver_hilo, (on_error, boton, e)))
            else:
                self._cola.put((self._resolver_hilo, (on_exito, boton, resultado)))

        threading.Thread(target=trabajo, daemon=True).start()

    def _resolver_hilo(self, callback, boton, valor):

        if boton is not None:
            try:
                boton.configure(state="normal")
            except tk.TclError:
                pass

        if callback:
            callback(valor)

    def _construir_pantalla_credenciales(self, valores_previos=None):

        if hasattr(self, "marco_carga") and self.marco_carga.winfo_exists():
            self.marco_carga.destroy()

        if hasattr(self, "marco_credenciales") and self.marco_credenciales.winfo_exists():
            self.marco_credenciales.destroy()

        self.marco_credenciales = tk.Frame(self, bg=NEGRO_FONDO)
        self.marco_credenciales.pack(fill="both", expand=True)

        contenedor = tk.Frame(self.marco_credenciales, bg=NEGRO_FONDO)
        contenedor.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            contenedor, text="🎧 EMMSOUND STUDIO",
            bg=NEGRO_FONDO, fg=VERDE, font=F_TITULO
        ).pack(pady=(0, 6))

        tk.Label(
            contenedor, text="Configuración inicial de Spotify",
            bg=NEGRO_FONDO, fg=BLANCO, font=F_SUBTITULO
        ).pack(pady=(0, 14))

        tk.Label(
            contenedor,
            text=(
                "Ingresa el Client ID y el Client Secret de tu app de\n"
                "Spotify. Esto solo se pide una vez: queda guardado en\n"
                "este equipo para la próxima vez que abras el programa."
            ),
            bg=NEGRO_FONDO, fg=GRIS_TEXTO, font=F_TEXTO, justify="center"
        ).pack(pady=(0, 18))

        fila_id = tk.Frame(contenedor, bg=NEGRO_FONDO)
        fila_id.pack(pady=(0, 10), fill="x")
        tk.Label(
            fila_id, text="Client ID", bg=NEGRO_FONDO, fg=BLANCO,
            font=F_TEXTO_B, width=13, anchor="w"
        ).pack(side="left")
        entry_client_id = tk.Entry(
            fila_id, width=42, bg=NEGRO_PANEL_2, fg=BLANCO,
            insertbackground=BLANCO, relief="flat"
        )
        entry_client_id.pack(side="left", ipady=5, padx=(8, 0))

        fila_secret = tk.Frame(contenedor, bg=NEGRO_FONDO)
        fila_secret.pack(pady=(0, 4), fill="x")
        tk.Label(
            fila_secret, text="Client Secret", bg=NEGRO_FONDO, fg=BLANCO,
            font=F_TEXTO_B, width=13, anchor="w"
        ).pack(side="left")
        entry_client_secret = tk.Entry(
            fila_secret, width=42, show="•", bg=NEGRO_PANEL_2, fg=BLANCO,
            insertbackground=BLANCO, relief="flat"
        )
        entry_client_secret.pack(side="left", ipady=5, padx=(8, 0))

        if valores_previos:
            entry_client_id.insert(0, valores_previos.get("client_id", ""))
            entry_client_secret.insert(0, valores_previos.get("client_secret", ""))

        var_mostrar = tk.BooleanVar(value=False)

        def alternar_mostrar():
            entry_client_secret.configure(show="" if var_mostrar.get() else "•")

        tk.Checkbutton(
            contenedor, text="Mostrar secret", variable=var_mostrar,
            command=alternar_mostrar, bg=NEGRO_FONDO, fg=GRIS_TEXTO,
            selectcolor=NEGRO_PANEL_2, activebackground=NEGRO_FONDO,
            activeforeground=GRIS_TEXTO, font=F_PEQUENA, bd=0,
            highlightthickness=0
        ).pack(anchor="e", padx=(0, 6))

        lbl_link = tk.Label(
            contenedor,
            text="¿No tienes credenciales? Créalas en developer.spotify.com/dashboard",
            bg=NEGRO_FONDO, fg=VERDE, font=F_PEQUENA, cursor="hand2"
        )
        lbl_link.pack(pady=(10, 4))
        lbl_link.bind(
            "<Button-1>",
            lambda e: webbrowser.open("https://developer.spotify.com/dashboard")
        )

        tk.Label(
            contenedor,
            text=(
                "Importante: en la configuración de tu app de Spotify,\n"
                f"agrega esta Redirect URI exactamente así:\n{REDIRECT_URI}"
            ),
            bg=NEGRO_FONDO, fg=GRIS_TEXTO, font=F_PEQUENA, justify="center"
        ).pack(pady=(0, 16))

        lbl_error = tk.Label(
            contenedor, text="", bg=NEGRO_FONDO, fg=ROJO_SUAVE, font=F_TEXTO
        )
        lbl_error.pack(pady=(0, 8))

        def guardar():

            client_id = entry_client_id.get().strip()
            client_secret = entry_client_secret.get().strip()

            if not client_id or not client_secret:
                lbl_error.configure(text="Completa ambos campos.")
                return

            self._credenciales = {
                "client_id": client_id, "client_secret": client_secret
            }
            guardar_configuracion(client_id, client_secret)

            self.marco_credenciales.destroy()
            self._construir_pantalla_carga()
            self.after(150, self._iniciar_conexion)

        self._boton(
            contenedor, "Guardar y continuar", guardar, "primario"
        ).pack(pady=(4, 0))

    def _construir_pantalla_carga(self):

        self.marco_carga = tk.Frame(self, bg=NEGRO_FONDO)
        self.marco_carga.pack(fill="both", expand=True)

        tk.Label(
            self.marco_carga, text="🎧 EmmSound Studio ",
            bg=NEGRO_FONDO, fg=VERDE, font=F_TITULO
        ).pack(pady=(220, 12))

        tk.Label(
            self.marco_carga,
            text=(
                "Conectando con Spotify...\n"
                "Si se abre tu navegador, inicia sesión y autoriza la app."
            ),
            bg=NEGRO_FONDO, fg=GRIS_TEXTO, font=F_TEXTO, justify="center"
        ).pack()

        self.barra_carga = ttk.Progressbar(
            self.marco_carga, style="Verde.Horizontal.TProgressbar",
            mode="indeterminate", length=260
        )
        self.barra_carga.pack(pady=20)
        self.barra_carga.start(12)

    def _iniciar_conexion(self):

        self._ejecutar_en_hilo(
            self._crear_gestor,
            on_exito=self._conexion_exitosa,
            on_error=self._conexion_fallida
        )

    def _crear_gestor(self):

        return GestorMinisterioSonido(
            self._credenciales["client_id"],
            self._credenciales["client_secret"],
            REDIRECT_URI, SCOPE,
            cache_path=CACHE_PATH
        )

    def _conexion_exitosa(self, gestor):

        self.gestor = gestor
        self.barra_carga.stop()
        self.marco_carga.destroy()

        self._construir_interfaz()

        self.after(INTERVALO_ACTUALIZACION_MS, self._actualizar_estado_periodico)

    def _conexion_fallida(self, error):

        if hasattr(self, "marco_carga") and self.marco_carga.winfo_exists():
            self.marco_carga.destroy()

        reintentar = messagebox.askretrycancel(
            "Error de conexión",
            f"No se pudo conectar con Spotify:\n{error}\n\n"
            "¿Quieres revisar el Client ID / Client Secret e "
            "intentarlo de nuevo?"
        )

        if reintentar:
            self._construir_pantalla_credenciales(
                valores_previos=self._credenciales
            )
        else:
            self.destroy()

    def _configurar_estilos(self):

        estilo = ttk.Style(self)

        estilo.theme_use('clam')

        estilo.configure(
            "TNotebook",
            background=NEGRO_FONDO,
            borderwidth=0
        )

        estilo.configure(
            "TNotebook.Tab",
            background=NEGRO_PANEL,
            foreground=GRIS_TEXTO,
            padding=(18, 10),
            font=F_TEXTO_B,
            borderwidth=0
        )

        estilo.map(
            "TNotebook.Tab",
            background=[("selected", VERDE)],
            foreground=[("selected", NEGRO_FONDO)]
        )

        estilo.configure(
            "Horizontal.TScale",
            background=NEGRO_PANEL_2,
            troughcolor=NEGRO_PANEL,
            borderwidth=0
        )

        estilo.configure(
            "Verde.Horizontal.TProgressbar",
            troughcolor=NEGRO_PANEL,
            background=VERDE,
            borderwidth=0,
            thickness=8
        )

        estilo.configure(
            "Treeview",
            background=NEGRO_PANEL_2,
            fieldbackground=NEGRO_PANEL_2,
            foreground=BLANCO,
            rowheight=28,
            font=F_TEXTO,
            borderwidth=0
        )

        estilo.configure(
            "Treeview.Heading",
            background=NEGRO_PANEL,
            foreground=VERDE,
            font=F_TEXTO_B,
            borderwidth=0
        )

        estilo.map(
            "Treeview",
            background=[("selected", VERDE_OSCURO)],
            foreground=[("selected", BLANCO)]
        )

        estilo.configure(
            "Vertical.TScrollbar",
            background=NEGRO_PANEL,
            troughcolor=NEGRO_FONDO,
            arrowcolor=VERDE,
            borderwidth=0
        )

    def _boton(self, parent, texto, comando, tipo="primario"):

        paletas = {
            "primario": dict(bg=VERDE, fg=NEGRO_FONDO, hover=VERDE_HOVER),
            "secundario": dict(bg=NEGRO_PANEL_2, fg=BLANCO, hover=BORDE),
            "peligro": dict(bg=NEGRO_PANEL_2, fg=ROJO_SUAVE, hover=ROJO_HOVER),
        }

        paleta = paletas.get(tipo, paletas["primario"])

        btn = tk.Button(
            parent,
            text=texto,
            command=comando,
            bg=paleta["bg"],
            fg=paleta["fg"],
            activebackground=paleta["hover"],
            activeforeground=paleta["fg"],
            disabledforeground=GRIS_TEXTO,
            font=F_TEXTO_B,
            bd=0,
            relief="flat",
            padx=14,
            pady=8,
            cursor="hand2"
        )

        def entrar(e, b=btn, c=paleta["hover"]):
            if b['state'] != 'disabled':
                b.configure(bg=c)

        def salir(e, b=btn, c=paleta["bg"]):
            if b['state'] != 'disabled':
                b.configure(bg=c)

        btn.bind("<Enter>", entrar)
        btn.bind("<Leave>", salir)

        return btn

    def _crear_treeview(
        self, parent, columnas, encabezados, anchos, height=12, expandir=True
    ):

        contenedor = tk.Frame(parent, bg=NEGRO_FONDO)
        contenedor.pack(fill="both", expand=expandir)

        scrollbar = ttk.Scrollbar(contenedor, orient="vertical")

        tree = ttk.Treeview(
            contenedor,
            columns=columnas,
            show="headings",
            height=height,
            yscrollcommand=scrollbar.set
        )

        scrollbar.configure(command=tree.yview)

        for col, texto, ancho in zip(columnas, encabezados, anchos):
            tree.heading(col, text=texto)
            tree.column(col, width=ancho, anchor="w")

        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return tree

    def _construir_interfaz(self):

        self._construir_header()
        self._construir_now_playing()
        self._construir_notebook()
        self._construir_status_bar()
        self._refrescar_fila()
        self._refrescar_letra_actual()
        self._refrescar_letras()
        self._actualizar_now_playing(silencioso=True)
        self._animar_espectro()
        self._animar_dispositivos()

    def _construir_header(self):

        header = tk.Frame(self, bg=NEGRO_PANEL, padx=20, pady=14)
        header.pack(fill="x")

        tk.Label(
            header, text="🎧 EmmSound Studio",
            bg=NEGRO_PANEL, fg=VERDE, font=F_TITULO
        ).pack(side="left")

        self.lbl_estado_pill = tk.Label(
            header, text="● Sin datos",
            bg=NEGRO_PANEL, fg=GRIS_TEXTO, font=F_TEXTO_B
        )
        self.lbl_estado_pill.pack(side="right")
        self.canvas_espectro = tk.Canvas(
            header, width=36, height=20, bg=NEGRO_PANEL, 
            bd=0, highlightthickness=0
        )
        self.canvas_espectro.pack(side="right", padx=(0, 10))
        
        self.barras_espectro = []
        for i in range(4):
            barra = self.canvas_espectro.create_rectangle(
                i*9, 20, i*9+6, 20, fill=VERDE, outline=""
            )
            self.barras_espectro.append(barra)
    
    def _animar_espectro(self):
        import random
        
        if self._reproduciendo:
            for i, barra in enumerate(self.barras_espectro):
                alto = random.randint(4, 20)
                self.canvas_espectro.coords(barra, i*9, 20 - alto, i*9+6, 20)
        else:
            for i, barra in enumerate(self.barras_espectro):
                self.canvas_espectro.coords(barra, i*9, 18, i*9+6, 20)
        
        self.after(120, self._animar_espectro)

    def _texto_barra_actividad(self, activo):
        return (
            "".join(CARACTERES_BARRA_DISPOSITIVO[1:3])
            if activo and self._reproduciendo else BARRA_DISPOSITIVO_INACTIVO
        )

    def _animar_dispositivos(self):
        import random

        if not hasattr(self, "tree_dispositivos"):
            self.after(200, self._animar_dispositivos)
            return

        for i, dispositivo in enumerate(getattr(self, "_dispositivos_listados", [])):
            iid = str(i)

            if not self.tree_dispositivos.exists(iid):
                continue

            if dispositivo.get('is_active') and self._reproduciendo:
                barra = "".join(
                    random.choice(CARACTERES_BARRA_DISPOSITIVO) for _ in range(4)
                )
            else:
                barra = BARRA_DISPOSITIVO_INACTIVO

            try:
                self.tree_dispositivos.set(iid, "actividad", barra)
            except tk.TclError:
                pass

        self.after(200, self._animar_dispositivos)

    def _construir_now_playing(self):

        marco = tk.Frame(self, bg=NEGRO_PANEL_2, padx=20, pady=14)
        marco.pack(fill="x")

        self.lbl_portada = tk.Label(
            marco, text="♪", bg=NEGRO_PANEL_2, fg=VERDE,
            font=("Segoe UI", 26, "bold"), width=3, height=2
        )
        self.lbl_portada.pack(side="left", padx=(0, 14))

        info = tk.Frame(marco, bg=NEGRO_PANEL_2)
        info.pack(side="left", fill="x", expand=True)

        self.lbl_cancion = tk.Label(
            info, text="Sin reproducción",
            bg=NEGRO_PANEL_2, fg=BLANCO, font=F_SUBTITULO, anchor="w"
        )
        self.lbl_cancion.pack(fill="x")

        self.lbl_artista = tk.Label(
            info, text="—",
            bg=NEGRO_PANEL_2, fg=GRIS_TEXTO, font=F_TEXTO, anchor="w"
        )
        self.lbl_artista.pack(fill="x")

        barra_frame = tk.Frame(info, bg=NEGRO_PANEL_2)
        barra_frame.pack(fill="x", pady=(8, 0))

        self.lbl_tiempo_actual = tk.Label(
            barra_frame, text="00:00",
            bg=NEGRO_PANEL_2, fg=GRIS_TEXTO, font=F_PEQUENA
        )
        self.lbl_tiempo_actual.pack(side="left")

        self.progreso = ttk.Progressbar(
            barra_frame, style="Verde.Horizontal.TProgressbar",
            mode="determinate", maximum=100
        )
        self.progreso.pack(side="left", fill="x", expand=True, padx=8)

        self.lbl_tiempo_total = tk.Label(
            barra_frame, text="00:00",
            bg=NEGRO_PANEL_2, fg=GRIS_TEXTO, font=F_PEQUENA
        )
        self.lbl_tiempo_total.pack(side="left")
        self.lbl_dispositivo_actual = tk.Label(
            info, text="ᯤ Sin dispositivo activo",
            bg=NEGRO_PANEL_2, fg=GRIS_TEXTO, font=F_PEQUENA, anchor="w"
        )
        self.lbl_dispositivo_actual.pack(fill="x", pady=(4, 0))

        controles = tk.Frame(marco, bg=NEGRO_PANEL_2)
        controles.pack(side="right")

        self.btn_anterior = self._boton(
            controles, "◀◀", self._reproducir_anterior, "secundario"
        )
        self.btn_anterior.pack(side="left", padx=2)

        self.btn_play_pause = self._boton(
            controles, "▐▐  Pausar", self._alternar_reproduccion, "primario"
        )
        self.btn_play_pause.pack(side="left", padx=4)

        self.btn_siguiente = self._boton(
            controles, "▶▶", self._reproducir_siguiente, "secundario"
        )
        self.btn_siguiente.pack(side="left", padx=2)

        self.btn_bajar_volumen = self._boton(
            controles, "🔉", lambda: self._ajustar_volumen(-10), "secundario"
        )
        self.btn_bajar_volumen.pack(side="left", padx=(12, 2))

        self.var_volumen = tk.IntVar(value=50)

        self.slider_volumen = ttk.Scale(
            controles, from_=0, to=100, orient="horizontal",
            variable=self.var_volumen, length=130,
            command=self._on_slider_mover
        )
        self.slider_volumen.pack(side="left", padx=2)
        self.slider_volumen.bind("<ButtonRelease-1>", self._on_slider_soltar)

        self.lbl_volumen = tk.Label(
            controles, text="50%",
            bg=NEGRO_PANEL_2, fg=BLANCO, font=F_TEXTO, width=4
        )
        self.lbl_volumen.pack(side="left", padx=2)

        self.btn_subir_volumen = self._boton(
            controles, "🔊", lambda: self._ajustar_volumen(10), "secundario"
        )
        self.btn_subir_volumen.pack(side="left", padx=(2, 10))

        self.btn_repetir = self._boton(
            controles, "⮎⮌", self._alternar_repetir, "secundario"
        )
        self.btn_repetir.pack(side="left", padx=4)

        self._boton(
            controles, "↻", self._actualizar_manual, "secundario"
        ).pack(side="left", padx=4)

        self._boton(
            controles, "➜]", self._salir, "peligro"
        ).pack(side="left", padx=(4, 0))

    def _construir_notebook(self):

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=16, pady=12)
        self.tab_buscar = tk.Frame(self.notebook, bg=NEGRO_FONDO, padx=4, pady=4)
        self.tab_fila = tk.Frame(self.notebook, bg=NEGRO_FONDO, padx=4, pady=4)
        self.tab_playlists = tk.Frame(self.notebook, bg=NEGRO_FONDO, padx=4, pady=4)
        self.tab_letras = tk.Frame(self.notebook, bg=NEGRO_FONDO, padx=4, pady=4)
        self.tab_dispositivos = tk.Frame(self.notebook, bg=NEGRO_FONDO, padx=4, pady=4)
        self.notebook.add(self.tab_buscar, text="🔍︎ Buscar")
        self.notebook.add(self.tab_fila, text="☰ Fila")
        self.notebook.add(self.tab_playlists, text="🖭 Playlists")
        self.notebook.add(self.tab_letras, text="📚 Letras")
        self.notebook.add(self.tab_dispositivos, text="🎧 Dispositivos")
        self._construir_tab_buscar()
        self._construir_tab_fila()
        self._construir_tab_playlists()
        self._construir_tab_letras()
        self._construir_tab_dispositivos()

    def _construir_tab_buscar(self):

        marco = self.tab_buscar

        fila_busqueda = tk.Frame(marco, bg=NEGRO_FONDO)
        fila_busqueda.pack(fill="x", pady=(4, 10))

        self.entry_busqueda = tk.Entry(
            fila_busqueda, bg=NEGRO_PANEL_2, fg=BLANCO,
            insertbackground=BLANCO, font=F_TEXTO, relief="flat"
        )
        self.entry_busqueda.pack(
            side="left", fill="x", expand=True, ipady=6, padx=(0, 8)
        )
        self.entry_busqueda.bind("<Return>", lambda e: self._buscar())

        self.btn_buscar = self._boton(
            fila_busqueda, "Buscar", self._buscar, "primario"
        )
        self.btn_buscar.pack(side="left")

        self.tree_busqueda = self._crear_treeview(
            marco,
            ("num", "titulo", "artista", "duracion"),
            ("#", "Título", "Artista", "Duración"),
            (40, 320, 220, 90),
            height=10, expandir=False
        )
        self.tree_busqueda.bind(
            "<<TreeviewSelect>>",
            lambda e: reiniciar_segundo_inicial(self.entry_segundo_busqueda)
        )

        pie = tk.Frame(marco, bg=NEGRO_FONDO)
        pie.pack(fill="x", pady=(10, 0))

        tk.Label(
            pie, text="Segundo inicial:",
            bg=NEGRO_FONDO, fg=GRIS_TEXTO, font=F_TEXTO
        ).pack(side="left")

        self.entry_segundo_busqueda = tk.Entry(
            pie, width=6, bg=NEGRO_PANEL_2, fg=BLANCO,
            insertbackground=BLANCO, relief="flat"
        )
        self.entry_segundo_busqueda.insert(0, "0")
        self.entry_segundo_busqueda.pack(side="left", padx=(6, 16), ipady=4)

        self.btn_reproducir_busqueda = self._boton(
            pie, "▶ Reproducir ahora",
            self._reproducir_seleccion_busqueda, "primario"
        )
        self.btn_reproducir_busqueda.pack(side="left", padx=4)

        self._boton(
            pie, "➕ Agregar a la fila",
            self._agregar_seleccion_busqueda_a_fila, "secundario"
        ).pack(side="left", padx=4)

        self.btn_agregar_playlist_busqueda = self._boton(
            pie, "📂 Agregar a playlist",
            self._agregar_seleccion_busqueda_a_playlist, "secundario"
        )
        self.btn_agregar_playlist_busqueda.pack(side="left", padx=4)

    def _construir_tab_fila(self):

        marco = self.tab_fila

        self.tree_fila = self._crear_treeview(
            marco,
            ("num", "titulo", "artista", "inicio"),
            ("#", "Título", "Artista", "Inicio"),
            (40, 340, 240, 90),
            height=14, expandir = False
        )
        self.tree_fila.bind("<Double-1>", lambda e: self._reproducir_seleccion_fila())
        self.tree_fila.bind("<<TreeviewSelect>>", self._fila_seleccionada)

        pie = tk.Frame(marco, bg=NEGRO_FONDO)
        pie.pack(fill="x", pady=(10, 0))

        self.btn_reproducir_fila = self._boton(
            pie, "▶ Reproducir seleccionada",
            self._reproducir_seleccion_fila, "primario"
        )
        self.btn_reproducir_fila.pack(side="left")

        self._boton(
            pie, "🗑 Eliminar seleccionada",
            self._eliminar_de_fila, "peligro"
        ).pack(side="left", padx=8)

        self._boton(
            pie, "↻ Actualizar", self._refrescar_fila, "secundario"
        ).pack(side="left")

    def _construir_tab_playlists(self):

        marco = self.tab_playlists

        superior = tk.Frame(marco, bg=NEGRO_FONDO)
        superior.pack(fill="x", pady=(4, 8))

        self.btn_cargar_biblioteca = self._boton(
            superior, "📂 Cargar mi biblioteca",
            self._cargar_biblioteca, "primario"
        )
        self.btn_cargar_biblioteca.pack(side="left")

        self.btn_cargar_playlist = self._boton(
            superior, "✔ Cargar playlist seleccionada",
            self._cargar_playlist_seleccionada, "secundario"
        )
        self.btn_cargar_playlist.pack(side="left", padx=8)

        self.tree_biblioteca = self._crear_treeview(
            marco,
            ("nombre", "canciones", "tuya"),
            ("Tu playlist", "Canciones", "Tuya"),
            (400, 100, 70),
            height=6
        )

        tk.Frame(marco, bg=BORDE, height=1).pack(fill="x", pady=10)

        self.lbl_playlist_actual = tk.Label(
            marco, text="Ninguna playlist cargada",
            bg=NEGRO_FONDO, fg=VERDE, font=F_SUBTITULO, anchor="w"
        )
        self.lbl_playlist_actual.pack(fill="x")

        self.tree_playlist = self._crear_treeview(
            marco,
            ("num", "titulo", "artista", "duracion"),
            ("#", "Título", "Artista", "Duración"),
            (40, 320, 220, 90),
            height=10
        )
        self.tree_playlist.bind(
            "<<TreeviewSelect>>",
            lambda e: reiniciar_segundo_inicial(self.entry_segundo_playlist)
        )

        pie = tk.Frame(marco, bg=NEGRO_FONDO)
        pie.pack(fill="x", pady=(10, 0))

        tk.Label(
            pie, text="Segundo inicial:",
            bg=NEGRO_FONDO, fg=GRIS_TEXTO, font=F_TEXTO
        ).pack(side="left")

        self.entry_segundo_playlist = tk.Entry(
            pie, width=6, bg=NEGRO_PANEL_2, fg=BLANCO,
            insertbackground=BLANCO, relief="flat"
        )
        self.entry_segundo_playlist.insert(0, "0")
        self.entry_segundo_playlist.pack(side="left", padx=(6, 16), ipady=4)

        self._boton(
            pie, "▶ Reproducir seleccionada",
            self._reproducir_seleccion_playlist, "primario"
        ).pack(side="left", padx=4)

        self._boton(
            pie, "➕ Agregar a la fila",
            self._agregar_seleccion_playlist_a_fila, "secundario"
        ).pack(side="left", padx=4)

    def _construir_tab_letras(self):

        marco = self.tab_letras
        marco_actual = tk.Frame(marco, bg=NEGRO_PANEL_2)
        marco_actual.pack(fill="x", pady=(0, 10))

        barra_actual = tk.Frame(marco_actual, bg=NEGRO_PANEL_2)
        barra_actual.pack(fill="x", padx=10, pady=(10, 6))

        tk.Label(
            barra_actual, text="🎤︎︎ Letra actual",
            bg=NEGRO_PANEL_2, fg=BLANCO, font=F_TEXTO_B
        ).pack(side="left")

        self.btn_importar_letra = self._boton(
            barra_actual, "Ver letra",
            self._importar_letra, "primario"
        )
        self.btn_importar_letra.pack(side="right")

        self.texto_letra_actual = scrolledtext.ScrolledText(
            marco_actual, height=10, bg=NEGRO_FONDO, fg=BLANCO,
            insertbackground=BLANCO, font=F_MONO,
            relief="flat", wrap="word", padx=12, pady=12
        )
        self.texto_letra_actual.pack(fill="x", padx=10, pady=(0, 10))
        self.texto_letra_actual.configure(state="disabled")

        marco_guardadas = tk.Frame(marco, bg=NEGRO_PANEL_2)
        marco_guardadas.pack(fill="both", expand=True)

        barra_guardadas = tk.Frame(marco_guardadas, bg=NEGRO_PANEL_2)
        barra_guardadas.pack(fill="x", padx=10, pady=(10, 6))

        tk.Label(
            barra_guardadas, text="⎙ Letras guardadas (histórico)",
            bg=NEGRO_PANEL_2, fg=BLANCO, font=F_TEXTO_B
        ).pack(side="left")

        self._boton(
            barra_guardadas, "💾 Abrir archivo", self._abrir_letras, "secundario"
        ).pack(side="right")

        self._boton(
            barra_guardadas, "↻ Actualizar", self._refrescar_letras, "secundario"
        ).pack(side="right", padx=(4, 4))

        self.texto_letras = scrolledtext.ScrolledText(
            marco_guardadas, bg=NEGRO_FONDO, fg=BLANCO,
            insertbackground=BLANCO, font=F_MONO,
            relief="flat", wrap="word", padx=12, pady=12
        )
        self.texto_letras.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.texto_letras.configure(state="disabled")

    def _construir_tab_dispositivos(self):

        marco = self.tab_dispositivos

        barra = tk.Frame(marco, bg=NEGRO_FONDO)
        barra.pack(fill="x", pady=(4, 10))

        self.btn_refrescar_dispositivos = self._boton(
            barra, "↻ Actualizar dispositivos",
            self._refrescar_dispositivos, "primario"
        )
        self.btn_refrescar_dispositivos.pack(side="left")

        self.btn_reproducir_aqui = self._boton(
            barra, "▶ Reproducir en este dispositivo",
            self._reproducir_en_dispositivo_seleccionado, "secundario"
        )
        self.btn_reproducir_aqui.pack(side="left", padx=8)

        self.tree_dispositivos = self._crear_treeview(
            marco,
            ("nombre", "tipo", "activo", "actividad", "volumen", "control"),
            ("Dispositivo", "Tipo", "Activo", "Actividad", "Volumen", "Control vol."),
            (230, 130, 70, 110, 90, 110),
            height=10, expandir=False
        )
        self.tree_dispositivos.bind(
            "<Double-1>", lambda e: self._reproducir_en_dispositivo_seleccionado()
        )

        self._dispositivos_listados = []

    def _construir_status_bar(self):

        self.status_bar = tk.Label(
            self, text="Listo.",
            bg=NEGRO_PANEL, fg=GRIS_TEXTO, font=F_TEXTO,
            anchor="w", padx=16, pady=6
        )
        self.status_bar.pack(fill="x", side="bottom")

    def _status(self, mensaje, tipo="info"):

        colores = {
            "info": GRIS_TEXTO, "ok": VERDE, "error": ROJO_SUAVE
        }

        self.status_bar.configure(
            text=mensaje, fg=colores.get(tipo, GRIS_TEXTO)
        )

    def _manejar_error(self, e, contexto=""):

        self._status(f"{contexto} {e}".strip(), "error")

    @staticmethod
    def _fmt_tiempo(segundos):

        return f"{segundos // 60:02d}:{segundos % 60:02d}"

    def _obtener_segundo(self, entry):

        texto = entry.get().strip()

        try:
            return max(0.0, float(texto)) if texto else 0.0
        except ValueError:
            return 0.0

    def _actualizar_estado_periodico(self):

        if self._actualizando_estado:
            self.after(INTERVALO_ACTUALIZACION_MS, self._actualizar_estado_periodico)
            return

        self._actualizando_estado = True

        def terminar():
            self._actualizando_estado = False
            self.after(INTERVALO_ACTUALIZACION_MS, self._actualizar_estado_periodico)

        self._actualizar_now_playing(silencioso=True, callback_final=terminar)

    def _actualizar_manual(self):

        self._actualizar_now_playing(silencioso=False)

    def _actualizar_now_playing(self, silencioso=False, callback_final=None):

        def exito(estado):
            self._aplicar_estado(estado)
            if not silencioso:
                self._status("Actualizado.", "ok")
            if callback_final:
                callback_final()

        def error(e):
            if not silencioso:
                self._manejar_error(e, "No se pudo actualizar:")
            if callback_final:
                callback_final()

        self._ejecutar_en_hilo(
            self.gestor.obtener_estado_actual,
            on_exito=exito,
            on_error=error
        )

    def _aplicar_estado(self, estado):

        self._verificar_fin_de_cancion(estado)

        if not estado or not estado.get('item'):
            self.lbl_cancion.configure(text="Sin reproducción")
            self.lbl_artista.configure(text="—")
            self.progreso['value'] = 0
            self.lbl_tiempo_actual.configure(text="00:00")
            self.lbl_tiempo_total.configure(text="00:00")
            self.lbl_estado_pill.configure(text="● Sin datos", fg=GRIS_TEXTO)
            self.btn_play_pause.configure(text="▶ Reanudar")
            self._reproduciendo = False
            self._mostrar_portada(None)

            dispositivo = (estado or {}).get('device')
            if dispositivo and dispositivo.get('name'):
                self.lbl_dispositivo_actual.configure(
                    text=f"ᯤ Dispositivo activo: {dispositivo.get('name')}"
                )
            else:
                self.lbl_dispositivo_actual.configure(
                    text="ᯤ Sin dispositivo activo"
                )
            self._actualizar_disponibilidad_volumen(dispositivo)
            self._ultimo_progreso_polling = 0
            self._ultima_duracion_polling = 0
            self._ultimo_reproduciendo_polling = False
            return

        track = estado['item']
        uri_actual = track.get('uri')
        nombre_cancion = track.get('name', '—')
        if track.get('explicit'):
            nombre_cancion += "  🅴"
        self.lbl_cancion.configure(text=nombre_cancion)
        artista = track['artists'][0]['name'] if track.get('artists') else '—'
        self.lbl_artista.configure(text=artista)

        imagenes = (track.get('album') or {}).get('images', []) or []
        artwork_url = imagenes[0].get('url') if imagenes else None
        self._mostrar_portada(artwork_url)

        progreso_ms = estado.get('progress_ms', 0) or 0
        duracion_ms = track.get('duration_ms', 0) or 1
        self.progreso['maximum'] = duracion_ms
        self.progreso['value'] = progreso_ms
        self.lbl_tiempo_actual.configure(text=self._fmt_tiempo(progreso_ms // 1000))
        self.lbl_tiempo_total.configure(text=self._fmt_tiempo(duracion_ms // 1000))

        reproduciendo = bool(estado.get('is_playing'))
        self._reproduciendo = reproduciendo
        if reproduciendo:
            self.lbl_estado_pill.configure(text="⏺ TRANSMITIENDO", fg=VERDE)
            self.btn_play_pause.configure(text="❚❚  Pausar")
        else:
            self.lbl_estado_pill.configure(text="⏺ EN PAUSA", fg=GRIS_TEXTO)
            self.btn_play_pause.configure(text="▶  Reanudar")

        dispositivo = estado.get('device')
        if dispositivo and dispositivo.get('name'):
            self.lbl_dispositivo_actual.configure(
                text=f"ᯤ Sonando en: {dispositivo.get('name')}"
            )
        else:
            self.lbl_dispositivo_actual.configure(
                text="ᯤ Sin dispositivo activo"
            )

        for i, fila_track in enumerate(self.gestor.fila_reproduccion):
            if fila_track.uri == uri_actual:
                self._indice_fila_actual = i
                break

        dispositivo = estado.get('device')
        if dispositivo and dispositivo.get('volume_percent') is not None and not self._arrastrando_volumen:
            self.var_volumen.set(dispositivo.get('volume_percent'))
            self.lbl_volumen.configure(text=f"{dispositivo.get('volume_percent')}%")

        self._actualizar_disponibilidad_volumen(dispositivo)

        self.btn_repetir.configure(
            text="⮎⮌: ON" if self.repetir_activo else "⮎⮌",
            bg=VERDE if self.repetir_activo else NEGRO_PANEL_2,
            fg=NEGRO_FONDO if self.repetir_activo else BLANCO
        )
        self._ultima_uri_polling = uri_actual
        self._ultimo_progreso_polling = progreso_ms
        self._ultima_duracion_polling = duracion_ms
        self._ultimo_reproduciendo_polling = reproduciendo

    def _mostrar_portada(self, url):
        if Image is None or ImageTk is None:
            self.lbl_portada.configure(text="♪", image="", width=3, height=2)
            return
        if not url:
            self.lbl_portada.configure(image="", text="♪", width=3, height=2)
            self._artwork_photo = None
            return
        if url in self._artwork_cache:
            self._artwork_photo = self._artwork_cache[url]
            self.lbl_portada.configure(
                image=self._artwork_photo, text="",
                width=TAMANO_PORTADA, height=TAMANO_PORTADA
            )
            return

        def descargar():
            try:
                with urllib.request.urlopen(url, timeout=8) as respuesta:
                    datos = respuesta.read()
                imagen = Image.open(io.BytesIO(datos)).convert("RGB")
                imagen = imagen.resize(
                    (TAMANO_PORTADA, TAMANO_PORTADA),
                    Image.Resampling.LANCZOS
                )
                return ImageTk.PhotoImage(imagen)
            except Exception:
                return None

        def exito(photo):
            if photo:
                self._artwork_cache[url] = photo
                self._artwork_photo = photo
                self.lbl_portada.configure(
                    image=photo, text="",
                    width=TAMANO_PORTADA, height=TAMANO_PORTADA
                )
            else:
                self.lbl_portada.configure(image="", text="♪", width=3, height=2)

        self._ejecutar_en_hilo(descargar, on_exito=exito)

    def _alternar_reproduccion(self):

        self._ejecutar_en_hilo(
            self.gestor.alternar_reproduccion,
            on_exito=self._tras_alternar_reproduccion,
            on_error=lambda e: self._manejar_error(
                e, "No se pudo cambiar la reproducción:"
            ),
            boton=self.btn_play_pause
        )

    def _tras_alternar_reproduccion(self, _resultado):

        self._status("Reproducción actualizada.", "ok")
        self._actualizar_now_playing(silencioso=True)

    def _actualizar_disponibilidad_volumen(self, dispositivo):

        soporta_volumen = bool(dispositivo and dispositivo.get('supports_volume'))
        estado_widget = "normal" if soporta_volumen else "disabled"

        self.btn_bajar_volumen.configure(state=estado_widget)
        self.btn_subir_volumen.configure(state=estado_widget)
        self.slider_volumen.configure(state=estado_widget)

    def _ajustar_volumen(self, cantidad):

        self._ejecutar_en_hilo(
            lambda: self.gestor.cambiar_volumen(cantidad),
            on_exito=self._volumen_actualizado,
            on_error=lambda e: self._manejar_error(e, "Volumen:")
        )

    def _volumen_actualizado(self, nuevo):

        self.var_volumen.set(nuevo)
        self.lbl_volumen.configure(text=f"{nuevo}%")
        self._status(f"Volumen: {nuevo}%", "ok")

    def _on_slider_mover(self, valor):

        self._arrastrando_volumen = True
        self.lbl_volumen.configure(text=f"{int(float(valor))}%")

    def _on_slider_soltar(self, evento):

        self._arrastrando_volumen = False
        valor = int(self.var_volumen.get())

        self._ejecutar_en_hilo(
            lambda: self.gestor.establecer_volumen(valor),
            on_exito=lambda nuevo: self._status(f"Volumen: {nuevo}%", "ok"),
            on_error=lambda e: self._manejar_error(e, "Volumen:")
        )

    def _transicionar_a_track(self, track, segundo=0, boton=None, indice_fila=None):
        if self._transicionando:
            self._status("Ya hay una transición en curso.", "info")
            return
        self._transicionando = True
        if indice_fila is not None:
            self._indice_fila_actual = indice_fila

        self._transicion_token = object()
        token_actual = self._transicion_token

        def watchdog():
            if self._transicionando and self._transicion_token is token_actual:
                self._transicionando = False
                self._status(
                    "La transición anterior tardó demasiado y se reinició.",
                    "error"
                )

        self.after(8000, watchdog)

        def preparar():
            estado = self.gestor.obtener_estado_actual()
            dispositivo = self.gestor.obtener_dispositivo_activo()
            if dispositivo is None:
                raise RuntimeError("No hay dispositivo activo.")
            if not dispositivo.get('supports_volume', False):
                return estado, dispositivo, None
            volumen = dispositivo.get('volume_percent')
            return estado, dispositivo, 50 if volumen is None else volumen

        def terminado(error=None):
            self._transicionando = False
            if error:
                self._manejar_error(error, "Reproducción:")
                return
            self._status(f"Reproduciendo: {track.name} - {track.artist}", "ok")
            self._actualizar_now_playing(silencioso=True)
            if self.repetir_activo:
                self._ejecutar_en_hilo(
                    lambda: self.gestor.establecer_repeticion(True),
                    on_error=lambda e: self._manejar_error(e, "Repetir:")
                )

        def preparado(resultado):
            try:
                estado, dispositivo, volumen_original = resultado

                if volumen_original is None:
                    self._ejecutar_en_hilo(
                        lambda: self.gestor.reproducir_cancion(track, segundo),
                        on_exito=lambda _: terminado(),
                        on_error=terminado
                    )
                    return

                pasos = PASOS_CROSSFADE
                intervalo = max(80, int((DURACION_CROSSFADE / pasos) * 1000))
                device_id = dispositivo.get('id')
                volumen = int(volumen_original)
                hay_anterior = bool(estado and estado.get('item'))

                def fade_in(i):
                    if i > pasos:
                        terminado()
                        return
                    valor = int(volumen * i / pasos)
                    def continuar(_):
                        self.after(intervalo, lambda: fade_in(i + 1))
                    self._ejecutar_en_hilo(
                        lambda v=valor: self.gestor.fijar_volumen_dispositivo(device_id, v),
                        on_exito=continuar, on_error=continuar
                    )

                def iniciar_nueva():
                    self._ejecutar_en_hilo(
                        lambda: self.gestor.reproducir_cancion(track, segundo),
                        on_exito=lambda _: fade_in(0),
                        on_error=terminado
                    )

                if not hay_anterior:
                    def silencio_listo(_):
                        iniciar_nueva()

                    self._ejecutar_en_hilo(
                        lambda: self.gestor.fijar_volumen_dispositivo(device_id, 0),
                        on_exito=silencio_listo,
                        on_error=lambda _e: iniciar_nueva()
                    )
                    return

                def fade_out(i):
                    if i < 0:
                        iniciar_nueva()
                        return
                    valor = int(volumen * i / pasos)
                    def continuar(_):
                        self.after(intervalo, lambda: fade_out(i - 1))
                    self._ejecutar_en_hilo(
                        lambda v=valor: self.gestor.fijar_volumen_dispositivo(device_id, v),
                        on_exito=continuar, on_error=continuar
                    )
                fade_out(pasos)

            except Exception as e:
                terminado(e)

        self._ejecutar_en_hilo(preparar, on_exito=preparado, on_error=terminado, boton=boton)

    def _obtener_indice_fila_actual(self):
        if self._indice_fila_actual is not None and 0 <= self._indice_fila_actual < len(self.gestor.fila_reproduccion):
            return self._indice_fila_actual
        try:
            estado = self.gestor.obtener_estado_actual()
        except Exception:
            return None
        uri = ((estado or {}).get('item') or {}).get('uri')
        for i, track in enumerate(self.gestor.fila_reproduccion):
            if track.uri == uri:
                return i
        return None

    def _reproducir_siguiente(self):
        self._navegar_manual(+1)

    def _reproducir_anterior(self):
        self._navegar_manual(-1)

    def _navegar_manual(self, direccion):
        if self._modo_reproduccion == 'playlist' and self.gestor.playlist_actual:
            self._navegar_en_playlist(direccion)
        elif self._modo_reproduccion == 'fila' or self.gestor.fila_reproduccion:
            self._navegar_en_fila(direccion)
        else:
            self._status(
                "No hay una fila o playlist activa para avanzar/retroceder.",
                "error"
            )

    def _navegar_en_fila(self, direccion):

        fila = self.gestor.fila_reproduccion

        if not fila:
            self._status("La fila está vacía.", "error")
            return

        indice = self._obtener_indice_fila_actual()
        indice = 0 if indice is None else indice + direccion
        indice = max(0, min(indice, len(fila) - 1))

        track = fila[indice]
        self._indice_fila_actual = indice
        self._modo_reproduccion = 'fila'
        self._transicionar_a_track(track, track.start_second)
        self.tree_fila.selection_set(str(indice + 1))
        self.tree_fila.see(str(indice + 1))

    def _navegar_en_playlist(self, direccion):

        playlist = self.gestor.playlist_actual

        if not playlist:
            self._status("No hay una playlist cargada.", "error")
            return

        indice = self._indice_playlist_actual
        indice = 0 if indice is None else indice + direccion
        indice = max(0, min(indice, len(playlist) - 1))

        track = playlist[indice]
        self._indice_playlist_actual = indice
        self._modo_reproduccion = 'playlist'
        self._transicionar_a_track(track, track.start_second)
        self.tree_playlist.selection_set(str(track.index))
        self.tree_playlist.see(str(track.index))

    def _alternar_repetir(self):
        nuevo_estado = not self.repetir_activo

        def exito(_):
            self.repetir_activo = nuevo_estado
            self.btn_repetir.configure(
                text="⮎⮌: ON" if nuevo_estado else "⮎⮌",
                bg=VERDE if nuevo_estado else NEGRO_PANEL_2,
                fg=NEGRO_FONDO if nuevo_estado else BLANCO
            )
            self._refrescar_fila()
            self._status(
                "Repetición activada: la fila usa la misma canción."
                if nuevo_estado else "Repetición desactivada.", "ok"
            )

        self._ejecutar_en_hilo(
            lambda: self.gestor.establecer_repeticion(nuevo_estado),
            on_exito=exito,
            on_error=lambda e: self._manejar_error(e, "Repetir:")
        )
    def _verificar_fin_de_cancion(self, estado):
        if self._transicionando or self._modo_reproduccion is None:
            return

        if not self._ultimo_reproduciendo_polling:
            return

        uri_anterior = self._ultima_uri_polling
        progreso_anterior = self._ultimo_progreso_polling
        duracion_anterior = self._ultima_duracion_polling

        if not uri_anterior or duracion_anterior <= 0:
            return

        if uri_anterior == self._ultima_uri_finalizada:
            return

        item_nuevo = (estado or {}).get('item') or {}
        uri_nueva = item_nuevo.get('uri')
        reproduciendo_nueva = bool((estado or {}).get('is_playing'))

        if uri_nueva == uri_anterior and reproduciendo_nueva:
            return

        if uri_nueva is None:
            llego_al_final = True
        else:
            llego_al_final = (
                progreso_anterior >= duracion_anterior - MARGEN_FIN_CANCION_MS
            )

        if not llego_al_final:
            return

        self._ultima_uri_finalizada = uri_anterior
        self._avanzar_automaticamente(uri_anterior)

    def _hay_pendiente_en_fila(self):
        fila = self.gestor.fila_reproduccion

        if not fila:
            return False

        indice_actual = self._obtener_indice_fila_actual()

        if indice_actual is None:

            return True

        return (indice_actual + 1) < len(fila)

    def _avanzar_automaticamente(self, uri_terminada):

        if self._modo_reproduccion == 'fila' or self._hay_pendiente_en_fila():
            self._autoplay_siguiente_en_fila()
            return

        if self._modo_reproduccion == 'playlist':
            self._autoplay_siguiente_en_playlist()
        elif self._modo_reproduccion == 'busqueda':
            self._autoplay_recomendaciones(uri_terminada)

    def _autoplay_siguiente_en_fila(self):
        fila = self.gestor.fila_reproduccion

        if not fila:
            self._modo_reproduccion = None
            return

        indice_actual = self._obtener_indice_fila_actual()
        siguiente = 0 if indice_actual is None else indice_actual + 1

        if siguiente >= len(fila):
            self._modo_reproduccion = None
            self._status("Fin de la fila de reproducción.", "info")
            return

        track = fila[siguiente]
        self._indice_fila_actual = siguiente
        self._modo_reproduccion = 'fila'
        self._transicionar_a_track(track, track.start_second)

        self._refrescar_fila()
        self.tree_fila.selection_set(str(siguiente + 1))
        self.tree_fila.see(str(siguiente + 1))

    def _autoplay_siguiente_en_playlist(self):
        playlist = self.gestor.playlist_actual

        if self._indice_playlist_actual is None:
            self._modo_reproduccion = None
            return

        siguiente = self._indice_playlist_actual + 1

        if siguiente >= len(playlist):
            self._modo_reproduccion = None
            self._status(
                f"Fin de la playlist '{self.gestor.nombre_playlist}'.", "info"
            )
            return

        track = playlist[siguiente]
        self._indice_playlist_actual = siguiente
        self._transicionar_a_track(track, track.start_second)

        self.tree_playlist.selection_set(str(track.index))
        self.tree_playlist.see(str(track.index))

    def _autoplay_recomendaciones(self, uri_terminada):
        self._status("Autoplay: buscando canciones similares...", "info")

        self._ejecutar_en_hilo(
            lambda: self.gestor.obtener_recomendaciones(uri_terminada),
            on_exito=self._recomendaciones_listas,
            on_error=lambda e: self._manejar_error(e, "Autoplay:")
        )

    def _recomendaciones_listas(self, canciones):

        if not canciones:
            self._modo_reproduccion = None
            self._status(
                "Autoplay: no se encontraron canciones similares.", "info"
            )
            return

        indice_inicio = len(self.gestor.fila_reproduccion)

        for track in canciones:
            self.gestor.agregar_a_fila(track, 0)

        self._refrescar_fila()

        primero = self.gestor.fila_reproduccion[indice_inicio]
        self._indice_fila_actual = indice_inicio
        self._modo_reproduccion = 'fila'
        self._transicionar_a_track(primero, primero.start_second)

        self._status(
            f"Autoplay: {len(canciones)} canciones similares agregadas "
            "a la fila.", "ok"
        )

    def _fila_seleccionada(self, _event=None):
        if self.tree_fila.selection():
            self.btn_reproducir_fila.configure(state="normal")

    def _reproducir_seleccion_fila(self):
        sel = self.tree_fila.selection()
        if not sel:
            self._status("Selecciona una canción de la fila.", "error")
            return
        indice = int(sel[0]) - 1
        if not (0 <= indice < len(self.gestor.fila_reproduccion)):
            self._status("La selección de la fila ya no es válida.", "error")
            return
        track = self.gestor.fila_reproduccion[indice]
        self._indice_fila_actual = indice
        self._modo_reproduccion = 'fila'
        self._transicionar_a_track(track, track.start_second, self.btn_reproducir_fila)


    def _buscar(self):

        query = self.entry_busqueda.get().strip()

        if not query:
            return

        self._status("Buscando...", "info")

        self._ejecutar_en_hilo(
            lambda: self.gestor.buscar_canciones(query),
            on_exito=self._mostrar_resultados_busqueda,
            on_error=lambda e: self._manejar_error(e, "Búsqueda:"),
            boton=self.btn_buscar
        )

    def _mostrar_resultados_busqueda(self, canciones):

        for item in self.tree_busqueda.get_children():
            self.tree_busqueda.delete(item)

        for track in canciones:
            self.tree_busqueda.insert(
                "", "end", iid=str(track.index),
                values=(
                    track.index, track.nombre_mostrado,
                    track.artist, track.duracion_texto
                )
            )

        self._status(f"{len(canciones)} resultados.", "ok")

    def _reproducir_seleccion_busqueda(self):
        sel = self.tree_busqueda.selection()
        if not sel:
            self._status("Selecciona una canción primero.", "error")
            return
        indice = int(sel[0]) - 1
        track = self.gestor.lista_canciones[indice]
        segundo = self._obtener_segundo(self.entry_segundo_busqueda)
        reiniciar_segundo_inicial(self.entry_segundo_busqueda)
        self._modo_reproduccion = 'busqueda'
        self._transicionar_a_track(track, segundo, self.btn_reproducir_busqueda)

    def _tras_reproducir(self, track):

        self._status(f"Reproduciendo: {track.name} - {track.artist}", "ok")
        self._actualizar_now_playing(silencioso=True)

    def _agregar_seleccion_busqueda_a_fila(self):

        sel = self.tree_busqueda.selection()

        if not sel:
            self._status("Selecciona una canción primero.", "error")
            return

        indice = int(sel[0]) - 1
        track = self.gestor.lista_canciones[indice]
        segundo = self._obtener_segundo(self.entry_segundo_busqueda)
        reiniciar_segundo_inicial(self.entry_segundo_busqueda)

        nuevo = self.gestor.agregar_a_fila(track, segundo)

        self._status(f"Agregada a la fila: {nuevo.name}", "ok")
        self._refrescar_fila()

    def _agregar_seleccion_busqueda_a_playlist(self):

        sel = self.tree_busqueda.selection()

        if not sel:
            self._status("Selecciona una canción primero.", "error")
            return

        indice = int(sel[0]) - 1
        track = self.gestor.lista_canciones[indice]

        if self.gestor.biblioteca_playlists:
            self._abrir_ventana_agregar_playlist(track, self.gestor.biblioteca_playlists)
            return

        self._status("Cargando tus playlists...", "info")

        self._ejecutar_en_hilo(
            self.gestor.obtener_biblioteca_con_propietario,
            on_exito=lambda playlists: self._abrir_ventana_agregar_playlist(
                track, playlists
            ),
            on_error=lambda e: self._manejar_error(e, "Playlists:"),
            boton=self.btn_agregar_playlist_busqueda
        )

    def _abrir_ventana_agregar_playlist(self, track, playlists):

        propias = [
            pl for pl in playlists
            if pl.get('owner', {}).get('id') == self.gestor.usuario_id
            or pl.get('collaborative', False)
        ]

        if not propias:
            self._status(
                "No se encontraron playlists propias para agregar canciones.",
                "error"
            )
            return

        ventana = tk.Toplevel(self)
        ventana.title("Agregar a playlist")
        ventana.configure(bg=NEGRO_PANEL, padx=18, pady=16)
        ventana.resizable(False, False)
        ventana.transient(self)

        if self._ruta_icono:
            try:
                ventana.iconbitmap(self._ruta_icono)
            except Exception:
                pass
        ventana.grab_set()

        tk.Label(
            ventana,
            text=f"Agregar '{track.name}' a:",
            bg=NEGRO_PANEL, fg=BLANCO, font=F_TEXTO_B,
            wraplength=340, justify="left", anchor="w"
        ).pack(fill="x", pady=(0, 10))

        nombres = [pl.get('name', 'Sin nombre') for pl in propias]
        var_playlist = tk.StringVar(value=nombres[0])

        combo = ttk.Combobox(
            ventana, textvariable=var_playlist, values=nombres,
            state="readonly", font=F_TEXTO
        )
        combo.pack(fill="x")

        lbl_estado_ventana = tk.Label(
            ventana, text="", bg=NEGRO_PANEL, fg=GRIS_TEXTO,
            font=F_PEQUENA, anchor="w"
        )
        lbl_estado_ventana.pack(fill="x", pady=(8, 0))

        marco_botones = tk.Frame(ventana, bg=NEGRO_PANEL)
        marco_botones.pack(pady=(16, 0))

        def confirmar():

            indice_sel = nombres.index(var_playlist.get())
            playlist = propias[indice_sel]
            playlist_id = playlist.get('id')
            nombre_playlist = playlist.get('name', 'Playlist')

            btn_confirmar.configure(state="disabled")
            lbl_estado_ventana.configure(text="Agregando...", fg=GRIS_TEXTO)

            def exito(_resultado):
                self._status(
                    f"'{track.name}' agregada a '{nombre_playlist}'.", "ok"
                )
                ventana.destroy()

            def error(e):
                lbl_estado_ventana.configure(text=str(e), fg=ROJO_SUAVE)
                btn_confirmar.configure(state="normal")

            self._ejecutar_en_hilo(
                lambda: self.gestor.agregar_a_playlist(playlist_id, track.uri),
                on_exito=exito,
                on_error=error
            )

        btn_confirmar = self._boton(marco_botones, "✔ Agregar", confirmar, "primario")
        btn_confirmar.pack(side="left", padx=4)

        self._boton(
            marco_botones, "Cancelar", ventana.destroy, "secundario"
        ).pack(side="left", padx=4)


    def _refrescar_fila(self):
        for item in self.tree_fila.get_children():
            self.tree_fila.delete(item)

        tracks = self.gestor.fila_reproduccion

        indice_repetir = None
        if self.repetir_activo and tracks:
            indice_repetir = self._obtener_indice_fila_actual()

        for i, track in enumerate(tracks, start=1):
            inicio = self._fmt_tiempo(int(track.start_second))
            nombre = track.nombre_mostrado
            se_repite = (indice_repetir is not None and (i - 1) == indice_repetir)

            if se_repite:
                nombre = f"⮎⮌ {nombre}"

            self.tree_fila.insert(
                "", "end", iid=str(i),
                values=(i, nombre, track.artist, inicio),
                tags=("repitiendo",) if se_repite else ()
            )

        self.tree_fila.tag_configure(
            "repitiendo", background=VERDE_OSCURO, foreground=BLANCO
        )

    def _eliminar_de_fila(self):

        sel = self.tree_fila.selection()

        if not sel:
            self._status("Selecciona una canción de la fila.", "error")
            return

        indice = int(sel[0]) - 1

        try:
            eliminada = self.gestor.eliminar_de_fila(indice)
        except IndexError as e:
            self._manejar_error(e)
            return

        self._status(f"Eliminada: {eliminada.name}", "ok")
        self._refrescar_fila()

    def _cargar_biblioteca(self):

        self._status("Cargando tu biblioteca de playlists...", "info")

        self._ejecutar_en_hilo(
            self.gestor.obtener_biblioteca_con_propietario,
            on_exito=self._mostrar_biblioteca,
            on_error=lambda e: self._manejar_error(e, "Biblioteca:"),
            boton=self.btn_cargar_biblioteca
        )

    def _mostrar_biblioteca(self, playlists):

        for item in self.tree_biblioteca.get_children():
            self.tree_biblioteca.delete(item)

        usuario_id = self.gestor.usuario_id

        for i, pl in enumerate(playlists):

            total = pl.get('tracks', {}).get('total', 0)

            es_propia = (
                pl.get('owner', {}).get('id') == usuario_id
                or pl.get('collaborative', False)
            )

            self.tree_biblioteca.insert(
                "", "end", iid=str(i),
                values=(
                    pl.get('name', 'Sin nombre'), total,
                    "Sí" if es_propia else "No"
                )
            )

        self._status(f"{len(playlists)} playlists encontradas.", "ok")

    def _cargar_playlist_seleccionada(self):

        sel = self.tree_biblioteca.selection()

        if not sel:
            self._status("Selecciona una playlist de tu biblioteca.", "error")
            return

        indice = int(sel[0])
        playlist = self.gestor.biblioteca_playlists[indice]
        playlist_id = playlist.get('id')
        nombre = playlist.get('name', 'Playlist')

        es_propia = (
            playlist.get('owner', {}).get('id') == self.gestor.usuario_id
            or playlist.get('collaborative', False)
        )

        self._status(f"Cargando '{nombre}'...", "info")

        self._ejecutar_en_hilo(
            lambda: self.gestor.cargar_playlist(playlist_id, nombre, es_propia),
            on_exito=lambda resultado: self._mostrar_playlist_cargada(
                nombre, resultado
            ),
            on_error=lambda e: self._manejar_error(e, "Playlist:"),
            boton=self.btn_cargar_playlist
        )

    def _mostrar_playlist_cargada(self, nombre, resultado):

        canciones, total_items = resultado

        self._indice_playlist_actual = None

        for item in self.tree_playlist.get_children():
            self.tree_playlist.delete(item)

        for track in canciones:
            self.tree_playlist.insert(
                "", "end", iid=str(track.index),
                values=(
                    track.index, track.nombre_mostrado,
                    track.artist, track.duracion_texto
                )
            )

        self.lbl_playlist_actual.configure(
            text=f"📂 {nombre}  ·  {len(canciones)} canciones"
        )

        if canciones:
            self._status(
                f"'{nombre}' cargada con {len(canciones)} canciones.", "ok"
            )
        elif total_items > 0:
            self._status(
                f"'{nombre}' tiene {total_items} elementos, pero ninguno "
                "está disponible para reproducir en tu cuenta/mercado.",
                "error"
            )
        else:
            self._status(f"'{nombre}' está vacía.", "info")

    def _reproducir_seleccion_playlist(self):
        sel = self.tree_playlist.selection()
        if not sel:
            self._status("Selecciona una canción de la playlist.", "error")
            return
        indice = int(sel[0]) - 1
        track = self.gestor.playlist_actual[indice]
        segundo = self._obtener_segundo(self.entry_segundo_playlist)
        reiniciar_segundo_inicial(self.entry_segundo_playlist)
        self._indice_playlist_actual = indice
        self._modo_reproduccion = 'playlist'
        self._transicionar_a_track(track, segundo)

    def _agregar_seleccion_playlist_a_fila(self):

        sel = self.tree_playlist.selection()

        if not sel:
            self._status("Selecciona una canción de la playlist.", "error")
            return

        indice = int(sel[0]) - 1
        track = self.gestor.playlist_actual[indice]
        segundo = self._obtener_segundo(self.entry_segundo_playlist)
        reiniciar_segundo_inicial(self.entry_segundo_playlist)

        nuevo = self.gestor.agregar_a_fila(track, segundo)

        self._status(f"Agregada a la fila: {nuevo.name}", "ok")
        self._refrescar_fila()

    def _importar_letra(self):

        self._status("Buscando letra...", "info")

        self._ejecutar_en_hilo(
            self.gestor.importar_letra_actual,
            on_exito=self._letra_importada,
            on_error=lambda e: self._manejar_error(e, "Letra:"),
            boton=self.btn_importar_letra
        )

    def _letra_importada(self, resultado):

        titulo, artista, letra = resultado

        self._status(f"Letra guardada: {titulo} - {artista}", "ok")
        self._refrescar_letra_actual()
        self._refrescar_letras()

    def _refrescar_letra_actual(self):

        contenido = self.gestor.leer_letra_actual()

        self.texto_letra_actual.configure(state="normal")
        self.texto_letra_actual.delete("1.0", "end")
        self.texto_letra_actual.insert(
            "1.0",
            contenido if contenido else "Todavía no se ha buscado ninguna letra."
        )
        self.texto_letra_actual.configure(state="disabled")

    def _refrescar_letras(self):

        contenido = self.gestor.leer_letras_guardadas()

        self.texto_letras.configure(state="normal")
        self.texto_letras.delete("1.0", "end")
        self.texto_letras.insert(
            "1.0",
            contenido if contenido else "Todavía no hay letras guardadas."
        )
        self.texto_letras.configure(state="disabled")
        self.texto_letras.see("end")

    def _abrir_letras(self):

        try:
            self.gestor.abrir_archivo_letras()
        except Exception as e:
            self._manejar_error(e, "Archivo:")
            return

        self._status("Archivo abierto.", "ok")

    def _refrescar_dispositivos(self):

        self._status("Actualizando dispositivos...", "info")

        self._ejecutar_en_hilo(
            self.gestor.listar_dispositivos,
            on_exito=self._mostrar_dispositivos,
            on_error=lambda e: self._manejar_error(e, "Dispositivos:"),
            boton=self.btn_refrescar_dispositivos
        )

    def _mostrar_dispositivos(self, dispositivos):

        for item in self.tree_dispositivos.get_children():
            self.tree_dispositivos.delete(item)

        self._dispositivos_listados = dispositivos

        for i, d in enumerate(dispositivos):

            self.tree_dispositivos.insert(
                "", "end", iid=str(i),
                values=(
                    d.get('name'),
                    d.get('type'),
                    "SÍ" if d.get('is_active') else "NO",
                    self._texto_barra_actividad(d.get('is_active')),
                    (
                        f"{d.get('volume_percent')}%"
                        if d.get('volume_percent') is not None else "—"
                    ),
                    "SÍ" if d.get('supports_volume') else "NO",
                )
            )

        self._status(f"{len(dispositivos)} dispositivos.", "ok")

    def _reproducir_en_dispositivo_seleccionado(self):

        sel = self.tree_dispositivos.selection()

        if not sel:
            self._status("Selecciona un dispositivo de la lista.", "error")
            return

        indice = int(sel[0])
        dispositivo = self._dispositivos_listados[indice]
        device_id = dispositivo.get('id')
        nombre = dispositivo.get('name', 'dispositivo')

        self._status(f"Cambiando reproducción a '{nombre}'...", "info")

        self._ejecutar_en_hilo(
            lambda: self.gestor.reproducir_en_dispositivo(device_id),
            on_exito=lambda _r: self._tras_cambiar_dispositivo(nombre),
            on_error=lambda e: self._manejar_error(e, "Dispositivo:"),
            boton=self.btn_reproducir_aqui
        )

    def _tras_cambiar_dispositivo(self, nombre):

        self._status(f"Reproduciendo ahora en '{nombre}'.", "ok")
        self._actualizar_now_playing(silencioso=True)
        self._refrescar_dispositivos()

    def _salir(self):

        if messagebox.askyesno(
            "Salir", "¿Seguro que quieres cerrar EmmSound Studio? :)"
        ):
            self.destroy()

def main():

    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()