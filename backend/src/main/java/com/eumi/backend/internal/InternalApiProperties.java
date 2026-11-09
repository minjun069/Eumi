package com.eumi.backend.internal;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.boot.context.properties.ConfigurationProperties;

/** 비밀값은 외부 설정에서만 받는다. 미설정 토큰은 인증하지 않는다. */
@ConfigurationProperties("eumi.internal")
public class InternalApiProperties implements InitializingBean {
    private String aiToken = "";
    private String pipelineToken = "";
    public void setAiToken(String value) { aiToken = value; }
    public void setPipelineToken(String value) { pipelineToken = value; }

    public String caller(String supplied) {
        if (matches(aiToken, supplied)) return "AI";
        if (matches(pipelineToken, supplied)) return "PIPELINE";
        return null;
    }
    private boolean present(String value) { return value != null && !value.isBlank(); }
    private boolean matches(String configured, String supplied) {
        return present(configured) && supplied != null && MessageDigest.isEqual(
                configured.getBytes(StandardCharsets.UTF_8), supplied.getBytes(StandardCharsets.UTF_8));
    }
    public void requireHttpTokens() {
        if (!present(aiToken) || !present(pipelineToken)) {
            throw new IllegalStateException("HTTP AI mode requires both internal service tokens.");
        }
    }
    @Override public void afterPropertiesSet() {
        for (String value : new String[]{aiToken, pipelineToken}) {
            if (value != null && !value.isEmpty() && (value.contains("${")
                    || value.codePoints().anyMatch(c -> Character.isWhitespace(c) || Character.isSpaceChar(c) || Character.isISOControl(c)))) {
                throw new IllegalStateException("Internal service tokens must not contain whitespace or unresolved placeholders.");
            }
        }
        if (matches(aiToken, pipelineToken)) throw new IllegalStateException("Internal service tokens must be distinct.");
    }
    @Override public String toString() { return "InternalApiProperties[redacted]"; }
}
