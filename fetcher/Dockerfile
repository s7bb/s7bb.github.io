FROM python:3.12-slim

# git required at runtime: GitPython shells out to the git binary
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir .

CMD ["s7bb-service"]
