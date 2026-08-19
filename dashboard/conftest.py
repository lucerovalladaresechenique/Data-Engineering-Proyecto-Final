"""
Asegura que el paquete `app/` sea importable al correr pytest, incluso si
pytest detecta un pyproject.toml/rootdir distinto en una carpeta padre
(por ejemplo, si este proyecto vive dentro de otro repo, como
Proyecto_Lucero/dashboard/).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
