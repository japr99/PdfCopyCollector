# PdfCopyCollector

PdfCopyCollector es un software para **juntar, ordenar y separar páginas de PDF**: reúne
varios PDF en uno solo, reordena las páginas a tu gusto y permite eliminar las que no
quieras, sin complicaciones.

Interfaz gráfica con **Flet 1.0.1** (Flutter embebido) y Python **3.14**.

🌐 **Web y descargas**: <https://japr.my.canva.site/talnumstack-pagenumber-es>

## Requisitos

- Python 3.14
- Un `venv` propio en la raíz del repo

## Dependencias

```bash
pip install -r requirements.txt            # Windows
pip install -r requirements-mac.txt        # macOS
```

## Ejecutar

```bash
python main.py
```

En la aplicación se añaden los PDF de origen, se ordenan o eliminan sus páginas y se genera
el PDF de salida.

## Estructura

| Ruta | Contenido |
| --- | --- |
| `main.py` | Punto de entrada y lógica principal de la interfaz |
| `pdf_merger.py` | Unión y reordenación de páginas de PDF |
| `fiery_export.py` | Generación del PDF de información para Fiery |
| `preferences.py` | Preferencias y configuración persistente |
| `lang.py` | Textos de la interfaz en español, inglés y catalán |
| `color_design.py` | Paleta de colores de la aplicación |
| `assets/` | Iconos de la aplicación |

## Licencia

Copyright © 2026 japr99

AGPL-3.0 — GNU Affero General Public License versión 3. Ver el fichero `LICENSE`.

Este programa es software libre: puedes redistribuirlo y/o modificarlo bajo los términos de la
Licencia Pública General Affero de GNU (AGPL), versión 3. Se distribuye **SIN NINGUNA GARANTÍA**;
consulta la licencia en <https://www.gnu.org/licenses/agpl-3.0.html>.