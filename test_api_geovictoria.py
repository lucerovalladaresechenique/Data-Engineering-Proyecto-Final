"""
test_api_geovictoria.py — Prueba rápida de conexión a la API de GeoVictoria.
Solo hace login y confirma que el token llegue bien, sin tocar el pipeline completo.

Uso:
    python test_api_geovictoria.py
"""
import os
from dotenv import load_dotenv

load_dotenv()

from src.extract.api_extractor import GeoVictoriaAPIExtractor

base_url = os.getenv("GEOVICTORIA_BASE_URL")
api_key = os.getenv("GEOVICTORIA_API_KEY")
api_secret = os.getenv("GEOVICTORIA_API_SECRET")

print(f"Probando conexión a: {base_url}")

if not (base_url and api_key and api_secret):
    print("❌ Faltan variables en tu .env (GEOVICTORIA_BASE_URL / GEOVICTORIA_API_KEY / GEOVICTORIA_API_SECRET)")
else:
    extractor = GeoVictoriaAPIExtractor(base_url=base_url, api_key=api_key, api_secret=api_secret)
    try:
        token = extractor.login()
        print(f"✓ Login exitoso. Token (primeros 15 caracteres): {token[:15]}...")
    except Exception as e:
        print(f"❌ Error al conectar: {e}")