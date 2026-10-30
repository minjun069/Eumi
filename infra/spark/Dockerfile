# Spark 3.5 실행 이미지 (compose profile data). apache/spark 공식 이미지에 아래를 더한다.
#   - S3A (MinIO 읽기 · 쓰기): hadoop-aws + aws-java-sdk-bundle. Spark 3.5.x에 들어 있는 Hadoop 3.3.4와 같은 버전이어야 한다
#   - PostgreSQL JDBC
#   - Kafka 소스 (Structured Streaming): spark-sql-kafka-0-10 + token-provider + kafka-clients + commons-pool2
#   - Python: pandas · pyarrow · psycopg (그 달 삭제 · UPSERT 같은 SQL 실행용) · python-dotenv
# 빌드: infra/ 에서 docker compose --profile data build spark
FROM apache/spark:3.5.9-java17-python3

ARG SPARK_VERSION=3.5.9
ARG HADOOP_AWS_VERSION=3.3.4
ARG AWS_SDK_VERSION=1.12.262
ARG POSTGRES_JDBC_VERSION=42.7.14
ARG KAFKA_CLIENTS_VERSION=3.4.1
ARG COMMONS_POOL2_VERSION=2.11.1
ARG MAVEN=https://repo1.maven.org/maven2

USER root

RUN set -eux; \
    cd /opt/spark/jars; \
    curl -fsSLO "$MAVEN/org/apache/hadoop/hadoop-aws/$HADOOP_AWS_VERSION/hadoop-aws-$HADOOP_AWS_VERSION.jar"; \
    curl -fsSLO "$MAVEN/com/amazonaws/aws-java-sdk-bundle/$AWS_SDK_VERSION/aws-java-sdk-bundle-$AWS_SDK_VERSION.jar"; \
    curl -fsSLO "$MAVEN/org/postgresql/postgresql/$POSTGRES_JDBC_VERSION/postgresql-$POSTGRES_JDBC_VERSION.jar"; \
    curl -fsSLO "$MAVEN/org/apache/spark/spark-sql-kafka-0-10_2.12/$SPARK_VERSION/spark-sql-kafka-0-10_2.12-$SPARK_VERSION.jar"; \
    curl -fsSLO "$MAVEN/org/apache/spark/spark-token-provider-kafka-0-10_2.12/$SPARK_VERSION/spark-token-provider-kafka-0-10_2.12-$SPARK_VERSION.jar"; \
    curl -fsSLO "$MAVEN/org/apache/kafka/kafka-clients/$KAFKA_CLIENTS_VERSION/kafka-clients-$KAFKA_CLIENTS_VERSION.jar"; \
    curl -fsSLO "$MAVEN/org/apache/commons/commons-pool2/$COMMONS_POOL2_VERSION/commons-pool2-$COMMONS_POOL2_VERSION.jar"; \
    chmod 644 /opt/spark/jars/*.jar

RUN pip install --no-cache-dir \
      pandas==2.2.3 \
      pyarrow==17.0.0 \
      "psycopg[binary]==3.2.9" \
      python-dotenv==1.1.1

COPY spark-defaults.conf /opt/spark/conf/spark-defaults.conf

# /opt/eumi/data 는 compose가 저장소의 data/ 를 마운트하고, checkpoint 는 스트리밍 체크포인트 볼륨
RUN mkdir -p /opt/eumi/data /opt/eumi/checkpoint && chown -R spark:spark /opt/eumi

# docker compose exec 로 들어왔을 때도 spark-submit · pyspark 를 바로 찾도록
ENV PATH="/opt/spark/bin:${PATH}"

USER spark
WORKDIR /opt/eumi/data
