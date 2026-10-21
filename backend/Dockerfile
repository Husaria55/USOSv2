FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/venv PATH="/venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
EXPOSE 8000
# Kilka procesów uvicorn (WEB_CONCURRENCY): wąskim gardłem przy szczycie jest CPU Pythona,
# nie baza. Każdy proces ma własną pulę połączeń (USOS_DB_POOL_SIZE + USOS_DB_MAX_OVERFLOW).
ENV WEB_CONCURRENCY=8
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers $WEB_CONCURRENCY --no-access-log"]
