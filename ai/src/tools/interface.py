"""Python 도구를 LangChain의 표준 호출·모델 스키마에 연결한다."""

from collections.abc import Collection, Mapping

from langchain_core.tools import BaseTool, StructuredTool

from src.tools.process import process_adapter, process_data
from src.tools.query import DataProvider, query_adapter, query_data
from src.tools.render import render_adapter, render_visualization
from src.tools.tableau import validate_visualization, visualization_adapter
from src.tools.tableau_catalog import resolve_allowed_views


def create_tools(
    providers: Mapping[str, DataProvider], *, allowed_view_keys: Collection[str] = ()
) -> list[BaseTool]:
    """호출별 권한 검사가 가능한 자료 공급자를 연결한 독립 도구 목록을 만든다.

    입력 JSON 스키마와 실제 검증은 같은 TypedDict/TypeAdapter에서 가져온다.
    자동 재시도, 작업 이력, 공개 산출물 등록은 이 인터페이스의 책임이 아니다.
    """
    registered = dict(providers)
    allowed_views = resolve_allowed_views(allowed_view_keys)

    def query(**arguments):
        return query_data(arguments, registered)

    def process(**arguments):
        return process_data(arguments)

    def render(**arguments):
        return render_visualization(arguments)

    def validate_tableau(**arguments):
        return validate_visualization(arguments, allowed_view_keys=allowed_views)

    def input_schema(name, adapter):
        schema = adapter.json_schema()
        if name == "validate_visualization":
            view = schema["properties"]["view_key"]
            view["description"] = "이번 실행에서 호출 측이 허용한 뷰 ID"
            if allowed_views:
                view["enum"] = sorted(allowed_views)
            else:
                view["description"] = (
                    "이번 실행에는 허용된 뷰가 없어 모든 호출이 거부됩니다."
                )
        return schema

    return [
        StructuredTool.from_function(
            func=fn,
            name=name,
            description=description,
            args_schema=input_schema(name, adapter),
            metadata={"retry_safe": True},
        )
        for name, fn, adapter, description in (
            (
                "query_data",
                query,
                query_adapter,
                "등록된 자료를 조건·필드·정렬·버전으로 조회한다. "
                "정상 0건과 실패를 구분하며 출처와 실제 자료 버전을 반환한다.",
            ),
            (
                "process_data",
                process,
                process_adapter,
                "전달 자료에 계산·집계·결합·필터·형변환을 순서대로 적용한다. "
                "비교 단위·분모와 결측을 검사하고 적용 연산·제외 행 수를 반환한다.",
            ),
            (
                "render_visualization",
                render,
                render_adapter,
                "전달 자료와 명세로 HTML 표·SVG 막대/선 차트·경계 지도를 만든다. "
                "산출물 내용과 적용 설정·출처·자료 버전·주의사항을 반환한다.",
            ),
            (
                "validate_visualization",
                validate_tableau,
                visualization_adapter,
                "선택한 Tableau 뷰의 입력 프로필에 따라 필터·매개변수·필수값과 "
                "선언된 날짜 순서·필터 의존 조건을 검사한다. "
                "valid=true이면 프론트용 tableau 산출물을, false이면 수정 가능한 "
                "issues와 artifact=null을 반환한다. 외부 호출·화면 검증은 하지 않는다.",
            ),
        )
    ]
