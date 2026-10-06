# PdfCopyCollector

PdfCopyCollector recopila las páginas de varios archivos o usa las páginas de un mismo archivo PDF para generar un nuevo archivo PDF, ordenando las páginas según sean a una cara o a doble cara, y generando un archivo de configuración de cajones de papel para poder imprimir cada copia en un cajón diferente en máquinas digitales (en este caso para Fiery Command WorkStation). En el caso de usar un solo archivo, las páginas se duplicarán automáticamente.

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