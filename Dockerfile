# Evals Workbench — single container: FastAPI serves the API and the built React app on $PORT.
# Build:  docker build -t evals-workbench .
# Demo:   docker run -p 8000:8000 -e DEMO_MODE=1 evals-workbench
# Private: docker run -p 8000:8000 -e APP_PASSWORD=... -e LLM_MODE=live -e ANTHROPIC_API_KEY=... -v evals-data:/data evals-workbench

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx vite build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    EVALS_DB=sqlite:////data/evals_workbench.db \
    PORT=8000
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /web/dist frontend/dist
RUN mkdir -p /data && useradd -m app && chown -R app /data /app
USER app
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz')"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
