# Stage 1: build the admin web UI
FROM node:22-slim AS ui
WORKDIR /ui
COPY web-ui/package.json web-ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web-ui/ ./
RUN npm run build

# Stage 2: Python app
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN pip install -r requirements.lock
COPY src ./src
COPY data_static ./data_static
RUN pip install --no-deps -e .
COPY --from=ui /ui/dist ./web-ui/dist
EXPOSE 8000
CMD ["sh", "-c", "python -m stockbot --host 0.0.0.0 --port ${PORT:-8000}"]
