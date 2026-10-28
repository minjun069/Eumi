# ==========================================================================
# backend 이미지
#   운영 이미지:      docker build -t eumi-backend:<태그> backend
#   테스트만 (선택):  docker build --target test backend
# Java 버전을 바꾸면 두 FROM 줄을 함께 바꾼다.
# ==========================================================================

# ---------- build: 실행 가능한 jar 만들기 ----------
FROM eclipse-temurin:21-jdk AS build
WORKDIR /workspace

# 빌드 설정만 먼저 복사해 의존성 레이어를 캐시한다 (소스만 바뀌면 다시 받지 않음)
COPY gradlew settings.gradle build.gradle ./
COPY gradle gradle
RUN chmod +x gradlew && ./gradlew dependencies --no-daemon > /dev/null

COPY src src
RUN ./gradlew bootJar --no-daemon -x test \
    && find build/libs -name '*.jar' ! -name '*-plain.jar' -exec cp {} app.jar \;

# ---------- test: MR 검증 잡에서 쓸 단계 (기본 빌드에서는 실행되지 않음) ----------
FROM build AS test
RUN ./gradlew test --no-daemon

# ---------- runtime: 운영 이미지 (기본 빌드 대상) ----------
FROM eclipse-temurin:21-jre-alpine AS runtime

# pipeline과 업로드 폴더를 함께 쓰므로 uid를 10001로 맞춘다
RUN addgroup -S -g 10001 app && adduser -S -u 10001 -G app app \
    && mkdir -p /data/uploads && chown app:app /data/uploads

WORKDIR /app
COPY --from=build --chown=app:app /workspace/app.jar app.jar
USER app

EXPOSE 8080

# 첫 기동(스키마 확인 등)이 길 수 있어 start-period를 넉넉히 준다
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=6 \
    CMD wget -qO- http://127.0.0.1:8080/api/health > /dev/null || exit 1

ENTRYPOINT ["java", "-XX:MaxRAMPercentage=70", "-Duser.timezone=Asia/Seoul", "-jar", "/app/app.jar"]
