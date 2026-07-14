FROM python:3.11-slim

# Build tools kept in the image (not just build stage) because a couple of
# requirements (e.g. the `jq` binding) may fall back to compiling from
# source if no prebuilt wheel matches your platform/architecture.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    autoconf \
    automake \
    libtool \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

# Default = production-style run (no reload). The dev compose file
# overrides this command to add --reload and mounts the source as a volume.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
