"""[운영 · 인프라 연결 확인 | Spark 컨테이너] 인수인계 1차 4.1 확인 (처리 코드는 만들지 않고 연결만 본다).

Spark 컨테이너 안에서 실행해 다음을 확인한다.
  1. MinIO(s3a) 쓰기 · 읽기
  2. PostgreSQL: 11개 테이블 존재, JDBC 읽기(eumi_pipeline), DML 권한(더미 행 INSERT 후 ROLLBACK, DB에 남지 않음)
  3. Kafka: 임시 토픽을 만들어 메시지 1건을 쓰고 읽은 뒤 토픽을 지운다 (flow_hourly는 비워 둔다)
  4. Kafka: flow_hourly 토픽이 있고 읽을 수 있는지

실행 (infra/ 폴더, data profile이 켜진 상태):
    docker compose --profile data exec spark spark-submit pipeline/ops/check_infra.py
마지막 줄이 "CHECK_INFRA PASS" 이면 통과.
"""
import datetime as dt
import json
import os
import sys

import psycopg
from pyspark.sql import Row, SparkSession

BUCKET = os.environ["MINIO_BUCKET"]
DB_URL = os.environ["PIPELINE_DB_URL"]
DB_PROPS = {
    "user": os.environ["PIPELINE_DB_USER"],
    "password": os.environ["PIPELINE_DB_PASSWORD"],
    "driver": "org.postgresql.Driver",
}
DB_DSN = os.environ["PIPELINE_DB_DSN"]
KAFKA_BOOTSTRAP = os.environ["KAFKA_BOOTSTRAP"]
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC_FLOW", "flow_hourly")

# 테이블 정의서의 11개 (public 2 + analysis 9). analysis.bh_region_contribution은 DB 팀이 추가한 12번째
EXPECTED_TABLES = {
    ("public", "dim_region"), ("public", "region_result"),
    ("analysis", "dim_grid100"), ("analysis", "bg_region_detail"), ("analysis", "flow_detail"),
    ("analysis", "bg_region_indicator"), ("analysis", "bg_grid_indicator"),
    ("analysis", "bh_region_indicator"), ("analysis", "bh_grid_indicator"),
    ("analysis", "bh_grid_anomaly"), ("analysis", "re_apt_trade"),
}

results = []


def report(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"[{'OK' if passed else 'FAIL'}] {name}: {detail}", flush=True)


def kafka_batch(topic):
    return (
        spark.read.format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .load()
    )


spark = SparkSession.builder.appName("check_infra").getOrCreate()
spark.sparkContext.setLogLevel("WARN")
jvm = spark._jvm
stamp = f"{dt.datetime.now():%Y%m%d%H%M%S}"

# 1) s3a 쓰기 · 읽기 (버킷 안 _check/ 에 썼다가 지운다)
path = f"s3a://{BUCKET}/_check/spark_{stamp}.parquet"
try:
    df = spark.createDataFrame([Row(grid_cd="다사575465", ts="2025-12-01T08:00:00+09:00", m_10=1.5)])
    df.write.mode("overwrite").parquet(path)
    n = spark.read.parquet(path).count()
    report("s3a write/read", n == 1, f"{path} rows={n}")
    fs = jvm.org.apache.hadoop.fs.FileSystem.get(jvm.java.net.URI(f"s3a://{BUCKET}"), spark._jsc.hadoopConfiguration())
    fs.delete(jvm.org.apache.hadoop.fs.Path(f"s3a://{BUCKET}/_check"), True)
except Exception as e:
    report("s3a write/read", False, repr(e)[:400])

# 2-1) 테이블 11개 존재 (4.2 확인)
try:
    query = (
        "(SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_schema IN ('public', 'analysis') AND table_type = 'BASE TABLE') t"
    )
    found = {(r["table_schema"], r["table_name"]) for r in spark.read.jdbc(DB_URL, query, properties=DB_PROPS).collect()}
    missing = sorted(EXPECTED_TABLES - found)
    report("db tables (11)", not missing, "all present" if not missing else f"missing={missing}")
except Exception as e:
    report("db tables (11)", False, repr(e)[:400])

