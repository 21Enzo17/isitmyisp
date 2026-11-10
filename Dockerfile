FROM python:3.12-slim

# fping: main probe engine (one process, many targets). mtr: evidence on incidents.
# iputils-ping: fallback prober. iproute2: route/addr discovery. iw: Wi-Fi signal (optional).
# libpango + fonts: PDF reports via WeasyPrint. tzdata: local times in reports (set TZ).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      fping mtr-tiny iputils-ping iproute2 iw ca-certificates tzdata \
      libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

ENV LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ISITMYISP_DATA=/data

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY isitmyisp ./isitmyisp
RUN pip install --no-cache-dir ".[web,pdf]"

VOLUME ["/data"]
EXPOSE 8080
# Needs host networking to see your real gateway and path:
#   docker run --rm --net=host --cap-add=NET_RAW -v isitmyisp:/data isitmyisp status
# Dashboard on http://127.0.0.1:8080 (monitor --web 0.0.0.0:8080 to expose it on your LAN).
# First run: the logs print a one-time setup token to create the admin account.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s \
  CMD python -c "import os,urllib.request,sys; u=os.environ.get('ISITMYISP_HEALTH_URL','http://127.0.0.1:8080/healthz'); sys.exit(0 if urllib.request.urlopen(u,timeout=4).status==200 else 1)" || exit 1
ENTRYPOINT ["isitmyisp"]
CMD ["monitor"]
