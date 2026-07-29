# Lean API image — no heavy parsing/OCR deps.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# pyproject.toml declares `packages = ["app"]` (a local package, not just a
# dependency list) — `pip install .` needs app/ present on disk, so the
# source must be copied in BEFORE installing, not after.
COPY . .
RUN pip install --upgrade pip && pip install .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
