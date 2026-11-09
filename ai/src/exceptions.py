"""Agent 실행 중 발생하는 오류의 유형과 전달 정보를 정의한다."""

# [이 파일]에서는 예외 종류, 전달할 정보, 오류 메시지를 정의한다.
# [오류 조건을 감지한 코드]에서 필요한 정보를 담아 해당 예외를 raise한다.
# [처리 책임이 있는 호출 계층]에서 예외를 잡아 오류 정보를 기록하고, 재시도·부분 완료·실행 중단 등의 대응을 결정한다.

class LimitReached(Exception):
    def __init__(self, resource: str, *, used: int | float, limit: int | float):
        self.code = "execution_limit_exceeded"
        self.resource = resource
        self.used = used
        self.limit = limit

        super().__init__(
            f"{resource} 한도에 도달했습니다. ({used}/{limit})"
        )


class ToolFailure(Exception):
    """도구 실패 정보를 전달한다. 재시도 여부는 호출 코드가 결정한다."""
    MESSAGES = {
        "read_unavailable": "자료를 조회할 수 없습니다.",
        "zero_denominator": "기준값이 0이어서 변화율을 계산할 수 없습니다.",
    }

    def __init__(
        self,
        code: str,
        *,
        details: dict[str, object] | None = None,
        retryable: bool = False,
    ):
        self.code = code
        self.details = dict(details) if details is not None else {}
        self.retryable = retryable

        message = self.MESSAGES.get(code, "도구 실행에 실패했습니다.")
        super().__init__(message)
