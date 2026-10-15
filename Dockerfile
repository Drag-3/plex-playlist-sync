FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt
COPY pps /app/pps

CMD ["python", "-m", "pps.run"]



#docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 -t rnagabhyrava/plexplaylistsync:<tag> --push .