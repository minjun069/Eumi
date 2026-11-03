package com.eumi.backend.agent;

import java.net.URI;
import java.time.Duration;

import jakarta.validation.constraints.Pattern;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties("eumi.ai")
public class AgentProperties implements InitializingBean {
    @Pattern(regexp = "fake|http")
    private String mode = "fake";
    private URI baseUrl = URI.create("http://localhost:8000");
    private Duration executionLimit;
    private Duration gracePeriod;
    private Duration unresponsiveAfter;
    private Duration cancelWait;
    private Duration fakeStepDelay = Duration.ofSeconds(1);
    private Duration httpTimeout = Duration.ofSeconds(3);

    public String getMode() { return mode; }
    public void setMode(String mode) { this.mode = mode; }
    public URI getBaseUrl() { return baseUrl; }
    public void setBaseUrl(URI value) { baseUrl = value; }
    public Duration getExecutionLimit() { return executionLimit == null ? Duration.ofSeconds(60) : executionLimit; }
    public void setExecutionLimit(Duration value) { executionLimit = value; }
    public Duration getGracePeriod() { return gracePeriod == null ? Duration.ofSeconds(2) : gracePeriod; }
    public void setGracePeriod(Duration value) { gracePeriod = value; }
    public Duration getUnresponsiveAfter() { return unresponsiveAfter == null ? Duration.ofSeconds(5) : unresponsiveAfter; }
    public void setUnresponsiveAfter(Duration value) { unresponsiveAfter = value; }
    public Duration getCancelWait() { return cancelWait == null ? Duration.ofSeconds(2) : cancelWait; }
    public void setCancelWait(Duration value) { cancelWait = value; }
    public Duration getFakeStepDelay() { return fakeStepDelay; }
    public void setFakeStepDelay(Duration value) { fakeStepDelay = value; }
    public Duration getHttpTimeout() { return httpTimeout; }
    public void setHttpTimeout(Duration value) { httpTimeout = value; }

    @Override
    public void afterPropertiesSet() {
        if (!"fake".equals(mode) && !"http".equals(mode)) {
            throw new IllegalStateException("AI mode must be explicitly fake or http.");
        }
        if (mode.equals("http") && (executionLimit == null || gracePeriod == null
                || unresponsiveAfter == null || cancelWait == null)) {
            throw new IllegalStateException("HTTP AI mode requires explicit execution-limit, grace-period, unresponsive-after and cancel-wait.");
        }
        for (Duration duration : new Duration[]{getExecutionLimit(), getGracePeriod(), getUnresponsiveAfter(),
                getCancelWait(), fakeStepDelay, httpTimeout}) {
            if (duration == null || duration.isZero() || duration.isNegative()) {
                throw new IllegalStateException("AI durations must be positive.");
            }
        }
        if (baseUrl == null || !("http".equals(baseUrl.getScheme()) || "https".equals(baseUrl.getScheme()))
                || baseUrl.getHost() == null || baseUrl.getUserInfo() != null || baseUrl.getQuery() != null
                || baseUrl.getFragment() != null) {
            throw new IllegalStateException("AI base-url must be an HTTP URL without credentials, query or fragment.");
        }
    }
}