# 2-2) JDBC 읽기 (계정 · search_path · 기준 테이블 행 수)
try:
    query = (
        "(SELECT current_user AS usr, current_setting('search_path') AS search_path, "
        "(SELECT count(*) FROM public.dim_region) AS region_cnt, "
        "(SELECT count(*) FROM analysis.dim_grid100) AS grid_cnt) t"
    )
    row = spark.read.jdbc(DB_URL, query, properties=DB_PROPS).collect()[0]
    report(
        "jdbc read",
        row["usr"] == "eumi_pipeline",
        f"user={row['usr']} search_path={row['search_path']} dim_region={row['region_cnt']} dim_grid100={row['grid_cnt']}",
    )
except Exception as e:
    report("jdbc read", False, repr(e)[:400])

# 2-3) DML 권한 (public.dim_region INSERT, analysis INSERT, public.region_result INSERT/DELETE) — 전부 ROLLBACK
conn = None
try:
    conn = psycopg.connect(DB_DSN, autocommit=False)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO public.dim_region (adm_cd10, adm_nm, sgg_nm) VALUES ('0000000000', '_check', '_check')")
        cur.execute(
            "INSERT INTO analysis.bg_region_detail (period_start, adm_cd10, item_cd, value) "
            "VALUES ('2025-07-01', '0000000000', '_check', 1)"
        )
        cur.execute(
            "INSERT INTO public.region_result (period_start, adm_cd10, bg_score, bg_grade, bh_score, bh_grade, risk_grade) "
            "VALUES ('2025-07-01', '0000000000', 0, 1, 0, 1, 1)"
        )
        cur.execute("DELETE FROM public.region_result WHERE adm_cd10 = '0000000000'")
        cur.execute("SELECT now(), current_setting('TimeZone')")
        now, tz = cur.fetchone()
    report("dml grants (rolled back)", True, f"dim_region/bg_region_detail/region_result ok, db now={now} tz={tz}")
except Exception as e:
    report("dml grants (rolled back)", False, repr(e)[:400])
finally:
    if conn is not None:
        conn.rollback()
        conn.close()

# 3) Kafka 메시지 1건 쓰고 읽기 — 임시 토픽 (AdminClient로 만들고 지운다)
check_topic = f"_check_{stamp}"
admin = None
try:
    props = jvm.java.util.Properties()
    props.put("bootstrap.servers", KAFKA_BOOTSTRAP)
    admin = jvm.org.apache.kafka.clients.admin.AdminClient.create(props)
    new_topic = jvm.org.apache.kafka.clients.admin.NewTopic(check_topic, jvm.java.util.Optional.empty(), jvm.java.util.Optional.empty())
    admin.createTopics(jvm.java.util.Collections.singletonList(new_topic)).all().get()

    msg = {"ts": "2025-12-01T08:00:00+09:00", "grid_cd": "다사575465", "m_10": 1.5}
    (
        spark.createDataFrame([Row(key="다사575465", value=json.dumps(msg, ensure_ascii=False))])
        .write.format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
        .option("topic", check_topic)
        .save()
    )
    rows = kafka_batch(check_topic).selectExpr("CAST(key AS STRING) AS key", "CAST(value AS STRING) AS value").collect()
    got = [(r["key"], json.loads(r["value"])) for r in rows]
    passed = len(got) == 1 and got[0][0] == "다사575465" and got[0][1] == msg
    report("kafka write/read (temp topic)", passed, f"topic={check_topic} messages={len(got)} first={got[0] if got else None}")
except Exception as e:
    report("kafka write/read (temp topic)", False, repr(e)[:400])
finally:
    if admin is not None:
        try:
            admin.deleteTopics(jvm.java.util.Collections.singletonList(check_topic)).all().get()
        except Exception as e:
            print(f"WARN: temp topic delete failed: {e!r}"[:300], flush=True)
        admin.close()

# 4) flow_hourly 토픽 읽기 (2차 replay 대상, 지금은 비어 있어야 한다)
try:
    n = kafka_batch(KAFKA_TOPIC).count()
    report("kafka topic flow_hourly", True, f"messages={n}")
except Exception as e:
    report("kafka topic flow_hourly", False, repr(e)[:400])

spark.stop()
failed = [name for name, passed, _ in results if not passed]
print("CHECK_INFRA", "PASS" if not failed else f"FAIL {failed}", flush=True)
sys.exit(0 if not failed else 1)
