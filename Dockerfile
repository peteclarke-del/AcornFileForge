FROM python:3.14-slim-trixie AS python-deps

# PyPI does not publish Capstone binaries for every Linux architecture. In
# particular, 32-bit Raspberry Pi builds fall back to the source distribution,
# which needs a native compiler and make. Install into a disposable root rather
# than carrying locally tagged wheels into the runtime stage. This avoids a
# second architecture-tag compatibility decision after the native package has
# already built successfully. The final image remains free of compilers and
# headers.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --root=/python-install -r requirements.txt \
    && PYTHONPATH="$(python -c 'import sysconfig; print("/python-install" + sysconfig.get_path("purelib"))')" \
       python -c "from capstone import CS_ARCH_ARM, CS_ARCH_M68K, CS_ARCH_MOS65XX, Cs; from oaknut.adfs import ADFS_D, ADFS_E, ADFS_E_PLUS, ADFS_F, ADFS_F_PLUS, ADFS_G, ADFS_G_PLUS; assert [item.label for item in (ADFS_D, ADFS_E, ADFS_E_PLUS, ADFS_F, ADFS_F_PLUS, ADFS_G, ADFS_G_PLUS)] == ['D', 'E', 'E+', 'F', 'F+', 'G', 'G+']; Cs(CS_ARCH_MOS65XX, 0); print('Staged Capstone ARM, M68K and MOS65XX support is available; released writable FileCore D/E/E+/F/F+/G/G+ support is available')"

FROM debian:bookworm-slim AS hxc-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git make gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/jfdelnero/HxCFloppyEmulator.git /src \
    && cd /src \
    && git checkout b1eee4cd73391ceaf2ad4ac57e28bf11c91333ba
RUN make -C /src/build HxCFloppyEmulator_cmdline

FROM debian:bookworm-slim AS elkulator-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git make gcc g++ autoconf automake libtool pkg-config patch \
    liballegro4-dev libopenal-dev libalut-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
# The pinned 1MHzWifi integration includes the Pi1MHz raw-SD MMFS adapter,
# deterministic ROM selection and the current cold-boot corrections.
RUN git clone https://github.com/stardot/elkulator.git /src/elkulator \
    && git -C /src/elkulator checkout 6cab45aba68fc3d3bdaea4c28b5de4de0307e00e \
    && git clone https://github.com/peteclarke-del/1mhzWifi.git /src/1mhzwifi \
    && git -C /src/1mhzwifi checkout c02e1dc42d36c1747780833c368dabd614091572 \
    && /src/1mhzwifi/emulator/pi1mhz-mailbox/integrations/elkulator/install.sh /src/elkulator \
    && cd /src/elkulator \
    && autoreconf -fi \
    && ./configure \
    && make -j2
RUN mkdir -p /src/elkulator-runtime \
    && cp /src/elkulator/src/elkulator /src/elkulator-runtime/ \
    && cp /src/elkulator/elk.cfg /src/elkulator-runtime/ \
    && curl -fsSL http://elkulator.acornelectron.co.uk/ElkulatorV1.0Linux.tar.gz -o /tmp/elkulator-roms.tar.gz \
    && tar -xzf /tmp/elkulator-roms.tar.gz -C /tmp \
    && find /tmp -type d -name roms -print -quit | xargs -I{} cp -a {} /src/elkulator-runtime/roms \
    && cp /src/1mhzwifi/build/pi1mhz-all/Pi1MHz/EMMFS.rom /src/elkulator-runtime/roms/ \
    && cp /src/1mhzwifi/build/pi1mhz-all/Pi1MHz/SWMMFS.rom /src/elkulator-runtime/roms/

FROM debian:bookworm-slim AS bem-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git make gcc g++ autoconf automake libtool pkg-config \
    liballegro5-dev liballegro-acodec5-dev liballegro-audio5-dev \
    liballegro-dialog5-dev liballegro-image5-dev liballegro-ttf5-dev \
    libasound2-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/stardot/b-em.git /src/b-em \
    && git -C /src/b-em checkout 6018d5e91a097d0a6dc0aee95e0477845e12660c \
    && cd /src/b-em \
    && ./autogen.sh \
    && ./configure \
    && make -j2
