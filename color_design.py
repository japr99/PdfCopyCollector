import platform
import flet as ft
from lang import t


# FUNCIÓN DE DETECCIÓN AUTOMÁTICA DE TEMA (COMENTADA PARA USO FUTURO)
# Esta función detecta el tema del sistema operativo automáticamente
# Se mantiene comentada por si queremos usar la detección automática en el futuro

# def detectar_tema_oscuro():
#     tema_local = 'claro'
#     # valor por defecto (asegurar que siempre existe)
#     tema_flet = ft.ThemeMode.LIGHT
#     try:
#         if platform.system() == "Darwin":  # macOS
#             import subprocess
#             result = subprocess.run([
#                 'defaults', 'read', '-g', 'AppleInterfaceStyle'
#             ], capture_output=True, text=True)
#             if result.returncode == 0 and 'Dark' in result.stdout:
#                 tema_local = 'oscuro'
#                 tema_flet = ft.ThemeMode.DARK
#             else:
#                 tema_local = 'claro'
#                 tema_flet = ft.ThemeMode.LIGHT
#         elif platform.system() == "Windows":
#             # Detectar tema en Windows leyendo el registro (protegido)
#             try:
#                 import winreg
#                 key = winreg.OpenKey(
#                     winreg.HKEY_CURRENT_USER,
#                     r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
#                 )
#                 value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
#                 if value == 0:
#                     tema_local = 'oscuro'
#                     tema_flet = ft.ThemeMode.DARK
#                 else:
#                     tema_local = 'claro'
#                     tema_flet = ft.ThemeMode.LIGHT
#             except Exception:
#                 # Si no se puede leer el registro, quedarse con el valor por defecto
#                 tema_local = 'claro'
#                 tema_flet = ft.ThemeMode.LIGHT
#         else:
#             tema_local = 'desconocido'
#             tema_flet = ft.ThemeMode.LIGHT
#     except Exception:
#         tema_local = 'claro'
#         tema_flet = ft.ThemeMode.LIGHT
#         print("[WARN] No se pudo detectar el tema del sistema, usando claro por defecto.")
#     print(f"[INFO] Tema detectado: {tema_local}")
#     return tema_local, tema_flet


# --- Observadores para tema_flet (registrar callbacks desde la app) ---
_tema_callbacks = []


def bind_tema_flet(callback, call_now: bool = True):
    """Registrar callback(tema_local, tema_flet). Si call_now True, llama inmediatamente con el valor actual."""
    _tema_callbacks.append(callback)
    try:
        if call_now and "tema" in globals() and "tema_flet" in globals():
            callback(tema, tema_flet)
    except Exception:
        pass


def _notify_tema(tema_local_new, tema_flet_new):
    for cb in list(_tema_callbacks):
        try:
            cb(tema_local_new, tema_flet_new)
        except Exception:
            pass


# FUNCIÓN DE REFRESCAR TEMA (COMENTADA - USABA DETECCIÓN AUTOMÁTICA)
# def refrescar_tema():
#     """Re-ejecuta la detección y notifica a los callbacks."""
#     global tema, tema_flet
#     tema, tema_flet = detectar_tema_oscuro()
#     _notify_tema(tema, tema_flet)


def set_tema_manual(tema_local_new, tema_flet_new):
    """Establecer manualmente el tema y notificar (útil para toggles en la UI)."""
    global tema, tema_flet
    tema = tema_local_new
    tema_flet = tema_flet_new
    _notify_tema(tema, tema_flet)


# FUNCIONES DE DETECCIÓN AUTOMÁTICA DE TEMA (COMENTADAS PARA USO FUTURO)
# Estas funciones detectan automáticamente el tema del sistema y lo aplican
# Se mantienen comentadas por si queremos usar la detección automática en el futuro

