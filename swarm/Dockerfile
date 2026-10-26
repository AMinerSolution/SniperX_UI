# DPX swarm API. Build context: this directory (swarm/).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SWARM_DB=/data/swarm.db SWARM_API_HOST=0.0.0.0 SWARM_API_PORT=8000

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY swarm ./swarm

# Non-root; /data holds the SQLite memory + LangGraph checkpoints and MUST be a persistent volume.
RUN useradd --system --uid 10001 swarm && mkdir /data && chown swarm /data
USER swarm
VOLUME /data
EXPOSE 8000

# /health needs the bearer token, so the check sends it. The API refuses to start without SWARM_API_TOKEN.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import os,urllib.request as u; u.urlopen(u.Request('http://127.0.0.1:8000/health', headers={'Authorization': 'Bearer ' + os.environ['SWARM_API_TOKEN']}))"

# One process only: state is SQLite + an in-process write lock. Do not add --workers.
CMD ["python", "-m", "swarm.api"]
