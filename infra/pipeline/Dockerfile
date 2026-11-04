# 데이터 파이프라인 실행 이미지 (compose profile data, 서비스 pipeline · pipeline-web · pipeline-init).
#   - Python 3.12 + 호스트 venv 와 같은 의존성(data/requirements.txt 기준: pandas · scikit-learn 1.8 · s3fs · shapely …)
#     → 모든 배치 · 스트리밍 스크립트가 이 컨테이너 안에서 돈다 (호스트 · 컨테이너 구분 없음)
#   - Spark 3.5.9: pip 의 pyspark(spark-submit 포함) + Java 17 (+ setuptools: Python 3.12 에 없는 distutils 를 pyspark 가 쓴다). S3A(hadoop-aws) · PostgreSQL JDBC · Kafka 소스 jar 를 더한다
#   - Airflow 2.10 (LocalExecutor, 메타 DB 는 postgres 의 airflow DB): 월 배치 DAG 스케줄 · 실행 · 로그
# 빌드: infra/ 에서 docker compose --profile data build pipeline
FROM python:3.12-slim-bookworm

ARG SPARK_VERSION=3.5.9
ARG HADOOP_AWS_VERSION=3.3.4
ARG AWS_SDK_VERSION=1.12.262
ARG POSTGRES_JDBC_VERSION=42.7.14
ARG KAFKA_CLIENTS_VERSION=3.4.1
ARG COMMONS_POOL2_VERSION=2.11.1
ARG AIRFLOW_VERSION=2.10.5
ARG MAVEN=https://repo1.maven.org/maven2

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    SPARK_HOME=/usr/local/lib/python3.12/site-packages/pyspark \
    AIRFLOW_HOME=/opt/airflow \
    TZ=Asia/Seoul

RUN set -eux; apt-get update; \
    apt-get install -y --no-install-recommends openjdk-17-jre-headless curl tini procps; \
    rm -rf /var/lib/apt/lists/*

# Airflow 는 공식 constraints 로 먼저 깔고, 파이프라인 의존성은 data/requirements.txt 의 고정 버전으로 덮어쓴다
COPY requirements.txt /tmp/requirements.txt
RUN set -eux; \
    pip install "apache-airflow[postgres]==${AIRFLOW_VERSION}" \
        --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.12.txt"; \
    pip install "pyspark==${SPARK_VERSION}" "setuptools>=70" -r /tmp/requirements.txt; \
    cd "$SPARK_HOME/jars"; \
    curl -fsSLO "$MAVEN/org/apache/hadoop/hadoop-aws/$HADOOP_AWS_VERSION/hadoop-aws-$HADOOP_AWS_VERSION.jar"; \
    curl -fsSLO "$MAVEN/com/amazonaws/aws-java-sdk-bundle/$AWS_SDK_VERSION/aws-java-sdk-bundle-$AWS_SDK_VERSION.jar"; \
    curl -fsSLO "$MAVEN/org/postgresql/postgresql/$POSTGRES_JDBC_VERSION/postgresql-$POSTGRES_JDBC_VERSION.jar"; \
    curl -fsSLO "$MAVEN/org/apache/spark/spark-sql-kafka-0-10_2.12/$SPARK_VERSION/spark-sql-kafka-0-10_2.12-$SPARK_VERSION.jar"; \
    curl -fsSLO "$MAVEN/org/apache/spark/spark-token-provider-kafka-0-10_2.12/$SPARK_VERSION/spark-token-provider-kafka-0-10_2.12-$SPARK_VERSION.jar"; \
    curl -fsSLO "$MAVEN/org/apache/kafka/kafka-clients/$KAFKA_CLIENTS_VERSION/kafka-clients-$KAFKA_CLIENTS_VERSION.jar"; \
    curl -fsSLO "$MAVEN/org/apache/commons/commons-pool2/$COMMONS_POOL2_VERSION/commons-pool2-$COMMONS_POOL2_VERSION.jar"; \
    chmod 644 "$SPARK_HOME"/jars/*.jar

COPY spark-defaults.conf $SPARK_HOME/conf/spark-defaults.conf

# 실행 계정 pipeline(uid 50000, Airflow 관례). /opt/eumi/data 는 compose 가 저장소 data/ 를 마운트
RUN set -eux; useradd -m -u 50000 -s /bin/bash pipeline; \
    mkdir -p /opt/eumi/data /opt/eumi/checkpoint /opt/airflow/logs; chown -R pipeline:pipeline /opt/eumi /opt/airflow
    # /opt/airflow/logs 는 compose 가 볼륨으로 덮는다. 이미지에 pipeline 소유로 미리 만들어 두어야 볼륨도 그 소유로 생긴다

ENV PATH="$SPARK_HOME/bin:${PATH}"
USER pipeline
WORKDIR /opt/eumi/data
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sleep", "infinity"]
