FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg git python3 python3-pip python3-venv \
      openssh-client rsync iptables fuse-overlayfs sudo \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl --retry 3 --retry-delay 5 -fsSL https://download.docker.com/linux/ubuntu/gpg \
      | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
 && chmod a+r /etc/apt/keyrings/docker.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
 && mkdir -p /etc/docker \
 && printf '%s\n' '{' '  "storage-driver": "fuse-overlayfs"' '}' > /etc/docker/daemon.json \
 && update-alternatives --set iptables /usr/sbin/iptables-legacy \
 && update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy \
 && rm -rf /var/lib/apt/lists/*

# Node/pnpm for ISUCON14 frontend build
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g pnpm@10 \
 && rm -rf /var/lib/apt/lists/*

RUN id -u ubuntu >/dev/null 2>&1 || useradd -m -s /bin/bash ubuntu \
 && groupadd -f docker \
 && usermod -aG docker ubuntu \
 && usermod -aG sudo ubuntu \
 && echo 'ubuntu ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/ubuntu \
 && chmod 440 /etc/sudoers.d/ubuntu

USER ubuntu
WORKDIR /workspace
