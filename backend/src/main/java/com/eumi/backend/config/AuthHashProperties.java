package com.eumi.backend.config;

import jakarta.validation.constraints.NotBlank;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/** 비밀값이 자동 toString에 포함되지 않도록 record/Lombok을 사용하지 않는다. */
@Validated
@ConfigurationProperties("eumi.auth")
public class AuthHashProperties {
    @NotBlank
    private String hashKey;

    public String getHashKey() { return hashKey; }
    public void setHashKey(String hashKey) { this.hashKey = hashKey; }
}
