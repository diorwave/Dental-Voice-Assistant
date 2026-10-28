FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Collect static files at build time (served by WhiteNoise). The throwaway key
# only exists for this build step; the runtime SECRET_KEY comes from the env.
RUN SECRET_KEY=collectstatic-build-only python manage.py collectstatic --noinput

RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

EXPOSE 8000

# Apply reviewed, committed migrations (never generate them at runtime) and
# serve with gunicorn. Tune with WEB_CONCURRENCY / GUNICORN_TIMEOUT / PORT.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn receptionist_project.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-3} --timeout ${GUNICORN_TIMEOUT:-30} --access-logfile -"]
