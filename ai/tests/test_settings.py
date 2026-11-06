# 설정 입력 정책 검증

from src.settings import Settings

'''
다음과 같이 실행
cd C:\ssafy\free_proj\Eumi\ai
uv run pytest tests/test_settings.py -v

pytest 동작
1. 파일에서 test_로 시작하는 함수를 찾는다.
2. 매개변수 monkeypatch에 pytest의 MonkeyPatch 객체를 넣는다.
3. 테스트 함수를 실행하고 assert가 통과하는지 확인한다.
4. 테스트가 끝나면 임시로 바꾼 환경변수를 복원한다.

'''

def test_only_credentials_are_read_from_environment(monkeypatch):
    monkeypatch.setenv("SETTINGS_MODEL", "test-model")
    monkeypatch.setenv("SETTINGS_MAX_STEPS", "invalid")
    settings = Settings(_env_file=None)
    assert settings.model == "test-model"
    assert settings.max_steps == 20
    assert Settings(max_steps=3, _env_file=None).max_steps == 3
