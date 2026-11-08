# 볼륨 NFS 서버 인스턴스 이미지 (볼륨 설계 결정 17). 볼륨 하나를 자기 netns의 knfsd로 export한다.
# 빌드: docker build -t anf-nfs-server backend/storage_agent/nfs_server  (scripts/setup-wsl-dataplane.sh)
FROM alpine:3.20
RUN apk add --no-cache nfs-utils rpcbind
# rootdir=/export: 호스트 ns를 /export로 바인드하므로 v3·v4.1 경로가 모두 /<creationToken>이 된다 (결정 2)
COPY nfs.conf /etc/nfs.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
