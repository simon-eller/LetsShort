FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=bot.py

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /LetsShort

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked

ADD . /LetsShort

CMD ["uv", "run", "gunicorn", "--config", "gunicorn-cfg.py", "bot:server"]
