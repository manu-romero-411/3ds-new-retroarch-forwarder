# 3ds-new-forwarder-generator -- development environment
FROM devkitpro/devkitarm:latest

ENV DEVKITPRO=/opt/devkitpro
ENV DEVKITARM=/opt/devkitpro/devkitARM
ENV PATH=${DEVKITARM}/bin:${DEVKITPRO}/tools/bin:${PATH}

# ffmpeg is the most reliable tool for generating BMPs bannertool can read.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        g++ gcc make zip unzip curl git ca-certificates python3 python3-pip ffmpeg imagemagick && \
    rm -rf /var/lib/apt/lists/*

RUN dkp-pacman -Syu 3ds-dev --noconfirm || \
    (echo ">>> 3ds-dev failed, check manually" && false)

# makerom
RUN git clone --depth 1 https://github.com/3DSGuy/Project_CTR.git /tmp/Project_CTR && \
    cd /tmp/Project_CTR/makerom && \
    make deps && \
    make && \
    mkdir -p "${DEVKITPRO}/tools/bin" && \
    cp bin/makerom "${DEVKITPRO}/tools/bin/makerom" && \
    chmod +x "${DEVKITPRO}/tools/bin/makerom" && \
    rm -rf /tmp/Project_CTR

# bannertool
RUN git clone --depth 1 https://github.com/CyberYoshi64/bannertool.git /tmp/bannertool && \
    cd /tmp/bannertool && \
    git submodule update --init --recursive && \
    make && \
    cp output/linux-x86_64/bannertool "${DEVKITPRO}/tools/bin/bannertool" && \
    chmod +x "${DEVKITPRO}/tools/bin/bannertool" && \
    rm -rf /tmp/bannertool

WORKDIR /work
CMD ["/bin/bash"]
