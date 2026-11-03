package com.eumi.backend;

import java.util.Map;
import com.eumi.backend.agent.AgentConfiguration;
import com.eumi.backend.agent.AgentProperties;
import com.eumi.backend.agent.QuestionMasker;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.Arguments;
import java.util.stream.Stream;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import static org.assertj.core.api.Assertions.assertThat;

class AgentConfigurationTests {
    private final ApplicationContextRunner runner = new ApplicationContextRunner().withUserConfiguration(AgentConfiguration.class);

    @Test
    void fakeHasExplicitlyDevelopmentOnlyTimingDefaults() {
        runner.run(context -> {
            assertThat(context).hasNotFailed();
            var properties = context.getBean(AgentProperties.class);
            assertThat(properties.getMode()).isEqualTo("fake");
            assertThat(properties.getGracePeriod()).hasSeconds(2);
        });
    }

    @ParameterizedTest
    @ValueSource(strings = {"execution-limit", "grace-period", "unresponsive-after", "cancel-wait"})
    void httpRequiresEveryAgreedTimingValue(String missing) {
        var values = Map.of("execution-limit", "60s", "grace-period", "2s", "unresponsive-after", "5s", "cancel-wait", "2s");
        var configured = runner.withPropertyValues("eumi.ai.mode=http");
        for (var entry : values.entrySet()) {
            if (!entry.getKey().equals(missing)) configured = configured.withPropertyValues("eumi.ai." + entry.getKey() + "=" + entry.getValue());
        }
        configured.run(context -> assertThat(context).hasFailed());
    }

    @Test
    void httpAcceptsExplicitPositiveTimingValues() {
        runner.withPropertyValues("eumi.ai.mode=http", "eumi.ai.execution-limit=60s", "eumi.ai.grace-period=2s",
                "eumi.ai.unresponsive-after=5s", "eumi.ai.cancel-wait=2s").run(context -> assertThat(context).hasNotFailed());
    }

    @ParameterizedTest
    @ValueSource(strings = {"0s", "-1s"})
    void nonPositiveExecutionLimitsAreRejected(String value) {
        runner.withPropertyValues("eumi.ai.execution-limit=" + value).run(context -> assertThat(context).hasFailed());
    }

    @ParameterizedTest
    @MethodSource("supportedMaskingCases")
    void masksOnlySupportedIdentifiersAndDelimitedFields(String input, String expected) {
        assertThat(new QuestionMasker().mask(input)).isEqualTo(expected);
    }

    static Stream<Arguments> supportedMaskingCases() {
        return Stream.of(
                Arguments.of("이름: 박 지원; 위험도는?", "이름: [이름]; 위험도는?"),
                Arguments.of("성명: Ali Has-an; 위험도는?", "성명: [이름]; 위험도는?"),
                Arguments.of("성함：홍길동\n위험도는?", "성함：[이름]\n위험도는?"),
                Arguments.of("사례자명 = 남궁 지원이; 비교해줘", "사례자명 = [이름]; 비교해줘"),
                Arguments.of("회원명: John James Smith Jones", "회원명: [이름]"),
                Arguments.of("생년월일: 1950-01-02; 분석기간 2026-11-03", "생년월일: [생년월일]; 분석기간 2026-11-03"),
                Arguments.of("이름: 홍길동 어르신의 위험도는?", "이름: [이름]"),
                Arguments.of("연락처 010-1234-5678, 011-123-4567", "연락처 [전화번호], [전화번호]"),
                Arguments.of("이메일주소: person@example.test; 위험도는?", "이메일주소: [이메일]; 위험도는?"),
                Arguments.of("이름: 홍길동; 비용 $5와 경로 \\자료 유지", "이름: [이름]; 비용 $5와 경로 \\자료 유지"),
                Arguments.of("이름:  ; 생년월일: \n위험도는?", "이름:  ; 생년월일: \n위험도는?"));
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "주민번호: 900101-1234567; 위험도는?",
            "계좌번호: 123.456/789; 카드번호: 1234-5678-9012-3456",
            "주소: 서울 어느로 12, 101동 202호; 위험도는?",
            "강남구 11680, 행정동 1168010100, 관리번호 2026-0001, 분석기간 2026-11-03, 70대 여성",
            "생년월일 표지 없는 날짜 1950-01-02와 일반 질문은 유지",
            "홍길동 어르신의 위험도는?",
            "집주소: 서울 어느로; 환자이름: 홍길동; 성명(한글): 김민수",
            "070-1234-5678, (02) 123-4567, +82 10-1234-5678, 01012345678"
    })
    void keepsValuesOutsideTheExplicitScope(String input) {
        assertThat(new QuestionMasker().mask(input)).isEqualTo(input);
    }
}
