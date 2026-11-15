"""python -m eval: 시나리오 실행과 저장 증거의 규칙·LLM 평가."""

import argparse
import asyncio
import json
from hashlib import sha256
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from eval.execution.schema import ExecutionPrices, supported
from eval.runner import load_suite, run_suite, select_cases
from eval.scenario_input import load_scenario_suite
from eval.schema import suite_adapter
from src.settings import Settings


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    schema = commands.add_parser("schema", help="입력 JSON Schema 출력")
    schema.add_argument("--output", type=Path)
    validate = commands.add_parser("validate", help="모델 호출 없이 입력 검사")
    validate.add_argument("suite", type=Path)
    validate.add_argument("--case", action="append", dest="case_ids")
    validate.add_argument(
        "--unit", choices=["tool", "node", "selection", "agent", "workflow"]
    )
    validate.add_argument("--target")
    validate.add_argument("--prices", type=Path, help="실행 비용의 단가 JSON")
    prepare = commands.add_parser("prepare-db", help="빈 평가 DB에 시험 원본 적재")
    prepare.add_argument("suite", type=Path)
    prepare.add_argument("--env-file", type=Path, default=Path(".env"))
    run = commands.add_parser("run", help="지정 단위 실행 및 증거 저장")
    run.add_argument("suite", type=Path)
    run.add_argument("--output", type=Path, default=Path("eval/outputs/evaluations"))
    run.add_argument("--case", action="append", dest="case_ids")
    run.add_argument(
        "--unit", choices=["tool", "node", "selection", "agent", "workflow"]
    )
    run.add_argument("--target")
    run.add_argument("--repeat", type=int, default=1)
    run.add_argument("--env-file", type=Path, default=Path(".env"))
    run.add_argument("--model")
    run.add_argument("--prices", type=Path, help="실행 비용의 단가 JSON")
    score = commands.add_parser("score", help="저장된 도구 실행의 검사·집계 결과 저장")
    score.add_argument("batch", type=Path)
    score.add_argument("--output", type=Path, help="새 채점 JSON 파일")
    executions = commands.add_parser(
        "score-executions", help="저장된 에이전트 실행의 운영 집계·지원 범위 EX 검사"
    )
    executions.add_argument("batch", type=Path)
    executions.add_argument("--output", type=Path, help="새 채점 JSON 파일")
    executions.add_argument("--case", action="append", dest="case_ids")
    executions.add_argument("--check", action="append", dest="check_ids")
    for name, help_text in (
        ("score-nodes", "저장된 노드 원문을 규칙·LLM으로 평가"),
        ("score-outputs", "실제 최종 반환에 채택된 작성 결과의 품질 평가"),
    ):
        judge = commands.add_parser(name, help=help_text)
        judge.add_argument("batch", type=Path)
        judge.add_argument("--output", type=Path, help="새 채점 JSON 파일")
        judge.add_argument(
            "--case", action="append", dest="case_ids", help="저장된 계획의 사례 ID"
        )
        judge.add_argument(
            "--check", action="append", dest="check_ids", help="평가할 검사 ID"
        )
        judge.add_argument(
            "--row", action="append", dest="row_ids", help="평가할 JSON 상황별 행 ID"
        )
        judge.add_argument("--method", choices=["rules", "all"], default="rules")
        judge.add_argument("--judge-model", help="all 방식의 평가 전용 모델 이름")
        judge.add_argument("--env-file", type=Path, default=Path(".env"))
        if name == "score-outputs":
            judge.add_argument(
                "--reuse",
                type=Path,
                help="일치하는 기존 품질 판정을 재사용할 채점 경로",
            )
    return result


