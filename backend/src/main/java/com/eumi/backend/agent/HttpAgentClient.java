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
        client = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(properties.getHttpTimeout())
                .followRedirects(HttpClient.Redirect.NEVER).build();
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
    public void start(UUID id, long questionId, AgentDtos.ScreenContext context) {
        var response = send(id, "http-start", "/internal/agent/runs", json.writeValueAsString(new AgentDtos.RunRequest(id, questionId, context)),
                properties.getHttpTimeout());
        if (response.statusCode() == 202) {
            AgentDiagnostics.accepted(id, questionId);
            return;
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

}
