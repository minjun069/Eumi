package com.eumi.backend.config;

import jakarta.validation.constraints.NotBlank;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties("eumi.mail")
public class EumiMailProperties {
    @NotBlank
    private String from;

    public String getFrom() { return from; }
    public void setFrom(String from) { this.from = from; }
}
