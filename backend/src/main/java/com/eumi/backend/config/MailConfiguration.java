package com.eumi.backend.config;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Bean;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.JavaMailSenderImpl;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties({AuthHashProperties.class, EumiMailProperties.class})
public class MailConfiguration {
    @Bean
    @Profile("prod")
    InitializingBean validateProductionSettings(Environment environment) {
        return () -> {
            for (String property : new String[]{"spring.mail.host", "spring.mail.port",
                    "spring.mail.properties[mail.smtp.auth]", "spring.mail.properties[mail.smtp.starttls.enable]",
                    "eumi.auth.hash-key", "eumi.mail.from"}) {
                String value = environment.resolveRequiredPlaceholders(environment.getRequiredProperty(property));
                if (value.isBlank()) throw new IllegalStateException("Required production setting is blank: " + property);
            }
        };
    }

    @Bean
    InitializingBean validateSmtpSettings(JavaMailSender sender) {
        return () -> {
            if (sender instanceof JavaMailSenderImpl smtp
                    && Boolean.parseBoolean(smtp.getJavaMailProperties().getProperty("mail.smtp.auth", "false"))
                    && (smtp.getUsername() == null || smtp.getUsername().isBlank()
                        || smtp.getPassword() == null || smtp.getPassword().isBlank())) {
                throw new IllegalStateException("SMTP_AUTH=true requires SMTP_USERNAME and SMTP_PASSWORD.");
            }
        };
    }
}
