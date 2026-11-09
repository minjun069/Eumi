"""임시 JSON DB·실제 보고서 API·모델·로컬 완료 알림을 검증한다."""

import argparse
import asyncio
import json
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, Response
from pydantic import SecretStr, TypeAdapter

from api import REPORT_PATH, create_app, report_request_adapter
from experiments.api_roundtrip import serve, write_json
from experiments.report_fixtures import datasets
from src.database import Database, record_report_source
from src.settings import Settings
from src.state import ReportRow, report_artifact, report_input
from src.tools.data import Dataset, read_dataset

sources_adapter = TypeAdapter(dict[str, Dataset])
reports_adapter = TypeAdapter(list[ReportRow])


class FileReportDatabase(Database):
    """단일 프로세스 실험용. 조회·저장 경계만 파일로 대체한다."""

    def __init__(self, settings, folder):
        super().__init__(settings)
        self.folder = folder
        self.catalog["public.region_result"] = self.catalog[
            "public.region_result"
        ].replace("실제 DB의", "임시 파일의 합성 자료:")

    def seed(self, body):
        body = report_request_adapter.validate_python(body)
        self.folder.mkdir(parents=True, exist_ok=False)
        write_json(self.folder / "sources.json", datasets(body), sources_adapter)
        write_json(self.folder / "reports.json", [], reports_adapter)

    def report_dataset(self, name):
        data = sources_adapter.validate_json(
            (self.folder / "sources.json").read_bytes()
        )[name]
        # 파일을 편집한 뒤에도 실제 내용과 자료 버전이 대응한다.
        data["reference"]["version"] = sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()
        return read_dataset(data)

    def region_results(self):
        return self.report_dataset("public.region_result")

    def read_reports(self):
        return reports_adapter.validate_json(
            (self.folder / "reports.json").read_bytes()
        )

    async def prepare_report(self, state):
        inputs = report_input(state)
        key = (inputs["month"] + "-01", inputs["dongCode"])
        source = next(
            (
                r
                for r in self.region_results()["rows"]
                if (r["period_start"], r["adm_cd10"]) == key
            ),
            None,
        )
        record_report_source(
            state,
            {
                "period_start": source["period_start"],
                "adm_cd10": source["adm_cd10"],
                "updated_at": source["updated_at"],
            }
            if source
            else None,
        )

    async def save_report(self, state):
        row = report_artifact(state)
        rows = [
            r
            for r in self.read_reports()
            if (r["period_start"], r["adm_cd10"])
            != (row["period_start"], row["adm_cd10"])
        ]
        # 읽기부터 교체까지 await가 없어 동별 병렬 실행에서도 갱신이 유실되지 않는다.
        write_json(self.folder / "reports.json", [*rows, row], reports_adapter)


async def run(settings, database, body):
    previous_reports = set(settings.output_dir.glob("*/report.json"))
    receiver = FastAPI()
    received = []

    @receiver.post("/api/internal/analysis/insight-report-completions", status_code=204)
    async def receive(payload: dict):
        received.append(payload)
        return Response(status_code=204)

    async with serve(receiver) as backend:
        settings.backend_url = backend
        settings.backend_token = SecretStr("local-test-token")
        app = create_app(settings, database=database)
        async with serve(app) as url, httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{url}{REPORT_PATH}", json=body)
            if response.content or response.status_code != 202:
                raise RuntimeError(f"접수 실패: HTTP {response.status_code}")
            print(f"HTTP {response.status_code}", flush=True)
            await asyncio.gather(*list(app.state.report_tasks))
    # HTTP 응답 전에 Task가 끝난 경우도 파일에서 같은 요청의 결과를 확인한다.
    reports = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in settings.output_dir.glob("*/report.json")
        if path not in previous_reports
    ]
    reports = [
        r for r in reports if report_input(r["state"])["requestId"] == body["requestId"]
    ]
    saved = database.read_reports()
    return (
        received
        == [
            {
                "requestId": body["requestId"],
                "month": body["month"],
                "savedCount": len(body["dongCodes"]),
                "failedDongCodes": [],
            }
        ]
        and len(reports) == len(body["dongCodes"])
        and all(
            r["failure"] is None
            and r["state"]["execution"]["status"] == "completed"
            and report_artifact(r["state"]) in saved
            and r["trace"]["coverage"]["model_inputs"] > 0
            and r["trace"]["coverage"]["unfinished_spans"] == 0
            for r in reports
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("outputs/report-roundtrip"))
    parser.add_argument("--month", default="2025-12")
    parser.add_argument("--dong-codes", nargs="+", default=["1168066000"])
    parser.add_argument("--model", default="gpt-5.6-luna")
    args = parser.parse_args()
    try:
        settings = Settings(
            output_dir=args.output,
            model=args.model,
            langfuse_enabled=False,
        )
        body = report_request_adapter.validate_python(
            {
                "requestId": str(uuid4()),
                "month": args.month,
                "dongCodes": args.dong_codes,
            }
        )
        database = FileReportDatabase(settings, args.file_db)
        if not args.file_db.exists():
            database.seed(body)
        passed = asyncio.run(run(settings, database, body))
    except Exception as exc:
        print(json.dumps({"passed": False, "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
    print(json.dumps({"passed": passed}))
    raise SystemExit(0 if passed else 1)
