FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /uvx /bin/

WORKDIR /code

COPY pyproject.toml uv.lock /code/
RUN uv sync --locked --no-dev --no-install-project

COPY . /code/
RUN mkdir -p /code/media /code/staticfiles \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /code

WORKDIR /code/app
USER appuser

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
