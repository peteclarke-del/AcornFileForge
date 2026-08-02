FROM debian:bookworm-slim AS hxc-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git make gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/jfdelnero/HxCFloppyEmulator.git /src \
    && cd /src \
    && git checkout b1eee4cd73391ceaf2ad4ac57e28bf11c91333ba
RUN make -C /src/build HxCFloppyEmulator_cmdline

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=hxc-builder /src/build/hxcfe /usr/local/bin/hxcfe
COPY --from=hxc-builder /src/build/libhxcfe.so /usr/local/lib/libhxcfe.so
COPY --from=hxc-builder /src/build/libusbhxcfe.so /usr/local/lib/libusbhxcfe.so
RUN ldconfig

COPY app ./app

RUN mkdir -p /app/work

EXPOSE 8666

CMD ["gunicorn", "--bind", "0.0.0.0:8666", "--workers", "1", "--threads", "8", "--timeout", "300", "--access-logfile", "-", "app.server:app"]
