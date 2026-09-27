# 3ds-new-forwarder-generator — entorno de desarrollo
#
# Base: imagen oficial de devkitPro para devkitARM (incluye ya el toolchain
# de GBA/DS/3DS). Confirmado: los binarios viven en /opt/devkitpro/devkitARM/bin
# y ESE PATH NO VIENE AÑADIDO al $PATH por defecto en la imagen -> lo añadimos
# nosotros explícitamente.
FROM devkitpro/devkitarm:latest

ENV DEVKITPRO=/opt/devkitpro
ENV DEVKITARM=/opt/devkitpro/devkitARM
ENV PATH=${DEVKITARM}/bin:${DEVKITPRO}/tools/bin:${PATH}

# Necesario para compilar bannertool y para los pasos de descarga de abajo.
# git hace falta porque bannertool trae un submódulo (buildtools).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        g++ gcc make zip unzip curl git ca-certificates python3 && \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# *** PUNTO A VERIFICAR ***
# No tengo confirmación directa de si ESTA imagen concreta ya trae
# preinstaladas las libs de 3DS (libctru, citro3d, 3dstools, 3dslink...) o
# si hay que tirar de dkp-pacman para instalarlas encima. Antes de fiarte de
# este bloque, comprueba con:
#
#   docker run --rm devkitpro/devkitarm:latest ls /opt/devkitpro
#
# Si ya ves ahí libctru/citro3d, este RUN de pacman puede ser innecesario
# (no debería romper nada volver a instalarlo, pero conviene saberlo).
# El nombre exacto del grupo de paquetes puede haber cambiado; si
# `3ds-dev` falla, prueba `dkp-pacman -Ss 3ds` para ver el nombre actual.
RUN dkp-pacman -Syu 3ds-dev --noconfirm || \
    (echo ">>> 3ds-dev fallo o no aplica en esta imagen, revisar manualmente" && false)

# ---------------------------------------------------------------------------
# makerom — VERIFICADO de verdad: compilado y ejecutado en un sandbox Ubuntu
# durante esta conversación (salida real: "CTR MAKEROM v0.19.0 (C) 3DSGuy").
# El binario precompilado que se distribuye en las releases de GitHub está
# enlazado contra una GLIBC más nueva que la que trae la imagen base de
# devkitPro, así que directamente lo compilamos desde fuente: el propio
# proyecto vendoriza sus dependencias (mbedtls, libblz, libyaml) como código,
# así que no hace falta nada más que un compilador C.
RUN git clone --depth 1 https://github.com/3DSGuy/Project_CTR.git /tmp/Project_CTR && \
    cd /tmp/Project_CTR/makerom && \
    make deps && \
    make && \
    mkdir -p "${DEVKITPRO}/tools/bin" && \
    cp bin/makerom "${DEVKITPRO}/tools/bin/makerom" && \
    chmod +x "${DEVKITPRO}/tools/bin/makerom" && \
    rm -rf /tmp/Project_CTR

# ---------------------------------------------------------------------------
# bannertool — VERIFICADO de verdad: clonado, compilado y ejecutado en un
# sandbox Ubuntu durante esta conversación (salida real: "bannertool
# v1.2.0-CY64"). No hay releases precompiladas fiables para esta herramienta
# (ni en el repo original de Steveice10, archivado, ni en los forks activos),
# así que se compila desde fuente. No necesita libpng/zlib porque trae su
# propio decodificador de imagen (stb_image) vendorizado.
RUN git clone --depth 1 https://github.com/CyberYoshi64/bannertool.git /tmp/bannertool && \
    cd /tmp/bannertool && \
    git submodule update --init --recursive && \
    make && \
    cp output/linux-x86_64/bannertool "${DEVKITPRO}/tools/bin/bannertool" && \
    chmod +x "${DEVKITPRO}/tools/bin/bannertool" && \
    rm -rf /tmp/bannertool

WORKDIR /work
CMD ["/bin/bash"]
