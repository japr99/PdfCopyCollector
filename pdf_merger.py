import logging
import math
import shutil
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
from preferences import get_config_dir

logger = logging.getLogger(__name__)


BATCH_SIZE = 20


class PdfCollectorError(Exception):
    def __init__(self, message_key, *message_args):
        self.message_key = message_key
        self.message_args = list(message_args)
        super().__init__(message_args[0] if message_args else message_key)


def _resolve_save_options(save_opts):
    """Normaliza opciones de guardado para mantener tipos estables."""
    opts = save_opts if isinstance(save_opts, dict) else {}

    try:
        garbage = int(opts.get("garbage", 4))
    except Exception:
        garbage = 4

    deflate = bool(opts.get("deflate", True))
    clean = bool(opts.get("clean", False))
    return garbage, deflate, clean


def _get_pdf_page_count(file_path):
    try:
        with fitz.open(file_path) as doc:
            return len(doc)
    except Exception as exc:
        logger.exception("No se pudo leer el PDF: %s", file_path)
        raise PdfCollectorError("error", str(exc)) from exc


def validate_files(file_paths, expected_copies, print_mode):
    """
    Valida la lista de archivos PDF antes de procesar.
    Retorna (es_valido, mensaje_error_llave, args, num_paginas).
    """
    if len(file_paths) != expected_copies:
        return False, "missing_files", [], 0

    if not file_paths:
        return False, "missing_files", [], 0

    base_pages = _get_pdf_page_count(file_paths[0])

    if print_mode == "insert_page":
        if len(file_paths) >= 2:
            insert_pages = _get_pdf_page_count(file_paths[1])
            if insert_pages != 1:
                return False, "insert_source_one_page", [insert_pages], 0
        return True, None, [], base_pages

    # Verificar el resto de archivos
    for file_path in file_paths[1:]:
        if _get_pdf_page_count(file_path) != base_pages:
            return False, "different_pages", [base_pages], 0

    # Para Duplex, advertir si es impar
    # No es un error bloqueante, pero se debe notificar
    warning = None
    if print_mode == "duplex" and base_pages % 2 != 0:
        warning = "duplex_odd_pages"

    return True, warning, [], base_pages