# def _color_design_watcher():
#     """Hilo en background que detecta cambios de tema y notifica via set_tema_manual."""
#     global tema, tema_flet
#     try:
#         while True:
#             time.sleep(3)
#             try:
#                 nuevo_tema, nuevo_tema_flet = detectar_tema_oscuro()
#             except Exception:
#                 # Ignorar fallos temporales en la detección
#                 continue
#             # Si cambia, usar set_tema_manual para notificar a los callbacks
#             if nuevo_tema != tema or nuevo_tema_flet != tema_flet:
#                 try:
#                     set_tema_manual(nuevo_tema, nuevo_tema_flet)
#                     print(f"[INFO color_design_watcher] Tema cambiado a: {nuevo_tema}")
#                 except Exception:
#                     pass
#     except Exception as ex:
#         print(f"[ERROR color_design_watcher] {ex}")


# Inicializar tema por defecto - detectar tema inicial una vez al arrancar
def inicializar_tema_inicial():
    """Detecta el tema del sistema una sola vez al arrancar la aplicación"""
    global tema, tema_flet
    try:
        if platform.system() == "Darwin":  # macOS
            import subprocess

            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and "Dark" in result.stdout:
                tema = "oscuro"
                tema_flet = ft.ThemeMode.DARK
            else:
                tema = "claro"
                tema_flet = ft.ThemeMode.LIGHT
        elif platform.system() == "Windows":
            try:
                import winreg

                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                )
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                if value == 0:
                    tema = "oscuro"
                    tema_flet = ft.ThemeMode.DARK
                else:
                    tema = "claro"
                    tema_flet = ft.ThemeMode.LIGHT
            except Exception:
                tema = "claro"
                tema_flet = ft.ThemeMode.LIGHT
        else:
            tema = "claro"
            tema_flet = ft.ThemeMode.LIGHT
    except Exception:
        tema = "claro"
        tema_flet = ft.ThemeMode.LIGHT
        # print("[WARN] No se pudo detectar el tema del sistema, usando claro por defecto.")

    # print(f"[INFO] Tema inicial detectado: {tema}")
    return tema, tema_flet


# Inicializar tema detectando el sistema una vez (lazy - solo cuando se necesite)
tema = "claro"
tema_flet = ft.ThemeMode.LIGHT
_tema_inicializado = False


def _asegurar_tema_inicializado():
    """Inicializa el tema solo la primera vez que se llama"""
    global tema, tema_flet, _tema_inicializado
    if not _tema_inicializado:
        tema, tema_flet = inicializar_tema_inicial()
        _tema_inicializado = True


