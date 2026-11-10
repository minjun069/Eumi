package com.eumi.backend.support;

import java.util.Map;
import org.springframework.boot.EnvironmentPostProcessor;
import org.springframework.boot.SpringApplication;
import org.springframework.core.Ordered;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.MapPropertySource;

/** 공용 DB를 쓰는 모든 Boot 테스트에서 외부 환경값보다 먼저 배치를 끈다. 운영 jar에는 포함되지 않는다. */
public class CleanupSchedulingTestEnvironmentPostProcessor implements EnvironmentPostProcessor,Ordered {
    @Override public void postProcessEnvironment(ConfigurableEnvironment environment,SpringApplication application) {
        environment.getPropertySources().addFirst(new MapPropertySource("testConversationCleanupScheduling",
                Map.of("eumi.batch.conversation-cleanup-cron","-")));
    }
    @Override public int getOrder() {return Ordered.LOWEST_PRECEDENCE;}
}
