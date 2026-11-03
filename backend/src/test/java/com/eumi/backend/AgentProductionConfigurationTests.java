package com.eumi.backend;

import java.util.Map;
import com.eumi.backend.agent.AgentConfiguration;
import com.eumi.backend.agent.AgentProperties;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.ConfigDataApplicationContextInitializer;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.env.StandardEnvironment;
import static org.assertj.core.api.Assertions.assertThat;

/** 실제 prod YAML의 모드 필수 설정 검사. DB·AI 네트워크에는 연결하지 않는다. */
class AgentProductionConfigurationTests {
    private ApplicationContextRunner runner(Map<String, Object> variables) {
        return new ApplicationContextRunner().withPropertyValues("spring.profiles.active=prod")
                .withInitializer(context -> {
                    var sources = context.getEnvironment().getPropertySources();
                    sources.remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
                    sources.remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
                    sources.addFirst(new MapPropertySource("ai-production-test-variables", variables));
                    new ConfigDataApplicationContextInitializer().initialize(context);
                }).withUserConfiguration(AgentConfiguration.class);
    }

    @Test void productionRequiresAiMode() {
        runner(Map.of()).run(context -> assertThat(context).hasFailed());
    }

    @Test void emptyProductionAiModeIsRejected() {
        runner(Map.of("EUMI_AI_MODE", "")).run(context -> assertThat(context).hasFailed());
    }

    @Test void unknownProductionAiModeIsRejected() {
        runner(Map.of("EUMI_AI_MODE", "unknown")).run(context -> assertThat(context).hasFailed());
    }

    @Test void explicitProductionFakeModeStartsWithoutHttpTimings() {
        runner(Map.of("EUMI_AI_MODE", "fake")).run(context -> {
            assertThat(context).hasNotFailed();
            assertThat(context.getBean(AgentProperties.class).getMode()).isEqualTo("fake");
        });
    }

    @Test void productionHttpStillRequiresExplicitTimings() {
        runner(Map.of("EUMI_AI_MODE", "http")).run(context -> assertThat(context).hasFailed());
    }

    @Test void productionHttpAcceptsExplicitModeAndAllFourTimings() {
        runner(Map.of("EUMI_AI_MODE", "http", "EUMI_AI_EXECUTION_LIMIT", "60s", "EUMI_AI_GRACE_PERIOD", "2s",
                "EUMI_AI_UNRESPONSIVE_AFTER", "5s", "EUMI_AI_CANCEL_WAIT", "2s"))
                .run(context -> assertThat(context).hasNotFailed());
    }
}
