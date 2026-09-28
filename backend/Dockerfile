FROM ghcr.io/astral-sh/uv:0.11.25 AS uv

FROM python:3.12-slim
COPY --from=uv /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY app ./app
RUN uv sync --frozen --no-dev
EXPOSE 8109
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8109"]
