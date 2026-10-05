import flet as ft
import logging
import os
import sys
import threading
import asyncio

from lang import get_text
from pdf_merger import (
    PdfCollectorError,
    validate_files,
    merge_pdfs,
    _get_pdf_page_count,
)
from fiery_export import generate_fiery_info
from preferences import get_preference, save_preference

# Agregar el directorio padre al path para importar color_design
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

import color_design

logger = logging.getLogger(__name__)

APP_VERSION = "1.0.2"

"""
1.0.1
Añadido soporte para usar el mismo archivo como copias.
"""
"""
1.0.2
trimbox, bleedbox y optimizacion subsetfonts.
"""

def get_resource_path(relative_path):
    """Obtiene la ruta absoluta del recurso, compatible con PyInstaller"""
    try:
        # PyInstaller crea una carpeta temporal y guarda su ruta en _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def _dump_client_entitlements(bundle):
    """Vuelca a un temporal los entitlements actuales del bundle (o None).

    `codesign --force` los borra si no se los vuelves a pasar, y el cliente
    Flutter los necesita: com.apple.security.files.user-selected.read-write
    es lo que permite al file_picker abrir diálogos (sin él →
    ENTITLEMENT_NOT_FOUND). Se llama justo antes de re-firmar.
    """
    import subprocess
    import tempfile

    dump = subprocess.run(
        ["codesign", "-d", "--entitlements", ":-", "--xml", str(bundle)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if dump.returncode != 0 or not dump.stdout:
        return None
    xml_at = dump.stdout.find("<?xml")
    if xml_at < 0:
        xml_at = dump.stdout.find("<plist")
    if xml_at < 0:
        return None
    fd, path = tempfile.mkstemp(suffix=".entitlements.plist")
    with os.fdopen(fd, "w") as f:
        f.write(dump.stdout[xml_at:])
    return path


def _heal_flt_client_cache() -> None:
    """Garantiza que el cliente cacheado se llama PdfCopyCollector (nunca Flet).

    flet_desktop.ensure_client_cached solo comprueba que exista la CARPETA
    (~/.flet/client/flet-desktop-*) y la devuelve tal cual. Sin el parche
    plain_client_cache esa carpeta es la compartida "flet-desktop-full-<ver>",
    que pueden haber poblado otras apps (p.ej. TalNumStack.app) → el Dock
    enseñaría el bundle de otra app. Aquí se valida por NOMBRE del bundle (el
    hash del tar cambia con cada rebuild) y se repara:
      - empaquetada: se borra la caché contaminada → se re-extrae del tar
        embebido (flet pack ya lo deja branded y firmado).
      - dev: no hay tar branded → se renombra el bundle, se parchea el plist
        y se re-firma ad-hoc (mismo gesto que flet pack al ensamblar).
    No devuelve nada: el icono ya no se decide aquí (ver
    _brand_and_set_client_icon, que usa su propio marcador).

    El re-firmado DEBE llevar los entitlements de antes (mismo truco que
    scripts/flet_pack_ents_patch.py): `codesign --force` sin `--entitlements`
    los borra, y sin com.apple.security.files.user-selected.read-write el
    file_picker revienta con ENTITLEMENT_NOT_FOUND. Al revés también duele:
    flet pack copia el cliente DE ESTA caché, así que si aquí se perdieran,
    el tar empaquetado saldría sin ellos para siempre.
    """
    if sys.platform != "darwin":
        return
    try:
        import builtins
        import shutil
        import subprocess
        import plistlib

        from flet_desktop import ensure_client_cached, find_macos_app_bundle

        cache_dir = ensure_client_cached()
        bundle = find_macos_app_bundle(cache_dir)

        if bundle is None:
            builtins.print(f"[FLET] Caché hueca sin cliente, regenerando: {cache_dir}")
            shutil.rmtree(cache_dir, ignore_errors=True)
            cache_dir = ensure_client_cached()
            bundle = find_macos_app_bundle(cache_dir)

        if bundle is not None and bundle.name != "PdfCopyCollector.app":
            if getattr(sys, "frozen", False):
                builtins.print(
                    f"[FLET] Cliente {bundle.name} no es de la app, re-extrayendo del tar: {cache_dir}"
                )
                shutil.rmtree(cache_dir, ignore_errors=True)
                cache_dir = ensure_client_cached()
                bundle = find_macos_app_bundle(cache_dir)
            else:
                # Volcar los entitlements ANTES de tocar nada: el re-firmado
                # los borraría y el file_picker dejaría de poder abrir diálogos.
                ents_path = _dump_client_entitlements(bundle)
                renombrado = bundle.parent / "PdfCopyCollector.app"
                bundle.rename(renombrado)
                bundle = renombrado
                plist_path = bundle / "Contents" / "Info.plist"
                with open(plist_path, "rb") as f:
                    pl = plistlib.load(f)
                pl["CFBundleName"] = "PdfCopyCollector"
                pl["CFBundleDisplayName"] = "PdfCopyCollector"
                pl["CFBundleIdentifier"] = "com.japr.pdfcopycollector"
                with open(plist_path, "wb") as f:
                    plistlib.dump(pl, f)
                cmd = ["codesign", "--force", "--deep", "-s", "-"]
                if ents_path:
                    cmd += ["--entitlements", ents_path]
                subprocess.run([*cmd, str(bundle)], check=False)
                if ents_path:
                    os.remove(ents_path)
                builtins.print(f"[FLET] Cliente renombrado a {bundle.name} (dev)")
    except Exception as e:
        import builtins

        builtins.print(f"[FLET] Aviso saneando caché del cliente: {e}")


def _brand_and_set_client_icon() -> None:
    """Pone el icono propio en el cliente Flet (solo darwin).

    El icono del cliente es Contents/Resources/AppIcon.icns (lo apunta
    CFBundleIconFile) y dentro del tar va el genérico de Flet. Copiar el
    nuestro encima es determinista; NSWorkspace.setIcon NO servía: solo dejaba
    puesta la bandera kHasCustomIcon en FinderInfo sin datos de icono detrás,
    así que el Dock seguía enseñando el de Flet.

    Se compara byte a byte → si ya es el nuestro no se toca nada (ni se
    re-firma) en cada arranque. Si cambia, hay que re-firmar después, porque el
    .icns es parte de lo firmado, y con los entitlements delante: sin
    com.apple.security.files.user-selected.read-write el file_picker revienta
    con ENTITLEMENT_NOT_FOUND.

    De paso borra cachés viejas de ESTA app (nunca las de las hermanas).
    Nunca revienta la app si algo falla.
    """
    if sys.platform != "darwin":
        return
    try:
        import builtins
        import shutil
        import subprocess
        import time

        from flet_desktop import ensure_client_cached, find_macos_app_bundle

        cache_dir = ensure_client_cached()
        bundle = find_macos_app_bundle(cache_dir)

        if bundle is None:
            builtins.print("[FLET] cliente sin bundle, icono no aplicado")
            return

        icns = get_resource_path(os.path.join("assets", "Application.icns"))
        destino = bundle / "Contents" / "Resources" / "AppIcon.icns"
        with open(icns, "rb") as f:
            nuestro = f.read()
        if not destino.exists() or destino.read_bytes() != nuestro:
            ents_path = _dump_client_entitlements(bundle)
            shutil.copyfile(icns, destino)
            cmd = ["codesign", "--force", "--deep", "-s", "-"]
            if ents_path:
                cmd += ["--entitlements", ents_path]
            subprocess.run([*cmd, str(bundle)], check=False)
            if ents_path:
                os.remove(ents_path)
            builtins.print(f"[FLET] icono PdfCopyCollector aplicado: {bundle}")

        root = cache_dir.parent
        for entry in root.glob("flet-desktop-full-*_pdfcopycollector"):
            if entry.name == cache_dir.name or not entry.is_dir():
                continue
            lu = entry / ".last-used"
            try:
                age = time.time() - lu.stat().st_mtime if lu.exists() else None
            except OSError:
                age = None
            # no borrar si otra instancia la usó hoy
            if age is None or age > 86400:
                shutil.rmtree(entry, ignore_errors=True)
                builtins.print(f"[FLET] caché cliente vieja borrada: {entry.name}")
    except Exception as e:
        import builtins

        builtins.print(f"[FLET] Aviso branding del cliente: {e}")


def main(page: ft.Page):
    # Inicializar modo desde el sistema según color_design
    color_design._asegurar_tema_inicializado()
    color_design.actualizar_colores()

    page.title = "PdfCopyCollector"

    # Configurar icono de la ventana (especialmente para Windows y setups empaquetados)
    try:
        # Intentar cargar desde la nueva carpeta assets con extensión .ico primero
        _icon_path = get_resource_path(os.path.join("assets", "icon.ico"))
        if not os.path.exists(_icon_path):
            # Fallback al archivo .png
            _icon_path = get_resource_path(os.path.join("assets", "icon.png"))

        if os.path.exists(_icon_path):
            page.window.icon = _icon_path
    except Exception:
        pass

    page.window.width = 870
    page.window.height = 850
    page.window.min_width = 870
    page.window.min_height = 850
    page.padding = 20
    page.run_task(page.window.center)  # Flet 1.0: center() es async

    # Estado de la UI
    state = {
        "lang": get_preference("language", "es"),
        "workflow_mode": get_preference("workflow_mode", "copy_collector"),
        "same_file_for_copies": get_preference("same_file_for_copies", False),
        "files": [],
        "file_pages": [],
        "copies": "2",
        "copies_backup": None,
        "print_mode": "simplex",
        "fiery": True,
        "optimize_level": 0,
        "is_processing": False,
        "ui_locked": False,
    }
    cancel_event = threading.Event()
    close_watchdog_timer = None
    closing_in_progress = False

    def t(key, *args):
        return get_text(state["lang"], key, *args)

    def _cancel_close_watchdog():
        nonlocal close_watchdog_timer
        try:
            if close_watchdog_timer is not None:
                close_watchdog_timer.cancel()
        except Exception:
            pass
        close_watchdog_timer = None

    def _activate_close_watchdog_windows(timeout_sec=2.0):
        nonlocal close_watchdog_timer
        if not sys.platform.startswith("win"):
            return

        def _force_exit_on_timeout():
            try:
                logger.warning(
                    "[WINDOW CLOSE] Timeout agotado en CopyCollector, forzando salida en Windows"
                )
            except Exception:
                pass
            try:
                os._exit(0)
            except Exception:
                pass

        _cancel_close_watchdog()
        try:
            timer = threading.Timer(timeout_sec, _force_exit_on_timeout)
            timer.daemon = True
            close_watchdog_timer = timer
            timer.start()
        except Exception:
            pass

    def _request_close():
        nonlocal closing_in_progress
        if closing_in_progress:
            return
        closing_in_progress = True

        async def _finalize_close_async():
            try:
                # Ocultar primero reduce la percepción de bloqueo al cerrar.
                page.window.visible = False
                page.update()
            except Exception:
                pass

            _activate_close_watchdog_windows(timeout_sec=2.0)

            try:
                await asyncio.sleep(0.05)
            except Exception:
                pass

            try:
                await page.window.destroy()  # Flet 1.0: destroy() es async
            except Exception:
                pass
            finally:
                _cancel_close_watchdog()

        try:
            page.run_task(_finalize_close_async)
        except Exception:

            def _fallback_close():
                _activate_close_watchdog_windows(timeout_sec=2.0)
                try:
                    # Desde el hilo no se puede await: programar el coroutine en el loop
                    loop = getattr(page, "loop", None)
                    if loop is not None:
                        loop.create_task(page.window.destroy())
                except Exception:
                    pass
                finally:
                    _cancel_close_watchdog()

            fallback_timer = threading.Timer(0.05, _fallback_close)
            fallback_timer.daemon = True
            fallback_timer.start()

    def on_window_event(e):
        # Flet 1.0: WindowEvent trae e.type (enum WindowEventType); en 0.28 era e.data
        if getattr(e, "type", None) != ft.WindowEventType.CLOSE:
            return

        if state["ui_locked"] or state["is_processing"]:
            page.show_dialog(
                ft.SnackBar(
                    ft.Text(
                        f"{t('warning')}: {t('close_blocked_processing')}",
                        color=color_design.SNACKBAR_COLOR_TEXTO,
                    ),
                    bgcolor=color_design.SNACKBAR_COLOR_FONDO,
                )
            )
            return

        _request_close()

    page.window.on_event = on_window_event

    def toggle_theme(e):
        nuevo_tema = "oscuro" if color_design.tema == "claro" else "claro"
        nuevo_flet = ft.ThemeMode.DARK if nuevo_tema == "oscuro" else ft.ThemeMode.LIGHT
        color_design.set_tema_manual(nuevo_tema, nuevo_flet)
        color_design.actualizar_colores()
        build_ui()

    def build_ui():
        # Limpiar controles y pickers previos para evitar acumulación en overlay
        if page.controls is not None:
            page.controls.clear()
        page.overlay.clear()

        light_theme, dark_theme = color_design.definir_constantes_color()
        page.theme = light_theme
        page.dark_theme = dark_theme
        page.theme_mode = color_design.tema_flet
        page.bgcolor = color_design.FONDO_APP

        # Componentes UI
        title_text = ft.Text(
            t("app_title"),
            size=26,
            weight=ft.FontWeight.BOLD,
            color=color_design.TEXTO_COLOR_GENERICO,
        )

        # Selector de idioma
        def on_lang_change(e):
            state["lang"] = lang_dropdown.value
            save_preference("language", state["lang"])
            build_ui()

        # Flet 1.0: border_radius/border_color deprecados (fuera en 1.3.0)
        def _input_border():
            return ft.OutlineInputBorder(
                border_radius=8,
                side=ft.BorderSide(color=color_design.BORDE_TEXTFIELDS_COLOR),
            )

        lang_dropdown = ft.Dropdown(
            options=[
                ft.dropdown.Option("es", "Español"),
                ft.dropdown.Option("en", "English"),
                ft.dropdown.Option("cat", "Català"),
            ],
            value=state["lang"],
            width=150,
            label=t("language"),
            on_select=on_lang_change,
            disabled=state["is_processing"],
            border=_input_border(),
            filled=True,
            fill_color=color_design.FONDO_TEXTFIELDS_COLOR,
            color=color_design.DROPDOWN_TEXT_STYLE_COLOR,
            bgcolor=color_design.DROPDOWN_FONDO_MENU_COLOR,
            label_style=ft.TextStyle(color=color_design.DROPDOWN_TEXT_STYLE_COLOR),
            trailing_icon=ft.Icon(
                ft.Icons.ARROW_DROP_DOWN,
                color=color_design.DROPDOWN_TRAILING_ICON_COLOR,
            ),
        )

        # Botón para modo claro/oscuro
        theme_icon = (
            ft.Icons.DARK_MODE if color_design.tema == "claro" else ft.Icons.LIGHT_MODE
        )
        theme_btn = ft.IconButton(
            icon=theme_icon,
            icon_color=color_design.ICONO_PREF_COLOR,
            on_click=toggle_theme,
            tooltip=t("theme_tooltip"),
            disabled=state["is_processing"],
        )

        # Diálogo de información / ayuda
        def open_info_dialog(e):
            def cl_dialog(e):
                page.pop_dialog()

            page_width = page.width or 0
            page_height = page.height or 0
            w = max(500, int(page_width * 0.9)) if page_width else 500
            h = max(400, int(page_height * 0.9)) if page_height else 400

            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text(
                    t("info"),
                    weight=ft.FontWeight.BOLD,
                    size=24,
                    text_align=ft.TextAlign.CENTER,
                ),
                content=ft.Container(
                    ft.Column(
                        [
                            ft.Text(
                                t("info_version", APP_VERSION),
                                size=18,
                            ),
                            ft.Row(
                                [
                                    ft.Container(
                                        content=ft.Icon(
                                            ft.Icons.COFFEE,
                                            size=18,
                                            color=color_design.ICONO_PREF_COLOR,
                                        ),
                                        margin=ft.Margin.only(top=2),
                                    ),
                                    ft.Text(
                                        spans=[
                                            ft.TextSpan(
                                                t("invite_coffee"),
                                                url="https://paypal.me/japr99",
                                                style=ft.TextStyle(
                                                    color=color_design.TEXTO_COLOR_GENERICO,
                                                    decoration=ft.TextDecoration.UNDERLINE,
                                                    weight=ft.FontWeight.BOLD,
                                                ),
                                            )
                                        ],
                                        size=14,
                                    ),
                                ],
                                spacing=6,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Container(height=10),
                            ft.Text(
                                t("help_text_1"),
                                size=14,
                                color=color_design.TEXTO_COLOR_GENERICO,
                            ),
                            ft.Container(height=5),
                            ft.Text(
                                t("help_text_2"),
                                size=14,
                                color=color_design.TEXTO_COLOR_GENERICO,
                            ),
                            ft.Container(height=5),
                            ft.Text(
                                t("help_text_insert"),
                                size=14,
                                color=color_design.TEXTO_COLOR_GENERICO,
                            ),
                            ft.Container(height=8),
                            ft.Divider(height=1),
                            ft.Container(height=4),
                            ft.Text(
                                t("help_pdfcollector_title"),
                                size=14,
                                weight=ft.FontWeight.BOLD,
                                color=color_design.TEXTO_COLOR_GENERICO,
                            ),
                            ft.Container(height=4),
                            ft.Text(
                                t("help_pdfcollector_text"),
                                size=14,
                                color=color_design.TEXTO_COLOR_GENERICO,
                            ),
                            ft.Container(height=8),
                            ft.Divider(height=1),
                            ft.Container(height=4),
                            ft.Text(
                                t("help_opt_title"),
                                size=14,
                                weight=ft.FontWeight.BOLD,
                                color=color_design.TEXTO_COLOR_GENERICO,
                            ),
                            ft.Container(height=4),
                            ft.Text(
                                t("help_opt_no_optimize"),
                                size=14,
                                color=color_design.TEXTO_COLOR_GENERICO,
                            ),
                            ft.Text(
                                t("help_opt_standard"),
                                size=14,
                                color=color_design.TEXTO_COLOR_GENERICO,
                            ),
                            ft.Text(
                                t("help_opt_no_duplicates"),
                                size=14,
                                color=color_design.TEXTO_COLOR_GENERICO,
                            ),
                            ft.Container(height=8),
                            ft.Divider(height=1),
                            ft.Container(height=4),
                            ft.Text(
                                spans=[
                                    ft.TextSpan(
                                        t("LICENSE_NOTICE").rsplit(
                                            "gnu.org/licenses/agpl-3.0.html", 1
                                        )[0]
                                    ),
                                    ft.TextSpan(
                                        "gnu.org/licenses/agpl-3.0.html",
                                        url="https://www.gnu.org/licenses/agpl-3.0.html",
                                        style=ft.TextStyle(
                                            color=color_design.TEXTO_COLOR_GENERICO,
                                            decoration=ft.TextDecoration.UNDERLINE,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                    ),
                                ],
                                size=12,
                            ),
                        ],
                        spacing=8,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    width=w,
                    height=h,
                    padding=ft.Padding(12, 8, 12, 8),
                ),
                actions=[
                    ft.Button(
                        content=t("close"),
                        width=80,
                        bgcolor=color_design.BOTONES_GENERICOS_FONDO_COLOR,
                        on_click=cl_dialog,
                        style=ft.ButtonStyle(
                            color={
                                ft.ControlState.DEFAULT: color_design.BOTONES_GENERICOS_COLOR,
                                ft.ControlState.HOVERED: color_design.BOTONES_GENERICOS_HOVER_COLOR,
                            },
                            overlay_color=color_design.BOTONES_GENERICOS_OVERLAY_COLOR,
                            padding=ft.Padding(0, 0, 0, 0),
                            shape=ft.RoundedRectangleBorder(radius=10),
                        ),
                    ),
                ],
                bgcolor=color_design.FONDO_ALERT_DIALOG,
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.show_dialog(dialog)

        info_btn = ft.IconButton(
            icon=ft.Icons.INFO_OUTLINED,
            icon_color=color_design.ICONO_PREF_COLOR,
            on_click=open_info_dialog,
            tooltip=t("info"),
            disabled=state["is_processing"],
        )

        def normalize_copycollector_files():
            if not state["files"]:
                state["file_pages"] = []
                state["copies"] = "2"
                copies_input.value = "2"
                copies_input.error = None
                return

            verified_pages = []
            for index, file_path in enumerate(state["files"]):
                try:
                    pages = _get_pdf_page_count(file_path)
                except Exception:
                    pages = (
                        state["file_pages"][index]
                        if index < len(state["file_pages"])
                        else 0
                    )
                verified_pages.append(pages)

            base_pages = verified_pages[0]
            filtered_files = [state["files"][0]]
            filtered_pages = [base_pages]

            for file_path, pages in zip(state["files"][1:], verified_pages[1:]):
                if pages == base_pages:
                    filtered_files.append(file_path)
                    filtered_pages.append(pages)

            state["files"] = filtered_files
            state["file_pages"] = filtered_pages

            keep_requested_copies = (
                state["same_file_for_copies"] and len(filtered_files) == 1
            )
            if keep_requested_copies:
                try:
                    requested = int(str(state.get("copies", "2")))
                except Exception:
                    requested = 2
                state["copies"] = str(max(2, requested))
            else:
                state["copies"] = str(max(2, len(filtered_files)))

            if len(filtered_files) != 1 and state["same_file_for_copies"]:
                state["same_file_for_copies"] = False
                save_preference("same_file_for_copies", False)

            copies_input.value = state["copies"]
            copies_input.error = None

        def on_workflow_mode_change(mode):
            if state["ui_locked"] or state["is_processing"]:
                return
            if state["workflow_mode"] == mode:
                return

            state["workflow_mode"] = mode
            save_preference("workflow_mode", mode)

            if mode == "pdf_collector":
                state["fiery"] = False
            elif mode == "copy_collector":
                normalize_copycollector_files()
            update_ui_state()

        mode_copy_text = ft.TextButton(
            "PdfCopyCollector",
            on_click=lambda _: on_workflow_mode_change("copy_collector"),
            style=ft.ButtonStyle(
                color=(
                    color_design.TEXTO_COLOR_GENERICO
                    if state["workflow_mode"] == "copy_collector"
                    else color_design.DROPDOWN_TEXT_STYLE_COLOR
                ),
                text_style=ft.TextStyle(
                    size=24,
                    weight=(
                        ft.FontWeight.BOLD
                        if state["workflow_mode"] == "copy_collector"
                        else ft.FontWeight.W_400
                    ),
                ),
            ),
        )

        mode_pdf_text = ft.TextButton(
            "PdfCollector",
            on_click=lambda _: on_workflow_mode_change("pdf_collector"),
            style=ft.ButtonStyle(
                color=(
                    color_design.TEXTO_COLOR_GENERICO
                    if state["workflow_mode"] == "pdf_collector"
                    else color_design.DROPDOWN_TEXT_STYLE_COLOR
                ),
                text_style=ft.TextStyle(
                    size=24,
                    weight=(
                        ft.FontWeight.BOLD
                        if state["workflow_mode"] == "pdf_collector"
                        else ft.FontWeight.W_400
                    ),
                ),
            ),
        )

        title_switch = ft.Row(
            [
                mode_copy_text,
                ft.Text("-", size=22, color=color_design.TEXTO_COLOR_GENERICO),
                mode_pdf_text,
            ],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        top_row = ft.Row(
            [
                title_switch,
                ft.Row(
                    [info_btn, theme_btn, lang_dropdown],
                    spacing=5,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # Guardar en estado temporalmente al cambiar
        def save_state_and_update(e=None):
            previous_mode = state["print_mode"]
            new_mode = print_mode_dropdown.value
            state["print_mode"] = new_mode

            if new_mode == "insert_page":
                if previous_mode != "insert_page":
                    state["copies_backup"] = state["copies"]
                state["copies"] = "2"
                copies_input.value = "2"
                copies_input.error = None
                state["fiery"] = False
                fiery_checkbox.value = False
            else:
                if previous_mode == "insert_page" and state.get("copies_backup"):
                    state["copies"] = state["copies_backup"]
                    copies_input.value = state["copies"]
                    state["copies_backup"] = None
                else:
                    raw_copies = "".join(
                        ch for ch in (copies_input.value or "").strip() if ch.isdigit()
                    )
                    if copies_input.value != raw_copies:
                        copies_input.value = raw_copies
                    state["copies"] = raw_copies or state["copies"]
                state["fiery"] = fiery_checkbox.value
                normalize_copies_value(force=False)

            update_ui_state()

        def commit_copies_input(e=None):
            if print_mode_dropdown.value != "insert_page":
                normalize_copies_value(force=True)
            update_ui_state()

        # Controles de configuración
        copies_input = ft.TextField(
            label=t("num_copies"),
            value=state["copies"],
            keyboard_type=ft.KeyboardType.NUMBER,
            width=150,
            disabled=state["print_mode"] == "insert_page" or state["is_processing"],
            border=_input_border(),
            filled=True,
            fill_color=color_design.FONDO_TEXTFIELDS_COLOR,
            color=color_design.TEXTO_COLOR_GENERICO,
            bgcolor=color_design.FONDO_TEXTFIELDS_COLOR,
            label_style=ft.TextStyle(color=color_design.TEXTO_COLOR_GENERICO),
            error=None,
            on_change=save_state_and_update,
            on_blur=commit_copies_input,
            on_submit=commit_copies_input,
        )

        print_mode_dropdown = ft.Dropdown(
            label=t("print_mode"),
            options=[
                ft.dropdown.Option("simplex", t("simplex")),
                ft.dropdown.Option("duplex", t("duplex")),
                ft.dropdown.Option("insert_page", t("insert_page")),
            ],
            value=state["print_mode"],
            width=200,
            border=_input_border(),
            filled=True,
            fill_color=color_design.FONDO_TEXTFIELDS_COLOR,
            color=color_design.DROPDOWN_TEXT_STYLE_COLOR,
            bgcolor=color_design.DROPDOWN_FONDO_MENU_COLOR,
            label_style=ft.TextStyle(color=color_design.DROPDOWN_TEXT_STYLE_COLOR),
            trailing_icon=ft.Icon(
                ft.Icons.ARROW_DROP_DOWN,
                color=color_design.DROPDOWN_TRAILING_ICON_COLOR,
            ),
            on_select=save_state_and_update,
        )

        fiery_checkbox = ft.Checkbox(
            label=t("generate_fiery"),
            value=state["fiery"],
            active_color=color_design.BORDE_TEXTFIELDS_COLOR,
            check_color=color_design.TEXTOS_FASE_1_COLOR,
            label_style=ft.TextStyle(color=color_design.TEXTOS_FASE_1_COLOR, size=14),
            fill_color=color_design.FONDO_TEXTFIELDS_COLOR,
            border_side=ft.BorderSide(1, color_design.BORDE_TEXTFIELDS_COLOR),
            splash_radius=0,
            disabled=state["ui_locked"] or state["is_processing"],
            on_change=save_state_and_update,
        )

        def on_same_file_for_copies_change(e):
            requested = bool(same_file_checkbox.value)
            files_count = len(state["files"])

            if requested and files_count > 1:
                state["same_file_for_copies"] = False
                same_file_checkbox.value = False
                show_warning(t("same_file_requires_one"))
            else:
                state["same_file_for_copies"] = requested

            save_preference("same_file_for_copies", state["same_file_for_copies"])
            update_ui_state()

        same_file_checkbox = ft.Checkbox(
            label=t("same_file_for_copies"),
            value=state["same_file_for_copies"],
            active_color=color_design.BORDE_TEXTFIELDS_COLOR,
            check_color=color_design.TEXTOS_FASE_1_COLOR,
            label_style=ft.TextStyle(color=color_design.TEXTOS_FASE_1_COLOR, size=14),
            fill_color=color_design.FONDO_TEXTFIELDS_COLOR,
            border_side=ft.BorderSide(1, color_design.BORDE_TEXTFIELDS_COLOR),
            splash_radius=0,
            disabled=state["ui_locked"] or state["is_processing"],
            on_change=on_same_file_for_copies_change,
        )

        same_file_row = ft.Container(
            content=ft.Row(
                controls=[same_file_checkbox],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            width=float("inf"),
            padding=ft.Padding.only(top=0, bottom=0),
        )

        _OPT_SAVE_OPTS = [
            dict(garbage=0, deflate=False, clean=False),
            dict(garbage=2, deflate=True, clean=False),
            dict(garbage=4, deflate=True, clean=False),
        ]

        def on_opt_change(e):
            state["optimize_level"] = int(e.control.value)

        opt_radio_group = ft.RadioGroup(
            value=str(state["optimize_level"]),
            on_change=on_opt_change,
            content=ft.Column(
                [
                    ft.Radio(
                        value="0",
                        label=t("opt_no_optimize"),
                        label_style=ft.TextStyle(
                            color=color_design.TEXTOS_FASE_1_COLOR, size=13
                        ),
                        fill_color=color_design.BORDE_TEXTFIELDS_COLOR,
                    ),
                    ft.Radio(
                        value="1",
                        label=t("opt_standard"),
                        label_style=ft.TextStyle(
                            color=color_design.TEXTOS_FASE_1_COLOR, size=13
                        ),
                        fill_color=color_design.BORDE_TEXTFIELDS_COLOR,
                    ),
                    ft.Radio(
                        value="2",
                        label=t("opt_no_duplicates"),
                        label_style=ft.TextStyle(
                            color=color_design.TEXTOS_FASE_1_COLOR, size=13
                        ),
                        fill_color=color_design.BORDE_TEXTFIELDS_COLOR,
                    ),
                ],
                spacing=2,
                tight=True,
            ),
        )

        opt_box = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        t("pdf_optimization"),
                        weight=ft.FontWeight.BOLD,
                        size=13,
                        color=color_design.TEXTO_COLOR_GENERICO,
                    ),
                    opt_radio_group,
                ],
                spacing=4,
                tight=True,
            ),
            border=ft.Border.all(1, color_design.BORDE_TEXTFIELDS_COLOR),
            border_radius=6,
            padding=ft.Padding.all(8),
        )

        copies_fiery_group = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [copies_input, print_mode_dropdown],
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [fiery_checkbox],
                        alignment=ft.MainAxisAlignment.CENTER,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=6,
                tight=True,
            ),
            border=ft.Border.all(1, color_design.BORDE_TEXTFIELDS_COLOR),
            border_radius=6,
            padding=ft.Padding.all(8),
        )

        optimization_row = ft.Container(
            content=ft.Row(
                [copies_fiery_group, opt_box],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            width=float("inf"),
            padding=ft.Padding.only(top=0, bottom=0),
        )

        settings_controls = ft.Column(
            controls=[same_file_row, optimization_row],
            spacing=0,
            tight=True,
        )

        def min_copies_required():
            if print_mode_dropdown.value == "insert_page":
                return 2
            if state["same_file_for_copies"] and len(state["files"]) <= 1:
                return 2
            return max(2, len(state["files"]))

        def refresh_copies_error():
            copies_input.error = None

        def normalize_copies_value(force=False):
            minimum = min_copies_required()

            if print_mode_dropdown.value == "insert_page":
                normalized = "2"
                state["copies"] = normalized
                copies_input.value = normalized
                refresh_copies_error()
                return 2

            raw_value = "".join(
                ch for ch in (copies_input.value or "").strip() if ch.isdigit()
            )
            if copies_input.value != raw_value:
                copies_input.value = raw_value

            if not raw_value:
                state["copies"] = str(minimum)
                if force:
                    copies_input.value = str(minimum)
                refresh_copies_error()
                return minimum

            requested_copies = int(raw_value)
            normalized_int = max(minimum, requested_copies)
            state["copies"] = str(normalized_int)

            if force and requested_copies != normalized_int:
                copies_input.value = str(normalized_int)

            refresh_copies_error()
            return normalized_int

        def expected_files_count():
            if state["workflow_mode"] == "pdf_collector":
                return len(state["files"]) + 1

            if print_mode_dropdown.value == "insert_page":
                return 2

            # En modo archivo único, solo se necesita 1 fuente de datos.
            if state["same_file_for_copies"]:
                return 1

            minimum = min_copies_required()
            raw_value = (copies_input.value or "").strip()
            try:
                requested_copies = int(raw_value)
            except ValueError:
                return minimum
            return max(minimum, requested_copies)

        def effective_copycollector_files():
            if state["workflow_mode"] != "copy_collector":
                return list(state["files"])

            if print_mode_dropdown.value == "insert_page":
                return list(state["files"])

            if not state["same_file_for_copies"]:
                return list(state["files"])

            if len(state["files"]) != 1:
                return list(state["files"])

            try:
                requested_copies = int((copies_input.value or "").strip())
            except Exception:
                requested_copies = 2
            normalized_copies = max(2, requested_copies)
            return [state["files"][0]] * normalized_copies

        # Flet 1.0: FilePicker es un servicio awaitable. pick_files()/save_file()
        # devuelven el resultado directamente (on_result ya no se emite) y
        # allowed_extensions solo filtra si file_type es CUSTOM.
        PDF_FILE_PICK = dict(
            file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf"]
        )

        async def on_file_picked(picked):
            if not picked:
                return

            if state["workflow_mode"] == "pdf_collector":
                for f in picked:
                    try:
                        pages = _get_pdf_page_count(f.path)
                    except Exception:
                        pages = 0
                    state["files"].append(f.path)
                    state["file_pages"].append(pages)
                update_ui_state()
                return

            expected_copies = expected_files_count()
            selected_files = picked
            if state["same_file_for_copies"]:
                selected_files = picked[:1]
                if len(picked) > 1:
                    show_warning(t("same_file_only_first"))

            for f in selected_files:
                if len(state["files"]) >= expected_copies:
                    break

                path = f.path
                temp_list = state["files"] + [path]

                try:
                    is_valid, err_msg, err_args, base_pages_val = validate_files(
                        temp_list, len(temp_list), print_mode_dropdown.value
                    )
                except PdfCollectorError as exc:
                    show_error(t(exc.message_key, *exc.message_args))
                    return

                if not is_valid and err_msg != "missing_files":
                    show_error(t(err_msg, *err_args))
                    return

                state["files"].append(path)
                state["file_pages"] = [base_pages_val] * len(state["files"])

                if len(temp_list) == expected_copies:
                    is_valid, warn_msg, _, _ = validate_files(
                        state["files"], expected_copies, print_mode_dropdown.value
                    )
                    if warn_msg:
                        show_warning(t(warn_msg))

            update_ui_state()

        async def on_add_click(_):
            await on_file_picked(
                await ft.FilePicker().pick_files(allow_multiple=True, **PDF_FILE_PICK)
            )

        async def on_run_click(_):
            if state["ui_locked"] or state["is_processing"]:
                return

            if state["workflow_mode"] == "pdf_collector":
                if len(state["files"]) < 1:
                    show_error(t("missing_files"))
                    return
            else:
                normalize_copies_value(force=True)

            cancel_event.clear()
            state["ui_locked"] = True
            state["is_processing"] = False
            update_ui_state()

            out_path = await ft.FilePicker().save_file(**PDF_FILE_PICK)
            if not out_path:
                cancel_event.clear()
                state["ui_locked"] = False
                state["is_processing"] = False
                update_ui_state()
                return

            if not out_path.lower().endswith(".pdf"):
                out_path += ".pdf"

            state["ui_locked"] = True
            state["is_processing"] = True
            _bp = state["file_pages"][0] if state["file_pages"] else 0
            processing_files = effective_copycollector_files()
            if state["workflow_mode"] == "pdf_collector":
                initial_total_pages = len(state["files"])
            elif print_mode_dropdown.value == "insert_page":
                initial_total_pages = _bp + 1
            else:
                initial_total_pages = _bp * max(1, len(processing_files))
            progress_bar.value = 0
            progress_text.value = (
                f"0/{initial_total_pages}" if initial_total_pages else "0/0"
            )
            update_ui_state()

            await asyncio.to_thread(run_process, out_path)

        def on_cancel_click(_):
            if not state["is_processing"]:
                return
            cancel_event.set()
            progress_text.value = t("cancelling")
            page.update()

        add_btn = ft.Button(
            content=t("add_pdf"),
            icon=ft.Icons.ADD,
            on_click=on_add_click,
            bgcolor=color_design.BOTONES_GENERICOS_FONDO_COLOR,
            style=ft.ButtonStyle(
                color={
                    ft.ControlState.DEFAULT: color_design.BOTONES_GENERICOS_COLOR,
                    ft.ControlState.HOVERED: color_design.BOTONES_GENERICOS_HOVER_COLOR,
                },
                overlay_color=color_design.BOTONES_GENERICOS_OVERLAY_COLOR,
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )

        base_info_text = ft.Text("", color=color_design.TEXTO_COLOR_GENERICO)

        load_row = ft.Row(
            [add_btn, base_info_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        )

        # Tabla Personalizada Constante
        header_row = ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        t("pages"),
                        weight=ft.FontWeight.BOLD,
                        color=color_design.TEXTO_COLOR_GENERICO,
                        width=80,
                    ),
                    ft.Text(
                        t("file_column"),
                        weight=ft.FontWeight.BOLD,
                        color=color_design.TEXTO_COLOR_GENERICO,
                        expand=True,
                    ),
                    ft.Text(
                        t("remove"),
                        weight=ft.FontWeight.BOLD,
                        color=color_design.TEXTO_COLOR_GENERICO,
                        width=80,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ]
            ),
            padding=ft.Padding.only(left=10, right=10, bottom=10, top=5),
            border=ft.Border.only(
                bottom=ft.BorderSide(1, color_design.TEXTO_COLOR_GENERICO)
            ),
        )

        files_list_col = ft.ListView(spacing=8, expand=True)

        table_container = ft.Container(
            content=ft.Column([header_row, files_list_col]),
            border=ft.Border.all(1, color_design.BORDE_TEXTFIELDS_COLOR),
            padding=10,
            border_radius=8,
            bgcolor=color_design.FONDO_SECCIONES,
            expand=True,
        )

        # Progreso y Ejecutar
        progress_bar = ft.ProgressBar(
            width=320,
            visible=False,
            color=color_design.TEXTO_COLOR_GENERICO,
            bgcolor=color_design.FONDO_TEXTFIELDS_COLOR,
        )
        progress_text = ft.Text(
            "",
            visible=False,
            color=color_design.TEXTO_COLOR_GENERICO,
            width=210,
        )

        cancel_btn = ft.Button(
            content=t("cancel"),
            icon=ft.Icons.CANCEL,
            on_click=on_cancel_click,
            visible=state["is_processing"],
            bgcolor=color_design.BOTONES_GENERICOS_FONDO_COLOR,
            style=ft.ButtonStyle(
                color={
                    ft.ControlState.DEFAULT: color_design.BOTONES_GENERICOS_COLOR,
                    ft.ControlState.HOVERED: color_design.BOTONES_GENERICOS_HOVER_COLOR,
                },
                overlay_color=color_design.BOTONES_GENERICOS_OVERLAY_COLOR,
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )

        run_btn = ft.Button(
            content=t("generate_pdf"),
            icon=ft.Icons.PLAY_ARROW,
            on_click=on_run_click,
            disabled=True,
            bgcolor=color_design.BOTONES_GENERICOS_FONDO_COLOR,
            style=ft.ButtonStyle(
                color={
                    ft.ControlState.DEFAULT: color_design.BOTONES_GENERICOS_COLOR,
                    ft.ControlState.HOVERED: color_design.BOTONES_GENERICOS_HOVER_COLOR,
                },
                overlay_color=color_design.BOTONES_GENERICOS_OVERLAY_COLOR,
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )

        progress_row = ft.Row(
            [progress_bar, progress_text],
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )

        buttons_row = ft.Row(
            [cancel_btn, run_btn],
            alignment=ft.MainAxisAlignment.END,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=6,
            tight=True,
        )

        bottom_row = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=progress_row,
                        expand=True,
                        height=64,
                        alignment=ft.Alignment.CENTER_LEFT,
                        margin=ft.Margin.only(right=10),
                    ),
                    ft.Container(
                        content=buttons_row,
                        height=64,
                        alignment=ft.Alignment.CENTER_RIGHT,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
            ),
            height=64,
            alignment=ft.Alignment.CENTER,
        )

        # Funciones de utilidad anidadas a build_ui
        def show_error(msg):
            page.show_dialog(
                ft.SnackBar(
                    ft.Text(
                        f"{t('error')}: {msg}",
                        color=color_design.SNACKBAR_COLOR_TEXTO,
                    ),
                    bgcolor=color_design.SNACKBAR_COLOR_ERROR,
                )
            )

        def show_warning(msg):
            page.show_dialog(
                ft.SnackBar(
                    ft.Text(
                        f"{t('warning')}: {msg}",
                        color=color_design.SNACKBAR_COLOR_TEXTO,
                    ),
                    bgcolor=color_design.SNACKBAR_COLOR_FONDO,
                )
            )

        def show_success(msg):
            page.show_dialog(
                ft.SnackBar(
                    ft.Text(msg, color=color_design.SNACKBAR_COLOR_TEXTO),
                    bgcolor=color_design.SUCCESS_COLOR,
                )
            )

        def remove_file(idx):
            if 0 <= idx < len(state["files"]):
                state["files"].pop(idx)
                if idx < len(state["file_pages"]):
                    state["file_pages"].pop(idx)
                update_ui_state()

        def update_ui_state():
            insert_mode = print_mode_dropdown.value == "insert_page"
            collector_mode = state["workflow_mode"] == "pdf_collector"
            is_processing = state["is_processing"]
            ui_locked = state["ui_locked"]
            files_count = len(state["files"])

            if state["same_file_for_copies"] and files_count > 1:
                state["same_file_for_copies"] = False
                save_preference("same_file_for_copies", False)

            same_file_checkbox.value = state["same_file_for_copies"]
            expected_copies = expected_files_count()

            # Calcular info combinada
            num_files = files_count
            base_pages = state["file_pages"][0] if state["file_pages"] else 0
            if insert_mode:
                if num_files == 0:
                    total_pages = 0
                elif num_files == 1:
                    total_pages = base_pages
                else:
                    total_pages = base_pages + 1
            else:
                total_pages = base_pages * max(1, len(effective_copycollector_files()))

            if num_files > 0:
                if collector_mode:
                    base_info_text.value = f"{t('files_count')}: {num_files}"
                else:
                    base_info_text.value = (
                        f"{t('pages')}: {base_pages} | "
                        f"{t('total_loaded')}: {total_pages} | "
                        f"{t('files_count')}: {num_files}/{expected_copies}"
                    )
            else:
                base_info_text.value = ""

            copies_input.disabled = insert_mode or ui_locked or collector_mode
            copies_input.visible = (not insert_mode) and (not collector_mode)
            same_file_checkbox.visible = (not insert_mode) and (not collector_mode)
            same_file_checkbox.disabled = (
                insert_mode
                or ui_locked
                or collector_mode
                or is_processing
                or files_count > 1
            )
            print_mode_dropdown.visible = not collector_mode
            fiery_checkbox.visible = (not insert_mode) and (not collector_mode)
            fiery_checkbox.disabled = insert_mode or ui_locked or collector_mode
            opt_radio_group.disabled = ui_locked or is_processing
            lang_dropdown.disabled = ui_locked
            theme_btn.disabled = ui_locked
            info_btn.disabled = ui_locked
            mode_copy_text.disabled = ui_locked
            mode_pdf_text.disabled = ui_locked
            is_copy = state["workflow_mode"] == "copy_collector"
            mode_copy_text.style = ft.ButtonStyle(
                color=(
                    color_design.TEXTO_COLOR_GENERICO
                    if is_copy
                    else color_design.DROPDOWN_TEXT_STYLE_COLOR
                ),
                text_style=ft.TextStyle(
                    size=24,
                    weight=ft.FontWeight.BOLD if is_copy else ft.FontWeight.W_400,
                ),
            )
            mode_pdf_text.style = ft.ButtonStyle(
                color=(
                    color_design.TEXTO_COLOR_GENERICO
                    if not is_copy
                    else color_design.DROPDOWN_TEXT_STYLE_COLOR
                ),
                text_style=ft.TextStyle(
                    size=24,
                    weight=ft.FontWeight.BOLD if not is_copy else ft.FontWeight.W_400,
                ),
            )
            # Interceptar siempre la X y delegar la política de cierre en on_window_event.
            page.window.prevent_close = True
            progress_bar.visible = is_processing
            progress_text.visible = is_processing
            if insert_mode and not collector_mode:
                copies_input.value = "2"
                copies_input.error = None
            else:
                refresh_copies_error()

            # Listado de archivos (Tabla)
            files_list_col.controls.clear()
            for i, fpath in enumerate(state["files"]):
                filename = os.path.basename(fpath)
                p = state["file_pages"][i] if i < len(state["file_pages"]) else 0
                if insert_mode:
                    num_pages_str = str(p) if i == 0 else "1"
                else:
                    num_pages_str = str(p) if p else "-"
                files_list_col.controls.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Text(
                                    f"{num_pages_str} {t('page_short')}",
                                    color=color_design.TEXTO_COLOR_GENERICO,
                                    width=80,
                                ),
                                ft.Text(
                                    filename,
                                    color=color_design.TEXTO_COLOR_GENERICO,
                                    expand=True,
                                    tooltip=fpath,
                                ),
                                ft.Container(
                                    ft.IconButton(
                                        ft.Icons.DELETE,
                                        icon_color=color_design.TEXTO_COLOR_GENERICO,
                                        tooltip=t("remove"),
                                        on_click=lambda e, idx=i: remove_file(idx),
                                        disabled=ui_locked,
                                    ),
                                    width=80,
                                    alignment=ft.Alignment.CENTER,
                                ),
                            ]
                        ),
                        padding=ft.Padding.symmetric(horizontal=10, vertical=5),
                        border_radius=5,
                    )
                )

            if collector_mode:
                add_btn.disabled = ui_locked
            else:
                if state["same_file_for_copies"]:
                    add_btn.disabled = ui_locked or num_files >= 1
                else:
                    add_btn.disabled = (
                        ui_locked or num_files >= expected_copies or expected_copies < 2
                    )
            cancel_btn.visible = is_processing
            cancel_btn.disabled = not is_processing
            if collector_mode:
                run_btn.disabled = ui_locked or num_files < 1
            else:
                if state["same_file_for_copies"]:
                    run_btn.disabled = ui_locked or num_files < 1
                else:
                    run_btn.disabled = (
                        ui_locked or num_files != expected_copies or expected_copies < 2
                    )
            print_mode_dropdown.disabled = ui_locked or num_files > 0 or collector_mode
            page.update()

        def run_process(output_path):
            # Flet 1.0: el worker corre fuera del event loop, asi que cualquier
            # escritura en controles se encola con call_soon_threadsafe.
            loop = page.loop
            collector_mode = state["workflow_mode"] == "pdf_collector"
            mode = "collector" if collector_mode else print_mode_dropdown.value
            gen_fiery = (
                (not collector_mode) and fiery_checkbox.value and mode != "insert_page"
            )
            copies = int(copies_input.value or "0")
            save_opts = _OPT_SAVE_OPTS[state["optimize_level"]]
            progress_state = {
                "last_pages": -1,
                "last_phase": None,
                "saving_started": False,
            }
            processing_files = (
                state["files"] if collector_mode else effective_copycollector_files()
            )

            def on_progress(
                pages_done,
                total_pages,
                phase_key="progress_generating",
                step_done=None,
                step_total=None,
            ):
                def _paint():
                    if cancel_event.is_set():
                        progress_bar.value = None
                        progress_text.value = t("cancelling")
                    elif phase_key == "progress_saving":
                        progress_state["saving_started"] = True
                        progress_bar.value = None
                        progress_text.value = t("progress_saving")
                    elif phase_key == "progress_flushing":
                        if step_done is not None and step_total:
                            progress_bar.value = step_done / step_total
                        else:
                            progress_bar.value = None
                        progress_text.value = t("progress_flushing")
                    elif phase_key == "progress_merging":
                        if step_done is not None and step_total:
                            progress_bar.value = step_done / step_total
                        else:
                            progress_bar.value = None
                        progress_text.value = t("progress_merging")
                    elif progress_state["saving_started"]:
                        progress_bar.value = None
                        progress_text.value = t("progress_saving")
                    else:
                        if total_pages:
                            progress_bar.value = pages_done / total_pages
                        elif step_done is not None and step_total:
                            progress_bar.value = step_done / step_total
                        progress_text.value = f"{pages_done}/{total_pages}"
                    page.update()

                pages_changed = pages_done != progress_state["last_pages"]
                phase_changed = phase_key != progress_state["last_phase"]
                progress_state["last_pages"] = pages_done
                progress_state["last_phase"] = phase_key

                if step_done is None or step_total is None:
                    loop.call_soon_threadsafe(_paint)
                    return

                if (
                    phase_changed
                    or pages_changed
                    or step_done % max(1, step_total // 20) == 0
                    or step_done == step_total
                ):
                    loop.call_soon_threadsafe(_paint)

            try:
                final_pages_per_copy = merge_pdfs(
                    processing_files,
                    output_path,
                    mode,
                    on_progress,
                    cancel_event,
                    save_opts=save_opts,
                )
                if gen_fiery:
                    fiery_path = os.path.splitext(output_path)[0] + "_Fiery.txt"
                    generate_fiery_info(
                        copies, mode, final_pages_per_copy, fiery_path, state["lang"]
                    )
                loop.call_soon_threadsafe(finish_process, True, gen_fiery)
            except PdfCollectorError as exc:
                if exc.message_key == "process_cancelled":
                    logger.info("Proceso cancelado por el usuario: %s", output_path)
                    loop.call_soon_threadsafe(
                        finish_process,
                        False,
                        t(exc.message_key, *exc.message_args),
                        cancelled=True,
                    )
                else:
                    logger.exception(
                        "Error de validacion/procesado PDF: %s", output_path
                    )
                    loop.call_soon_threadsafe(
                        finish_process, False, t(exc.message_key, *exc.message_args)
                    )
            except Exception as e:
                logger.exception("Error al generar PDF combinado: %s", output_path)
                loop.call_soon_threadsafe(finish_process, False, str(e))

        def finish_process(success, extra=None, cancelled=False):
            cancel_event.clear()
            state["is_processing"] = False
            state["ui_locked"] = False
            progress_bar.visible = False
            progress_text.visible = False
            update_ui_state()
            if success:
                show_success(t("pdf_saved"))
                if extra:
                    show_success(t("fiery_saved"))
            elif cancelled:
                show_warning(str(extra))
            else:
                show_error(str(extra))

        # Layout general
        container = ft.Container(
            content=ft.Column(
                [
                    top_row,
                    ft.Divider(color=color_design.TEXTO_COLOR_GENERICO, height=1),
                    ft.Text(
                        t("settings"),
                        weight=ft.FontWeight.BOLD,
                        color=color_design.TEXTO_COLOR_GENERICO,
                    ),
                    settings_controls,
                    ft.Divider(color=color_design.TEXTO_COLOR_GENERICO, height=1),
                    ft.Row(
                        [
                            ft.Text(
                                t("files_section"),
                                weight=ft.FontWeight.BOLD,
                                color=color_design.TEXTO_COLOR_GENERICO,
                            ),
                            load_row,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    table_container,
                    ft.Divider(color=color_design.TEXTO_COLOR_GENERICO, height=1),
                    bottom_row,
                ],
                spacing=15,
            ),
            padding=25,
            bgcolor=color_design.FONDO_FASE_1,
            border_radius=12,
            expand=True,
        )

        page.add(container)
        update_ui_state()

    # Construir UI inicial
    build_ui()


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    assets_path = os.path.join(base_dir, "assets")
    _heal_flt_client_cache()
    _brand_and_set_client_icon()
    ft.run(main, assets_dir=assets_path)