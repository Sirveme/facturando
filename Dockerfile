FROM python:3.12-slim-bookworm

# Variables de entorno
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Directorio de trabajo
WORKDIR /app

# Copiar requirements primero (mejor cache)
COPY requirements.txt .

# Instalar dependencias Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Puerto por defecto
ENV PORT=8080
EXPOSE 8080

# Comando - usar shell form para que interprete $PORT
CMD uvicorn src.main:app --host 0.0.0.0 --port $PORT
