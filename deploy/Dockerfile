FROM python:3.12-slim-bookworm
WORKDIR /srv/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt playwright==1.57.0 \
    && python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONPATH=/srv/app:/srv/app/core/server PYTHONUNBUFFERED=1
COPY . .
