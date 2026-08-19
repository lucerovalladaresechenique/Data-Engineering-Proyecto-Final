"""
Punto de entrada para ejecutar la app localmente:

    python run.py

Equivalente a:

    streamlit run app/main.py
"""

import sys
from streamlit.web import cli as stcli

if __name__ == "__main__":
    sys.argv = ["streamlit", "run", "app/main.py"]
    sys.exit(stcli.main())
