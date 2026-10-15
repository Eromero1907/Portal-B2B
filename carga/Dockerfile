# Herramientas del Entregable 3: generador de carga y pruebas de aceptación de la plataforma.
# Corre dentro de la red de Docker (habla con nginx y con la BD por nombre de servicio).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# El código se monta en /workspace (docker-compose.yml): no hace falta reconstruir la imagen al editarlo.
