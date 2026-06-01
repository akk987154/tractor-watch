FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir hatchling && \
    pip install --no-cache-dir --target=/deps httpx selectolax rich plotly pydantic pydantic-settings loguru fastapi uvicorn jinja2

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /deps /usr/local/lib/python3.12/site-packages
COPY src/ src/
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .
CMD ["tractor-watch", "track"]
