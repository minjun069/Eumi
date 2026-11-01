"""Python 도구를 LangChain의 표준 호출·모델 스키마에 연결한다."""

from collections.abc import Mapping

from langchain_core.tools import BaseTool, StructuredTool

from src.tools.process import process_adapter, process_data
from src.tools.query import DataProvider, query_adapter, query_data
from src.tools.render import render_adapter, render_visualization


def create_tools(providers: Mapping[str, DataProvider]) -> list[BaseTool]:
    """호출별 권한 검사가 가능한 자료 공급자를 연결한 독립 도구 목록을 만든다.

    입력 JSON 스키마와 실제 검증은 같은 TypedDict/TypeAdapter에서 가져온다.
    자동 재시도, 작업 이력, 공개 산출물 등록은 이 인터페이스의 책임이 아니다.
    """
    registered = dict(providers)

    def query(**arguments):
        return query_data(arguments, registered)

    def process(**arguments):
        return process_data(arguments)

    def render(**arguments):
        return render_visualization(arguments)

    return [
        StructuredTool.from_function(
            func=fn,
            name=name,
            description=description,
            args_schema=adapter.json_schema(),
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
        )
    ]
