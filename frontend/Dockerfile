# ==========================================================================
# frontend(web) 이미지 — 빌드한 정적 파일을 nginx로 서빙한다
#   docker build -t eumi-web:<태그> frontend
# API는 상대 경로(/api/...)로 부르므로 빌드 때 넣을 주소가 없다.
# 호스트 Nginx가 /api/ 를 backend로, 나머지를 이 컨테이너로 보낸다.
# ==========================================================================

# ---------- build ----------
FROM node:22-alpine AS build
WORKDIR /app

# package-lock.json이 있어야 한다 (npm ci는 lock 파일 그대로 설치)
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---------- runtime ----------
FROM nginx:stable-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ > /dev/null || exit 1
