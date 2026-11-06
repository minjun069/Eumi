import fsspec, pandas as pd, pyarrow as pa, pyarrow.parquet as pq
from config import storage_options

def _fs(path):
    if str(path).startswith("s3://"):
        return fsspec.filesystem("s3", **storage_options(path))
    return fsspec.filesystem("file")

def write_parquet(df: pd.DataFrame, path: str):
    fs = _fs(path)
    parent = path.rsplit("/", 1)[0]
    if not str(path).startswith("s3://"):
        fs.makedirs(parent, exist_ok=True)
    with fs.open(path, "wb") as f:
        # ts 를 마이크로초로 저장한다. pandas 기본(나노초)은 Spark 3.5 가 읽지 못한다 (Illegal Parquet type TIMESTAMP(NANOS))
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), f, compression="zstd", coerce_timestamps="us", allow_truncated_timestamps=True)

def read_parquet(path: str) -> pd.DataFrame:
    fs = _fs(path)
    with fs.open(path, "rb") as f:
        return pq.read_table(f).to_pandas()

def write_csv(df: pd.DataFrame, path: str):
    fs = _fs(path)
    parent = path.rsplit("/", 1)[0]
    if not str(path).startswith("s3://"):
        fs.makedirs(parent, exist_ok=True)
    with fs.open(path, "w", encoding="utf-8-sig") as f:
        df.to_csv(f, index=False)

def list_files(dir_path: str, suffix=".parquet"):
    fs = _fs(dir_path)
    try:
        files = sorted(p for p in fs.ls(dir_path) if p.endswith(suffix))
    except FileNotFoundError:
        return []
    # s3fs.ls 는 'bucket/key' 형태로 돌려주므로 s3:// 접두사를 되살린다 (없으면 read_parquet 가 로컬 경로로 읽는다)
    if str(dir_path).startswith("s3://"):
        files = [p if p.startswith("s3://") else f"s3://{p}" for p in files]
    return files
