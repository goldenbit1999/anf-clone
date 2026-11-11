# storage agent 이미지 (FR-13, 설계 _workspace/containers/02_main_design.md §1, 스파이크 S9).
# 호스트(WSL Ubuntu 24.04, GitHub ubuntu-24.04 러너)와 같은 배포판이라 컨테이너 안의 LVM(2.03.16)과 iptables(nft)가
# 호스트와 같다. compose의 init 서비스도 이 이미지를 쓴다(nsenter, docker CLI).
# 빌드 컨텍스트는 저장소 루트다(deploy/compose.yaml). 들어가는 파일은 루트의 .dockerignore가 정한다.

# docker CLI만 가져온다. agent가 볼륨 인스턴스를 띄우고(docker run) 상태를 묻는다(docker inspect·exec)
FROM docker:29.1.3-cli AS docker-cli

FROM ubuntu:24.04
# lvm2·thin-provisioning-tools: aggregate와 볼륨. e2fsprogs: mkfs.ext4, resize2fs, chattr. iproute2: tc, ip.
# iptables: 되돌리기 창의 입력 차단. util-linux: losetup, mount, findmnt, nsenter. kmod: modprobe ifb. procps: sysctl
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3 python3-venv lvm2 thin-provisioning-tools e2fsprogs iproute2 iptables util-linux kmod procps \
 && rm -rf /var/lib/apt/lists/*
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
# 의존성은 저장소의 pyproject.toml 하나가 정한다(D-14). 패키지는 없고(packages = []) 의존성만 설치된다
COPY pyproject.toml ./
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir .
COPY backend/storage_agent backend/storage_agent

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["/opt/venv/bin/python", "-m", "uvicorn", "--factory", "storage_agent.agent_app:create_app", \
     "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8090"]
