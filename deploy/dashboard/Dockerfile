# 대시보드 이미지 (FR-13, 설계 _workspace/containers/02_main_design.md 결정 6).
# node 단계에서 빌드하고(WSL에 node가 없어도 된다), nginx가 정적 파일과 두 프록시를 맡는다.
# 빌드 컨텍스트는 저장소 루트다(deploy/compose.yaml). frontend/node_modules와 dist는 .dockerignore가 뺀다.
FROM node:22-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.28.0-alpine
COPY deploy/dashboard/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