def merge_pdfs(
    file_paths,
    output_path,
    print_mode,
    progress_callback=None,
    cancel_event=None,
    save_opts=None,
):
    """
    Combina los PDFs de manera intercalada.

    Se usa show_pdf_page para copiar cada página como contenido PDF nativo.
    DocumentWriter no es válido aquí con Page.run en PyMuPDF 1.27.x.
    """
    if not file_paths:
        raise ValueError("No files provided.")

    if print_mode == "collector":
        final_doc = fitz.open()
        try:
            total_ops = len(file_paths)
            for idx, pdf_path in enumerate(file_paths, start=1):
                if cancel_event and cancel_event.is_set():
                    raise PdfCollectorError("process_cancelled")

                src = fitz.open(pdf_path)
                try:
                    final_doc.insert_pdf(src)
                finally:
                    src.close()

                if progress_callback:
                    progress_callback(
                        idx,
                        total_ops,
                        "progress_generating",
                        idx,
                        total_ops + 1,
                    )

            if cancel_event and cancel_event.is_set():
                raise PdfCollectorError("process_cancelled")

            garbage, deflate, clean = _resolve_save_options(save_opts)
            if progress_callback:
                progress_callback(
                    total_ops,
                    total_ops,
                    "progress_saving",
                    total_ops + 1,
                    total_ops + 1,
                )
            if garbage >= 2:
                try:
                    final_doc.subset_fonts()
                except Exception as exc:
                    logger.warning("[MERGE][WARN] subset_fonts falló: %s", exc)
            final_doc.save(output_path, garbage=garbage, deflate=deflate, clean=clean)

            return final_doc.page_count
        finally:
            final_doc.close()
            fitz.TOOLS.store_shrink(100)

    num_copies = len(file_paths)
    docs = []
    out_doc = None
    temp_dir = None
    batch_files = []

    def report_progress(done_pages, total_pages, phase_key, done_steps, total_steps):
        if progress_callback:
            progress_callback(
                done_pages, total_pages, phase_key, done_steps, total_steps
            )

    def check_cancelled():
        if cancel_event and cancel_event.is_set():
            raise PdfCollectorError("process_cancelled")

    try:
        docs = [fitz.open(fp) for fp in file_paths]
        check_cancelled()
        num_pages = len(docs[0])

        if print_mode == "insert_page":
            if len(docs) != 2:
                raise PdfCollectorError("missing_files")

            master_doc = docs[0]
            insert_doc = docs[1]
            insert_pages = len(insert_doc)
            if insert_pages != 1:
                raise PdfCollectorError("insert_source_one_page", insert_pages)

            num_pages = len(master_doc)
            logical_pages = num_pages
            total_ops = num_pages * 2
        elif print_mode == "simplex":
            logical_pages = num_pages
            total_ops = num_pages * num_copies
        else:
            logical_pages = num_pages if num_pages % 2 == 0 else num_pages + 1
            total_ops = logical_pages * num_copies

        total_batches = max(1, math.ceil(total_ops / BATCH_SIZE))
        total_steps = total_ops + (total_batches * 2) + 1
        current_step = 0
        current_pages = 0
        current_batch_pages = 0
        batch_index = 0
        show_saving_before_last_page = (
            save_opts is not None and save_opts.get("garbage", 0) >= 4 and total_ops > 1
        )

        temp_base = get_config_dir() / "temp"
        try:
            temp_base.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning("No se pudo crear temp_base en config_dir: %s", e)
            temp_base = None

        if temp_base and temp_base.exists():
            temp_dir = Path(
                tempfile.mkdtemp(prefix="copy_collect_batches_", dir=str(temp_base))
            )
        else:
            temp_dir = Path(tempfile.mkdtemp(prefix="copy_collect_batches_"))

        out_doc = fitz.open()

        def flush_batch(force=False):
            nonlocal out_doc, current_batch_pages, batch_index, current_step
            check_cancelled()
            if out_doc is None or out_doc.page_count == 0:
                return
            if not force and current_batch_pages < BATCH_SIZE:
                return

            batch_path = temp_dir / f"batch_{batch_index:04d}.pdf"
            out_doc.save(str(batch_path), garbage=1, deflate=True, clean=False)
            out_doc.close()
            out_doc = None
            fitz.TOOLS.store_shrink(100)
            batch_files.append(batch_path)
            batch_index += 1
            current_batch_pages = 0
            current_step += 1
            report_progress(
                current_pages,
                total_ops,
                "progress_flushing",
                current_step,
                total_steps,
            )
            out_doc = fitz.open()

        def append_source_page(doc, page_index):
            nonlocal current_step, current_pages, current_batch_pages
            check_cancelled()
            if out_doc is None:
                raise PdfCollectorError("error", "Documento de salida no inicializado.")
            if show_saving_before_last_page and current_pages == total_ops - 1:
                report_progress(
                    current_pages,
                    total_ops,
                    "progress_saving",
                    current_step,
                    total_steps,
                )
            src_page = doc[page_index]
            out_page = out_doc.new_page(
                width=src_page.rect.width,
                height=src_page.rect.height,
            )
            out_page.show_pdf_page(out_page.rect, doc, page_index)
            # Preservar las cajas del original (TrimBox/BleedBox/ArtBox/CropBox).
            # new_page solo fija MediaBox; sin esto se pierden trim/sangre en la salida.
            _dx, _dy = src_page.rect.x0, src_page.rect.y0
            for _name in ("trimbox", "bleedbox", "artbox", "cropbox"):
                _box = getattr(src_page, _name, None)
                if _box:
                    getattr(out_page, "set_" + _name)(
                        fitz.Rect(
                            _box.x0 - _dx,
                            _box.y0 - _dy,
                            _box.x1 - _dx,
                            _box.y1 - _dy,
                        )
                    )
            current_batch_pages += 1
            current_pages += 1
            current_step += 1
            report_progress(
                current_pages,
                total_ops,
                "progress_generating",
                current_step,
                total_steps,
            )
            flush_batch()

        def append_blank_page(width, height):
            nonlocal current_step, current_pages, current_batch_pages
            check_cancelled()
            if out_doc is None:
                raise PdfCollectorError("error", "Documento de salida no inicializado.")
            if show_saving_before_last_page and current_pages == total_ops - 1:
                report_progress(
                    current_pages,
                    total_ops,
                    "progress_saving",
                    current_step,
                    total_steps,
                )
            out_doc.new_page(width=width, height=height)
            current_batch_pages += 1
            current_pages += 1
            current_step += 1
            report_progress(
                current_pages,
                total_ops,
                "progress_generating",
                current_step,
                total_steps,
            )
            flush_batch()

        if print_mode == "insert_page":
            for p_idx in range(num_pages):
                check_cancelled()
                append_source_page(master_doc, p_idx)
                append_source_page(insert_doc, 0)

        elif print_mode == "simplex":
            for p_idx in range(num_pages):
                check_cancelled()
                for doc in docs:
                    append_source_page(doc, p_idx)

        elif print_mode == "duplex":
            num_blocks = logical_pages // 2
            for b_idx in range(num_blocks):
                check_cancelled()
                p1_idx = b_idx * 2
                p2_idx = b_idx * 2 + 1

                for doc in docs:
                    # Primera página del bloque
                    page1 = doc[p1_idx]
                    append_source_page(doc, p1_idx)

                    # Segunda página del bloque
                    if p2_idx < num_pages:
                        append_source_page(doc, p2_idx)
                    else:
                        # Página en blanco del mismo tamaño que p1
                        append_blank_page(page1.rect.width, page1.rect.height)

        flush_batch(force=True)
        if out_doc is not None:
            out_doc.close()
            out_doc = None

        final_doc = fitz.open()
        try:
            for batch_path in batch_files:
                check_cancelled()
                src = fitz.open(str(batch_path))
                try:
                    final_doc.insert_pdf(src)
                finally:
                    src.close()
                current_step += 1
                report_progress(
                    current_pages,
                    total_ops,
                    "progress_merging",
                    current_step,
                    total_steps,
                )

            check_cancelled()
            garbage, deflate, clean = _resolve_save_options(save_opts)
            current_step += 1
            report_progress(
                current_pages,
                total_ops,
                "progress_saving",
                current_step,
                total_steps,
            )
            if garbage >= 2:
                try:
                    final_doc.subset_fonts()
                except Exception as exc:
                    logger.warning("[MERGE][WARN] subset_fonts falló: %s", exc)
            final_doc.save(output_path, garbage=garbage, deflate=deflate, clean=clean)
        finally:
            final_doc.close()
            fitz.TOOLS.store_shrink(100)

        return logical_pages

    finally:
        if out_doc:
            out_doc.close()
        if temp_dir:
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                logger.warning(
                    "No se pudo eliminar el directorio temporal: %s", temp_dir
                )
        for doc in docs:
            doc.close()