def _input(args):
    value = json.loads(args.suite.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("실행 입력은 JSON 객체여야 합니다")
    source = {}
    if value.get("schema_version") == "node-scenarios-v4":
        loaded = load_scenario_suite(
            args.suite,
            unit=args.unit or "agent",
            target=args.target,
            case_ids=args.case_ids,
        )
        suite = loaded["suite"]
        source = {
            "source_files_sha256": loaded["source_files_sha256"],
            "source_selection": loaded["selection"],
        }
        count = sum(supported(case) for case in suite["cases"])
        print(
            f"선택한 시나리오 {len(suite['cases'])}개: "
            f"EX 자동 검사 {count}개, 운영 지표 {len(suite['cases'])}개. "
            "최종 출력 품질은 score-outputs로 별도 평가합니다."
        )
    else:
        suite = suite_adapter.validate_python(value)
    prices_path = getattr(args, "prices", None)
    if prices_path is not None:
        raw = prices_path.read_bytes()
        prices = TypeAdapter(ExecutionPrices).validate_json(raw)
        suite["execution_prices"] = prices
        source.setdefault("source_files_sha256", {})[str(prices_path.resolve())] = (
            sha256(raw).hexdigest()
        )
    return suite, source


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "score-executions":
            from eval.execution.scoring import score_executions

            print(
                score_executions(
                    args.batch,
                    args.output,
                    case_ids=args.case_ids,
                    check_ids=args.check_ids,
                )
            )
            return 0
        if args.command in {"score-nodes", "score-outputs"}:
            from src.gemini import create_model

            if args.command == "score-nodes":
                from eval.nodes.scoring import score_nodes as score_model_outputs

                selection = {}
            else:
                from eval.output_scoring import score_outputs as score_model_outputs

                selection = {"reuse": args.reuse}
            if args.method == "all" and not args.judge_model:
                raise ValueError("LLM 평가에는 --judge-model을 명시해야 합니다")
            if args.method == "rules" and args.judge_model:
                raise ValueError("--judge-model은 --method all에서만 사용합니다")
            model = (
                create_model(Settings(_env_file=args.env_file, model=args.judge_model))
                if args.method == "all"
                else None
            )
            print(
                asyncio.run(
                    score_model_outputs(
                        args.batch,
                        args.output,
                        model=model,
                        judge_model=args.judge_model,
                        method=args.method,
                        case_ids=args.case_ids,
                        check_ids=args.check_ids,
                        row_ids=args.row_ids,
                        **selection,
                    )
                )
            )
            return 0
        if args.command == "score":
            from eval.tools.scoring import score_batch

            print(score_batch(args.batch, args.output))
            return 0
        if args.command == "schema":
            payload = json.dumps(
                suite_adapter.json_schema(), ensure_ascii=False, indent=2
            )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(payload + "\n", encoding="utf-8")
                print(args.output.resolve())
            else:
                print(payload)
            return 0
        if args.command == "prepare-db":
            from eval.database import prepare_database

            suite = load_suite(args.suite)
            if suite.get("data_source") != "database":
                raise ValueError("prepare-db requires data_source='database'")
            prepared = prepare_database(
                Settings(_env_file=args.env_file), suite["database_fixture"]
            )
            print(json.dumps(prepared, ensure_ascii=False))
            return 0
        suite, source = _input(args)
        if args.command == "validate":
            cases = (
                select_cases(
                    suite, case_ids=args.case_ids, unit=args.unit, target=args.target
                )
                if args.case_ids or args.unit or args.target
                else suite["cases"]
            )
            print(f"Valid suite: {suite['id']} ({len(cases)} cases)")
            return 0
        options = {"model": args.model} if args.model else {}
        settings = Settings(_env_file=args.env_file, **options)
        result = asyncio.run(
            run_suite(
                suite,
                settings,
                args.output,
                case_ids=args.case_ids,
                unit=args.unit,
                target=args.target,
                repeat=args.repeat,
                source_path=args.suite,
                **source,
            )
        )
        failed = False
        for folder in result if isinstance(result, list) else [result]:
            batch = json.loads((folder / "batch.json").read_text(encoding="utf-8"))
            print(folder)
            print(
                f"{batch['status']}: {len(batch['runs'])}/{batch['planned_runs']} runs"
            )
            failed |= batch["status"] == "error"
        return int(failed)
    except KeyboardInterrupt:
        print("평가 실행이 취소되었습니다. 생성된 실행 폴더에서 기록을 확인하세요.")
        return 130
    except ValidationError as exc:
        for error in exc.errors(
            include_input=False, include_context=False, include_url=False
        ):
            print(f"입력 오류: {error['loc']}: {error['msg']}")
        return 2
    except ValueError as exc:
        print(f"입력 오류: {exc}")
        return 2
    except Exception as exc:
        print(f"실행 또는 저장 오류: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
