# syntax=docker/dockerfile:1
FROM bluenviron/mediamtx:1.21.3 AS gateway

FROM ubuntu:22.04 AS driver-build
RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc libc6-dev python3 libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/blackmagic-recorder
COPY build.py ./
COPY src/ src/
COPY include/ include/
COPY sample/ sample/
COPY COPYING.GPL LICENSE ./
COPY vendor/libusb-compat/ vendor/libusb-compat/
RUN python3 build.py

FROM ubuntu:22.04 AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 ffmpeg libusb-1.0-0 coreutils ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --user-group --no-create-home --shell /usr/sbin/nologin recorder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/blackmagic-recorder
# Include the exact driver/shim sources and their licenses alongside the binaries.
COPY --from=driver-build /opt/blackmagic-recorder/ ./
COPY --from=gateway /mediamtx /usr/local/bin/mediamtx
COPY firmware/VideoRecorder.hex firmware/cap.qmmapp.seve1-eb-16mb.bin firmware/
COPY convert-capture.py ./
COPY stream-service/server.py stream-service/publish.py stream-service/qbox_ts.py stream-service/
COPY stream-service/docker/healthcheck.py stream-service/docker/smoke.py stream-service/docker/
COPY stream-service/docker/stream.json stream-service/docker/mediamtx.yml /etc/blackmagic-recorder/
RUN python3 stream-service/server.py --config /etc/blackmagic-recorder/stream.json --check \
    && ffmpeg -hide_banner -encoders 2>/dev/null | grep -q libopus \
    && /usr/local/bin/mediamtx --version
USER 1000:1000
EXPOSE 18890/tcp 18889/tcp 18189/udp 18189/tcp
HEALTHCHECK --interval=5s --timeout=3s --start-period=90s --retries=3 \
  CMD ["python3", "/opt/blackmagic-recorder/stream-service/docker/healthcheck.py", "capture"]
CMD ["python3", "/opt/blackmagic-recorder/stream-service/server.py", "--config", "/etc/blackmagic-recorder/stream.json"]
