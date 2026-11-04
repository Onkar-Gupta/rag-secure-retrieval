FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY pyproject.toml README.md ./
COPY rag_secure ./rag_secure
RUN pip install .

COPY config.yaml ./
COPY eval/users.yaml ./eval/users.yaml
COPY data/docs ./data/docs

# Inside the container: listen on every interface, and reach Ollama on the host machine.
RUN sed -i 's/^host: .*/host: 0.0.0.0/; s#^ollama_url: .*#ollama_url: http://host.docker.internal:11434#' config.yaml \
    && grep -q '^host: 0.0.0.0' config.yaml && grep -q 'host.docker.internal' config.yaml \
    && chown -R app:app /app

USER app
# Fetch the embedding model now, so the container needs no internet when it starts.
RUN for i in 1 2 3; do       python -c "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction as D; D()(['warm up'])" && exit 0;       echo "download failed, retrying"; sleep 5;     done; exit 1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["sh", "-c", "rag ingest && rag serve"]
