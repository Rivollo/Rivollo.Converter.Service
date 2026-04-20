FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update --fix-missing && apt-get install -y --no-install-recommends --fix-missing \
    wget \
    curl \
    python3.11 \
    python3.11-venv \
    python3-pip \
    libglu1-mesa \
    libxi6 \
    libxrender1 \
    libxkbcommon0 \
    libsm6 \
    libxxf86vm1 \
    libgl1 \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

ARG BLENDER_VERSION=5.0.0
ARG BLENDER_MIRROR=https://download.blender.org/release/Blender5.0

RUN wget -q "${BLENDER_MIRROR}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" -O /tmp/blender.tar.xz \
    && tar -xf /tmp/blender.tar.xz -C /opt \
    && mv /opt/blender-${BLENDER_VERSION}-linux-x64 /opt/blender \
    && rm /tmp/blender.tar.xz

ENV BLENDER_BIN=/opt/blender/blender

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python3", "job.py"]
