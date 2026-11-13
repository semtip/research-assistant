# Stage 1: build the React frontend
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
COPY data/ /app/data/
RUN npm run build

# Stage 2: Python API that also serves the built frontend at /koos
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYDANTIC_AI_NO_BANNER=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "uvicorn[standard]==0.54.0"
COPY backend/ backend/
COPY --from=frontend /app/frontend/dist frontend/dist
RUN useradd --create-home app
USER app
EXPOSE 8080
# The API key comes from the environment at runtime, never from the image.
CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