RUN mkdir -p /src/bem-runtime \
    && cp /src/b-em/src/b-em /src/bem-runtime/ \
    && cp /src/b-em/b-em.cfg /src/bem-runtime/ \
    && cp /src/b-em/*.bin /src/bem-runtime/ \
    && cp -a /src/b-em/roms /src/b-em/fonts /src/b-em/ddnoise /src/bem-runtime/

FROM python:3.14-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    mame xvfb xauth x11vnc novnc websockify imagemagick xdotool liballegro4.4t64 libopenal1 libalut0 \
    liballegro5.2t64 liballegro-acodec5.2t64 liballegro-audio5.2t64 \
    liballegro-dialog5.2t64 liballegro-image5.2t64 liballegro-ttf5.2t64 \
    libasound2t64 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=python-deps /python-install/usr/local /usr/local
RUN python -c "from capstone import CS_ARCH_ARM, CS_ARCH_M68K, CS_ARCH_MOS65XX, Cs; Cs(CS_ARCH_MOS65XX, 0); print('Capstone ARM, M68K and MOS65XX support is available')"

COPY --from=hxc-builder /src/build/hxcfe /usr/local/bin/hxcfe
COPY --from=hxc-builder /src/build/libhxcfe.so /usr/local/lib/libhxcfe.so
COPY --from=hxc-builder /src/build/libusbhxcfe.so /usr/local/lib/libusbhxcfe.so
COPY --from=elkulator-builder /src/elkulator-runtime /opt/elkulator
COPY --from=bem-builder /src/bem-runtime /opt/b-em
COPY firmware/mame /opt/acorn-file-forge/firmware/mame
COPY firmware/elkulator/RHPLUS133.rom.gz.b64 /tmp/RHPLUS133.rom.gz.b64
RUN base64 -d /tmp/RHPLUS133.rom.gz.b64 | gzip -dc > /opt/elkulator/roms/RHPLUS133.rom \
    && echo "cda520a110b160af2c750b2d28c84353ad2c3ede15b4821cf96452ee4dc3b5f8  /opt/elkulator/roms/RHPLUS133.rom" | sha256sum -c - \
    && rm /tmp/RHPLUS133.rom.gz.b64
RUN for profile in base plus1 plus3 plus1-plus3 ap4 plus1-ap4; do \
      mkdir -p "/opt/elkulator/profiles/$profile"; \
      cp /opt/elkulator/elkulator "/opt/elkulator/profiles/$profile/elkulator"; \
      cp /opt/elkulator/elk.cfg "/opt/elkulator/profiles/$profile/elk.cfg"; \
      ln -s ../../roms "/opt/elkulator/profiles/$profile/roms"; \
    done \
    && sed -i 's/^plus1 = .*/plus1 = 1/' /opt/elkulator/profiles/plus1/elk.cfg \
    && sed -i 's/^plus1 = .*/plus1 = 1/' /opt/elkulator/profiles/plus1-plus3/elk.cfg \
    && sed -i 's/^plus1 = .*/plus1 = 1/' /opt/elkulator/profiles/plus1-ap4/elk.cfg \
    && for profile in plus3 plus1-plus3 ap4 plus1-ap4; do \
      sed -i 's/^plus3 = .*/plus3 = 1/' "/opt/elkulator/profiles/$profile/elk.cfg"; \
    done \
    && for profile in plus3 plus1-plus3; do \
      sed -i 's/^dfsena = .*/dfsena = 0/; s/^adfsena = .*/adfsena = 1/' "/opt/elkulator/profiles/$profile/elk.cfg"; \
    done \
    && for profile in ap4 plus1-ap4; do \
      sed -i 's/^dfsena = .*/dfsena = 1/; s/^adfsena = .*/adfsena = 1/' "/opt/elkulator/profiles/$profile/elk.cfg"; \
    done \
    && for profile in base plus1 plus3 plus1-plus3 ap4 plus1-ap4; do \
      cp -a "/opt/elkulator/profiles/$profile" "/opt/elkulator/profiles/$profile-mrb"; \
      sed -i 's/^mrb = .*/mrb = 1/' "/opt/elkulator/profiles/$profile-mrb/elk.cfg"; \
    done
RUN ldconfig

COPY VERSION ./VERSION
COPY app ./app
COPY acorn_greaseweazle ./acorn_greaseweazle

RUN mkdir -p /app/work

EXPOSE 8666 8668

CMD ["gunicorn", "--bind", "0.0.0.0:8666", "--workers", "1", "--threads", "8", "--timeout", "300", "--access-logfile", "-", "app.wsgi:app"]
