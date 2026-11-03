package com.eumi.backend.agent;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.UUID;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;
import tools.jackson.databind.json.JsonMapper;

@Component
@ConditionalOnProperty(prefix = "eumi.ai", name = "mode", havingValue = "http")
public class HttpAgentClient implements AgentClient {
    private final HttpClient client;
    private final AgentProperties properties;
    private final JsonMapper json;

    public HttpAgentClient(AgentProperties properties, JsonMapper json) {
        this.properties = properties; this.json = json;
        client = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(properties.getHttpTimeout()).build();
    }

    private HttpResponse<String> send(UUID id, String operation, String path, String body, Duration timeout) {
        URI uri = properties.getBaseUrl().resolve(path);
        var request = HttpRequest.newBuilder(uri).timeout(timeout);
        if (body == null) request.GET();
        else request.header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body));
        var pending = client.sendAsync(request.build(), HttpResponse.BodyHandlers.ofString());
        try { return pending.get(Math.max(1, timeout.toMillis()), TimeUnit.MILLISECONDS); }
        catch (InterruptedException ex) {
            AgentDiagnostics.failure(id, operation, ex);
            pending.cancel(true); Thread.currentThread().interrupt(); throw new Unavailable();
        } catch (ExecutionException | TimeoutException ex) {
            AgentDiagnostics.failure(id, operation, ex);
            pending.cancel(true); throw new Unavailable();
        }
    }

    @Override
    public void start(UUID id, long questionId) {
        var response = send(id, "http-start", "/internal/agent/runs", json.writeValueAsString(new AgentDtos.QuestionCreated(id, questionId)),
                properties.getHttpTimeout());
        if (response.statusCode() == 202) return;
        if (response.statusCode() == 409) {
            var status = status(id);
            if (status.running() && Long.valueOf(questionId).equals(status.questionId())) return;
        }
        AgentDiagnostics.httpStatus(id, "start", response.statusCode());
        throw new Unavailable();
    }

    @Override
    public void cancel(UUID id) {
        Duration timeout = properties.getHttpTimeout().compareTo(properties.getCancelWait()) > 0
                ? properties.getCancelWait() : properties.getHttpTimeout();
        int status = send(id, "http-cancel", "/internal/agent/runs/" + id + "/cancel", "", timeout).statusCode();
        if (status != 202) {
            AgentDiagnostics.httpStatus(id, "cancel", status);
            throw new Unavailable();
        }
    }

    @Override
    public RunStatus status(UUID id) {
        var response = send(id, "http-status", "/internal/agent/runs/" + id, null, properties.getHttpTimeout());
        if (response.statusCode() != 200) {
            AgentDiagnostics.httpStatus(id, "status", response.statusCode());
            throw new Unavailable();
        }
        try {
            var body = json.readTree(response.body());
            var question = body.path("questionId");
            if (!body.path("running").isBoolean() || (!question.isNull() && !question.isIntegralNumber())
                    || (body.path("running").asBoolean() && (question.isNull() || question.asLong() < 1))) throw new Unavailable();
            return new RunStatus(body.path("running").asBoolean(), question.isNull() ? null : question.asLong());
        } catch (RuntimeException ex) {
            AgentDiagnostics.failure(id, "status-parse", ex);
            throw new Unavailable();
        }
    }
}
