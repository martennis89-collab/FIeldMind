FROM python:3.11-slim

# Build tools kept in the image (not just build stage) because a couple of
# requirements (e.g. the `jq` binding) may fall back to compiling from
# source if no prebuilt wheel matches your platform/architecture.
# fonts-liberation: python:3.11-slim ships NO TTF fonts, so reportlab fell
# back to Helvetica and rendered every Cyrillic character in the exported
# reimbursement PDF as a black square. _register_pdf_font() looks for
# LiberationSans here (DejaVu is its fallback); without this package the
# whole Cyrillic-font path is dead code.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    autoconf \
    automake \
    libtool \
    pkg-config \
    curl \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

# Default = production-style run (no reload). The dev compose file
# overrides this command to add --reload and mounts the source as a volume.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
