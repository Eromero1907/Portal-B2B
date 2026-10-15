# Imagen de una instancia del monolito modular (Portal B2B · Entregable 3)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY portal ./portal
EXPOSE 8000
# Un proceso por contenedor: cada contenedor es una "instancia" (app1, app2, app3) detrás de nginx.
CMD ["uvicorn", "portal.principal:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
