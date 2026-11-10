FROM python:3.12-slim

# fping: main probe engine (one process, many targets). mtr: evidence on incidents.
# iputils-ping: fallback prober. iproute2: route/addr discovery. iw: Wi-Fi signal (optional).
RUN apt-get update \
 && apt-get install -y --no-install-recommends fping mtr-tiny iputils-ping iproute2 iw ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ISITMYISP_DATA=/data

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY isitmyisp ./isitmyisp
RUN pip install --no-cache-dir .

VOLUME ["/data"]
# Needs host networking to see your real gateway and path:
#   docker run --rm --net=host --cap-add=NET_RAW ghcr.io/<user>/isitmyisp status
ENTRYPOINT ["isitmyisp"]
CMD ["monitor"]
