# Stub propio del servicio externo de crédito/tributación
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY stub_credito.py fallas.py .
RUN mkdir -p /srv/faults

EXPOSE 9000
CMD ["uvicorn", "stub_credito:app", "--host", "0.0.0.0", "--port", "9000", "--no-access-log"]
