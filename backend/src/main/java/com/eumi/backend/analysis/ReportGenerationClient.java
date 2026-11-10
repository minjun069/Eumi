package com.eumi.backend.analysis;

import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import com.eumi.backend.agent.AgentProperties;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import org.springframework.stereotype.Component;
import tools.jackson.databind.json.JsonMapper;

/** INT-05 접수만 확인한다. fake는 네트워크를 사용하지 않고, HTTP 재시도/응답 본문 해석은 하지 않는다. */
@Component
public class ReportGenerationClient {
    public enum Admission { FAKE_ACCEPTED, AI_ACCEPTED }
    private final AgentProperties properties;
    private final JsonMapper json;
    private final HttpClient client;

    public ReportGenerationClient(AgentProperties properties, JsonMapper json) {
        this.properties = properties; this.json = json;
        client = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(properties.getHttpTimeout()).followRedirects(HttpClient.Redirect.NEVER).build();
    }

    public Admission generate(ReportDtos.GenerationRequest body) {
        if ("fake".equals(properties.getMode())) return Admission.FAKE_ACCEPTED;
        var request = HttpRequest.newBuilder(properties.getBaseUrl().resolve("/internal/insight-reports/runs"))
                .timeout(properties.getHttpTimeout()).header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(json.writeValueAsString(body))).build();
        var pending = client.sendAsync(request, HttpResponse.BodyHandlers.discarding());
        try {
            int status = pending.get(Math.max(1, properties.getHttpTimeout().toMillis()), TimeUnit.MILLISECONDS).statusCode();
            if (status == 202) return Admission.AI_ACCEPTED;
        } catch (InterruptedException ex) {
            pending.cancel(true); Thread.currentThread().interrupt();
        } catch (ExecutionException | TimeoutException ex) {
            pending.cancel(true);
        }
        throw new ApiException(ErrorCode.AI_UNAVAILABLE);
    }
}
