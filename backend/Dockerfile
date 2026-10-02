FROM ghcr.io/astral-sh/uv:0.11.25 AS uv

FROM python:3.12-slim
COPY --from=uv /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY deploy ./deploy
RUN uv sync --frozen --no-dev
RUN groupadd --system sqlchat && useradd --system --gid sqlchat --create-home --home-dir /home/sqlchat sqlchat \
    && mkdir -p /app/uploads /var/lib/sqlchat/prometheus/api /var/lib/sqlchat/prometheus/worker \
    && chown -R sqlchat:sqlchat /app/uploads /var/lib/sqlchat/prometheus
USER sqlchat:sqlchat
EXPOSE 8109
ENTRYPOINT ["python", "deploy/connection_env.py"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8109"]
