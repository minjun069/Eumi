package com.eumi.backend;

import com.eumi.backend.config.AuthHashProperties;
import com.eumi.backend.config.MailConfiguration;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.JavaMailSenderImpl;

import static org.assertj.core.api.Assertions.assertThat;

class FoundationConfigurationTests {
    private final ApplicationContextRunner runner = new ApplicationContextRunner()
            .withUserConfiguration(MailConfiguration.class)
            .withPropertyValues("eumi.mail.from=no-reply@eumi.test");

    @Test
    void missingHashKeyFailsStartup() {
        runner.withBean(JavaMailSender.class, JavaMailSenderImpl::new)
                .run(context -> assertThat(context).hasFailed());
    }

    @Test
    void providedHashKeyBindsWithoutLeakingThroughToString() {
        runner.withPropertyValues("eumi.auth.hash-key=fixture-only-key")
                .withBean(JavaMailSender.class, JavaMailSenderImpl::new)
                .run(context -> {
                    assertThat(context).hasNotFailed();
                    var properties = context.getBean(AuthHashProperties.class);
                    assertThat(properties.getHashKey().equals("fixture-only-key")).isTrue();
                    assertThat(properties.toString()).doesNotContain("fixture-only-key");
                });
    }

    @Test
    void smtpAuthenticationCannotStartWithEmptyCredentials() {
        runner.withPropertyValues("eumi.auth.hash-key=fixture-only-key")
                .withBean(JavaMailSender.class, () -> {
                    var sender = new JavaMailSenderImpl();
                    sender.getJavaMailProperties().setProperty("mail.smtp.auth", "true");
                    return sender;
                }).run(context -> {
                    assertThat(context).hasFailed();
                    assertThat(context.getStartupFailure()).hasRootCauseMessage(
                            "SMTP_AUTH=true requires SMTP_USERNAME and SMTP_PASSWORD.");
                });
    }
}
