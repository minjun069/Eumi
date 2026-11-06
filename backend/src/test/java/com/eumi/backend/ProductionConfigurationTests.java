package com.eumi.backend;

import java.util.HashMap;
import java.util.Map;

import com.eumi.backend.config.AuthHashProperties;
import com.eumi.backend.config.MailConfiguration;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.boot.autoconfigure.AutoConfigurations;
import org.springframework.boot.mail.autoconfigure.MailSenderAutoConfiguration;
import org.springframework.boot.test.context.ConfigDataApplicationContextInitializer;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.env.StandardEnvironment;

import static org.assertj.core.api.Assertions.assertThat;

/** 실제 application-prod.yml을 읽되 DB·SMTP 연결은 하지 않는 설정 검사. */
class ProductionConfigurationTests {
    private static final Map<String, Object> REQUIRED = Map.of(
            "SMTP_HOST", "localhost", "SMTP_PORT", "1025", "SMTP_AUTH", "false",
            "SMTP_STARTTLS_ENABLED", "false", "EUMI_AUTH_HASH_KEY", "fixture-only-key",
            "EUMI_MAIL_FROM", "no-reply@eumi.test");

    private ApplicationContextRunner runner(Map<String, Object> variables) {
        return new ApplicationContextRunner()
                .withPropertyValues("spring.profiles.active=prod")
                .withInitializer(context -> {
                    var sources = context.getEnvironment().getPropertySources();
                    sources.remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
                    sources.remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
                    sources.addFirst(new MapPropertySource("production-test-variables", variables));
                    new ConfigDataApplicationContextInitializer().initialize(context);
                })
                .withConfiguration(AutoConfigurations.of(MailSenderAutoConfiguration.class))
                .withUserConfiguration(MailConfiguration.class);
    }

    @Test
    void productionWithoutSmtpAndEumiVariablesFailsStartup() {
        runner(Map.of()).run(context -> assertThat(context).hasFailed());
    }

    @ParameterizedTest
    @ValueSource(strings = {"SMTP_HOST", "SMTP_PORT", "SMTP_AUTH", "SMTP_STARTTLS_ENABLED",
            "EUMI_AUTH_HASH_KEY", "EUMI_MAIL_FROM"})
    void eachRequiredProductionVariableMustBePresent(String variable) {
        var variables = new HashMap<>(REQUIRED);
        variables.remove(variable);
        runner(variables).run(context -> assertThat(context).hasFailed());
    }

    @ParameterizedTest
    @ValueSource(strings = {"SMTP_HOST", "SMTP_PORT", "SMTP_AUTH", "SMTP_STARTTLS_ENABLED",
            "EUMI_AUTH_HASH_KEY", "EUMI_MAIL_FROM"})
    void eachRequiredProductionVariableMustNotBeEmpty(String variable) {
        var variables = new HashMap<>(REQUIRED);
        variables.put(variable, "");
        runner(variables).run(context -> assertThat(context).hasFailed());
    }

    @Test
    void completeProductionSettingsBindWithoutNetworkAccess() {
        runner(REQUIRED).run(context -> {
            assertThat(context).hasNotFailed();
            assertThat(context.getEnvironment().getActiveProfiles()).containsExactly("prod");
            assertThat(context.getBean(AuthHashProperties.class).getHashKey().equals("fixture-only-key")).isTrue();
        });
    }
}
