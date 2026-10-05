import datetime
import os

from lang import get_text


def generate_fiery_info(
    num_copies: int,
    mode: str,
    num_pages_per_file: int,
    output_path: str,
    lang_code: str = "es",
):
    """
    Genera el archivo de instrucciones Fiery para las impresoras Xerox.

    :param num_copies: Número de copias / archivos utilizados.
    :param mode: 'simplex' (Una cara) o 'duplex' (Doble cara).
    :param num_pages_per_file: Número de páginas del archivo de referencia.
    :param output_path: Ruta donde guardar el archivo de texto.
    """
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t = lambda key, *args: get_text(lang_code, key, *args)
    modo_str = t("fiery_mode_simplex") if mode == "simplex" else t("fiery_mode_duplex")

    lines = []
    lines.append(f"# {t('fiery_header', now)}")
    lines.append(f"# {t('fiery_mode')}: {modo_str}")
    lines.append(f"# {t('fiery_trays')}: {num_copies}")
    lines.append(f"# {t('fiery_apply_groups')}")
    lines.append("")

    for c in range(1, num_copies + 1):
        lines.append(f"{t('fiery_copy')} {c}:")
        page_list = []

        if mode == "simplex":
            # Simplex: 1 página por archivo en cada iteración
            for p in range(num_pages_per_file):
                page_num = c + p * num_copies
                page_list.append(str(page_num))
        else:
            # Duplex: 2 páginas por archivo en cada iteración
            # Note: Si num_pages_per_file es impar, se asume que se rellenó con blank en el PDF
            # Pero el cálculo de páginas Fiery asume la estructura del PDF final (par)
            total_blocks = (num_pages_per_file + 1) // 2
            for k in range(total_blocks):
                p1 = k * 2 * num_copies + 2 * (c - 1) + 1
                p2 = k * 2 * num_copies + 2 * (c - 1) + 2
                page_list.append(str(p1))
                page_list.append(str(p2))

        lines.append(",".join(page_list))
        lines.append("")

    # Escribimos el txt
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