def definir_constantes_color():

    ligth_colors = ft.Theme(
        color_scheme=ft.ColorScheme(
            #### PRIMARIOS ####
            # TEXTO_COLOR_GENERICO
            # TEXTO_NUMEROS_GRAFICO_COLOR
            primary=ft.Colors.BLACK,
            # FONDO_APP
            on_surface=ft.Colors.BLUE_700,
            # FONDO_GRAFICO_COLOR
            tertiary_container=ft.Colors.GREY_300,
            # MARCO_GRAFICO_COLOR
            on_tertiary=ft.Colors.BLUE,
            # LINEA_DISCONTINUA_GRAFICO_COLOR
            on_tertiary_container=ft.Colors.RED_300,
            # SNACKBAR_COLOR_TEXTO
            surface=ft.Colors.BLUE_50,
            # SNACKBAR_COLOR_FONDO
            surface_tint=ft.Colors.BLUE_900,
            # DROPDOWN_TRAILING_ICON_COLOR
            # DROPDOWN_TEXT_STYLE_COLOR
            # TEXTOS_FASE_1_COLOR
            # TEXTOS_FASE_2_COLOR
            # TEXTO_BLOQUE_RESUMEN_COLOR
            inverse_surface=ft.Colors.BLACK,
            # DROPDOWN_FONDO_MENU_COLOR
            on_inverse_surface=ft.Colors.WHITE,
            # ICONO_PREF_COLOR
            on_primary=ft.Colors.BLACK,
            # ICONO_PREF_HOVER_COLOR
            on_primary_container=ft.Colors.WHITE,
            # FONDO_FASE_1
            on_secondary=ft.Colors.BLUE_200,
            # FONDO_FASE_2
            on_secondary_container=ft.Colors.BLUE_200,
            # FONDO_SECCIONES
            on_surface_variant=ft.Colors.BLUE_200,
            # COLOR_TEXTO_MENU
            inverse_primary=ft.Colors.BLUE_50,
            # FONDO_MENU_AJUSTES
            secondary=ft.Colors.BLUE_900,
            # FONDO_ALERT_DIALOG
            secondary_container=ft.Colors.BLUE_200,
            # BOTONES_GENERICOS_TEXTO_COLOR
            shadow=ft.Colors.WHITE,
            # FONDO_BARRA_SUPERIOR
            error=ft.Colors.BLUE_200,
            # FONDO_CALCULO_FASE_1
            on_error_container=ft.Colors.BLUE_300,
            # FONDO_HEADER_FASE_1
            on_error=ft.Colors.BLUE_500,
            # FONDO_TEXTFIELDS_COLOR
            outline=ft.Colors.BLUE_100,
            # BORDE_TEXTFIELDS_COLOR
            outline_variant=ft.Colors.BLUE_900,
            # FONDO_BLOQUE_RESUMEN_COLOR
            tertiary=ft.Colors.BLUE_600,
        ),
        scrollbar_theme=ft.ScrollbarTheme(
            thumb_color=ft.Colors.BLUE_900,
            thickness=8,
            radius=4,
        ),
    )

    dark_colors = ft.Theme(
        color_scheme=ft.ColorScheme(
            #### PRIMARIOS ###
            # TEXTO_COLOR_GENERICO
            # TEXTO_NUMEROS_GRAFICO_COLOR
            primary=ft.Colors.WHITE,
            # FONDO_APP
            on_surface=ft.Colors.GREY_800,
            # FONDO_GRAFICO_COLOR
            tertiary_container=ft.Colors.GREY_600,
            # MARCO_GRAFICO_COLOR
            on_tertiary=ft.Colors.BLACK,
            # LINEA_DISCONTINUA_GRAFICO_COLOR
            on_tertiary_container=ft.Colors.GREY_300,
            #### SNACKBAR ####
            # SNACKBAR_COLOR_TEXTO
            surface=ft.Colors.WHITE,
            # SNACKBAR_COLOR_FONDO
            surface_tint=ft.Colors.GREY_800,
            # COLOR_TEXTO_MENU
            inverse_primary=ft.Colors.WHITE,
            # DROPDOWN_TRAILING_ICON_COLOR
            # DROPDOWN_TEXT_STYLE_COLOR
            # TEXTOS_FASE_1_COLOR
            # TEXTOS_FASE_2_COLOR
            # TEXTO_BLOQUE_RESUMEN_COLOR
            inverse_surface=ft.Colors.WHITE,
            # DROPDOWN_FONDO_MENU_COLOR
            on_inverse_surface=ft.Colors.GREY_200,
            # ICONO_PREF_COLOR
            on_primary=ft.Colors.WHITE,
            # ICONO_PREF_HOVER_COLOR
            on_primary_container=ft.Colors.BLACK,
            # FONDO_FASE_1
            on_secondary=ft.Colors.GREY_700,
            # FONDO_FASE_2
            on_secondary_container=ft.Colors.GREY_700,
            # FONDO_SECCIONES
            on_surface_variant=ft.Colors.GREY_600,
            # FONDO_MENU_AJUSTES
            secondary=ft.Colors.GREY_800,
            # FONDO_ALERT_DIALOG
            secondary_container=ft.Colors.GREY_800,
            # BOTONES_GENERICOS_TEXTO_COLOR
            shadow=ft.Colors.BLACK,
            # FONDO_BARRA_SUPERIOR
            error=ft.Colors.GREY_800,
            # FONDO_CALCULO_FASE_1
            on_error_container=ft.Colors.GREY_600,
            # FONDO_HEADER_FASE_1
            on_error=ft.Colors.GREY_800,
            # FONDO_TEXTFIELDS_COLOR
            outline=ft.Colors.GREY_800,
            # BORDE_TEXTFIELDS_COLOR
            outline_variant=ft.Colors.GREY_500,
            # FONDO_BLOQUE_RESUMEN_COLOR
            tertiary=ft.Colors.GREY_900,
        ),
        scrollbar_theme=ft.ScrollbarTheme(
            thumb_color=ft.Colors.GREY_400,
            thickness=8,
            radius=4,
        ),
    )

    return ligth_colors, dark_colors


