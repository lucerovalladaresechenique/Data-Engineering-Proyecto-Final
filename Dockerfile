# Imagen del pipeline de Control de Asistencia (Sesión 2 Python Certified Data Engineer)
# Diseñada para correr en Cloud Run Job (Linux), pero funciona igual en cualquier
# servidor Linux con Docker instalado — cumple el requisito de "probar en Linux".

FROM python:3.12-slim

WORKDIR /app

# Instala dependencias primero (aprovecha el cache de capas de Docker: si el
# código cambia pero requirements.txt no, esta capa no se reconstruye).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto del proyecto (código, empleados.txt, data_samples si existen).
COPY . .

# En Cloud Run, las credenciales de GCP vienen de la cuenta de servicio adjunta
# al servicio (Application Default Credentials) — NO se hornea ningún JSON de
# credenciales dentro de la imagen por seguridad. Para pruebas locales con
# Docker, se monta el archivo y se pasa GOOGLE_APPLICATION_CREDENTIALS por
# variable de entorno al correr `docker run` (ver README).
ENV CLOUD_PROVIDER=gcp
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "run_daily.py"]
