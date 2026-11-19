FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Installed before copying the code, so this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# The admin's static files, served by WhiteNoise. collectstatic only copies files, but it loads the
# settings, so the required ones get throwaway values here; the real ones come at run time.
RUN SECRET_KEY=build CORE_SERVICE_TOKEN=build ALLOWED_HOSTS=localhost \
    DATABASE_URL=sqlite:////tmp/build.db REDIS_URL=redis://localhost:6379/0 \
    JWT_PRIVATE_KEY_PATH=/dev/null JWT_PUBLIC_KEY_PATH=/dev/null \
    MINIO_INTERNAL_URL=http://localhost MINIO_PUBLIC_URL=http://localhost \
    MINIO_ACCESS_KEY=build MINIO_SECRET_KEY=build MINIO_BUCKET=build \
    python manage.py collectstatic --noinput

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