def actualizar_colores():
    """Recalcula todas las constantes de color dependientes de `tema`.
    Llamar tras cambiar `tema` para mantener coherencia.
    """
    global COLOR_TEXTO_MENU, DROPDOWN_TRAILING_ICON_COLOR, TEXTO_NUMEROS_GRAFICO_COLOR, MARCO_GRAFICO_COLOR, LINEA_DISCONTINUA_GRAFICO_COLOR, FONDO_GRAFICO_COLOR, SNACKBAR_COLOR_ERROR, SNACKBAR_COLOR_FONDO, SNACKBAR_COLOR_TEXTO, TEXTO_COLOR_GENERICO, ICONO_PREF_COLOR, ICONO_PREF_HOVER_COLOR, FONDO_BARRA_SUPERIOR, FONDO_MENU_AJUSTES, FONDO_ALERT_DIALOG, BOTONES_GENERICOS_TEXTO_COLOR, BOTONES_GENERICOS_COLOR, BOTONES_GENERICOS_HOVER_COLOR, BOTONES_GENERICOS_OVERLAY_COLOR, BOTONES_GENERICOS_FONDO_COLOR, FONDO_ALERT_DIALOG, SUCCESS_COLOR, ERROR_COLOR, INFO_COLOR, DROPDOWN_TEXT_STYLE_COLOR, FONDO_APP, FONDO_SECCIONES, FONDO_FASE_1, FONDO_FASE_2, TEXTOS_FASE_1_COLOR, TEXTOS_FASE_2_COLOR, FONDO_TEXTFIELDS_COLOR, BORDE_TEXTFIELDS_COLOR, DROPDOWN_FONDO_MENU_COLOR, FONDO_BLOQUE_RESUMEN_COLOR, TEXTO_BLOQUE_RESUMEN_COLOR, FONDO_CALCULO_FASE_1, FONDO_HEADER_FASE_1, LINEA_CONTINUA_GRAFICO_COLOR, CHECKBOX_FILL_COLOR

    # Asegurar que el tema esté inicializado
    _asegurar_tema_inicializado()

    COLOR_TEXTO_MENU = ft.Colors.INVERSE_PRIMARY

    DROPDOWN_FONDO_MENU_COLOR = ft.Colors.ON_INVERSE_SURFACE
    DROPDOWN_TEXT_STYLE_COLOR = ft.Colors.INVERSE_SURFACE
    DROPDOWN_TRAILING_ICON_COLOR = ft.Colors.INVERSE_SURFACE

    # GENERICOS
    TEXTO_COLOR_GENERICO = ft.Colors.PRIMARY
    FONDO_APP = ft.Colors.ON_SURFACE

    # GRAFICO
    TEXTO_NUMEROS_GRAFICO_COLOR = ft.Colors.PRIMARY
    FONDO_GRAFICO_COLOR = ft.Colors.TERTIARY_CONTAINER
    MARCO_GRAFICO_COLOR = ft.Colors.ON_TERTIARY
    LINEA_CONTINUA_GRAFICO_COLOR = ft.Colors.ON_TERTIARY
    LINEA_DISCONTINUA_GRAFICO_COLOR = ft.Colors.ON_TERTIARY_CONTAINER

    # SNACKBAR
    SNACKBAR_COLOR_TEXTO = ft.Colors.SURFACE
    SNACKBAR_COLOR_ERROR = ft.Colors.RED
    SNACKBAR_COLOR_FONDO = ft.Colors.SURFACE_TINT

    # ICONOS
    ICONO_PREF_COLOR = ft.Colors.ON_PRIMARY
    ICONO_PREF_HOVER_COLOR = ft.Colors.ON_PRIMARY_CONTAINER

    FONDO_FASE_1 = ft.Colors.ON_SECONDARY

    FONDO_FASE_2 = ft.Colors.ON_SECONDARY_CONTAINER

    FONDO_SECCIONES = ft.Colors.ON_SURFACE_VARIANT

    FONDO_MENU_AJUSTES = ft.Colors.SECONDARY

    FONDO_ALERT_DIALOG = ft.Colors.SECONDARY_CONTAINER

    BOTONES_GENERICOS_TEXTO_COLOR = ft.Colors.SHADOW

    TEXTOS_FASE_1_COLOR = ft.Colors.INVERSE_SURFACE

    TEXTOS_FASE_2_COLOR = ft.Colors.INVERSE_SURFACE

    TEXTO_BLOQUE_RESUMEN_COLOR = ft.Colors.INVERSE_SURFACE

    FONDO_CALCULO_FASE_1 = ft.Colors.ON_ERROR_CONTAINER

    FONDO_HEADER_FASE_1 = ft.Colors.ON_ERROR

    FONDO_BARRA_SUPERIOR = ft.Colors.ERROR

    FONDO_TEXTFIELDS_COLOR = ft.Colors.OUTLINE

    BORDE_TEXTFIELDS_COLOR = ft.Colors.OUTLINE_VARIANT

    # BOTONES_GENERICOS_COLOR = ft.Colors.WHITE if tema == 'oscuro' else ft.Colors.BLACK
    BOTONES_GENERICOS_COLOR = ft.Colors.ON_PRIMARY

    # BOTONES_GENERICOS_HOVER_COLOR = ft.Colors.BLACK if tema == 'oscuro' else ft.Colors.WHITE
    BOTONES_GENERICOS_HOVER_COLOR = ft.Colors.ON_PRIMARY_CONTAINER

    # BOTONES_GENERICOS_OVERLAY_COLOR = ft.Colors.WHITE if tema == 'oscuro' else ft.Colors.BLACK
    BOTONES_GENERICOS_OVERLAY_COLOR = ft.Colors.ON_PRIMARY

    # BOTONES_GENERICOS_FONDO_COLOR = ft.Colors.BLACK if tema == 'oscuro' else ft.Colors.WHITE
    BOTONES_GENERICOS_FONDO_COLOR = ft.Colors.ON_PRIMARY_CONTAINER

    # FONDO_BLOQUE_RESUMEN_COLOR = ft.Colors.GREY_800 if tema == 'oscuro' else ft.Colors.BLUE_100
    FONDO_BLOQUE_RESUMEN_COLOR = ft.Colors.TERTIARY

    # Colores para estados en diálogos
    SUCCESS_COLOR = ft.Colors.GREEN
    ERROR_COLOR = ft.Colors.RED
    INFO_COLOR = TEXTO_COLOR_GENERICO

    # CHECKBOX
    CHECKBOX_FILL_COLOR = ft.Colors.PRIMARY


# Ejecutar la primera inicialización de constantes
actualizar_colores()

# WATCHER AUTOMÁTICO COMENTADO - ahora usamos selector manual
# Iniciar el watcher en import (daemon para que no bloquee la salida) — mover tras inicialización
# threading.Thread(target=_color_design_watcher, daemon=True).start()
