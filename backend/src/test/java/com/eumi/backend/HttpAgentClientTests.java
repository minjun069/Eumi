package com.eumi.backend;

import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Queue;
import java.util.UUID;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.CopyOnWriteArrayList;
import com.eumi.backend.agent.AgentClient;
import com.eumi.backend.agent.AgentProperties;
import com.eumi.backend.agent.HttpAgentClient;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/** 실제 로컬 HTTP stub 검사. FastAPI 실연결 결과와 구분한다. */
@ExtendWith(OutputCaptureExtension.class)
class HttpAgentClientTests {
    private HttpServer server;
    private HttpAgentClient client;
    private final JsonMapper json = JsonMapper.builder().build();
    private final Queue<Response> responses = new ConcurrentLinkedQueue<>();
    private final List<Request> requests = new CopyOnWriteArrayList<>();
    record Response(int status, String body, long delayAfterHeadersMillis) {
        Response(int status, String body) { this(status, body, 0); }
    }
    record Request(String method, String path, String body, String protocol, String upgrade) { }

    @BeforeEach
    void startServer() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            requests.add(new Request(exchange.getRequestMethod(), exchange.getRequestURI().getPath(),
                    new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8),
                    exchange.getProtocol(), exchange.getRequestHeaders().getFirst("Upgrade")));
            var response = responses.remove();
            byte[] body = response.body().getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(response.status(), body.length == 0 ? -1 : body.length);
            if (response.delayAfterHeadersMillis() > 0) {
                try { Thread.sleep(response.delayAfterHeadersMillis()); }
                catch (InterruptedException ex) { Thread.currentThread().interrupt(); }
            }
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        var properties = new AgentProperties();
        properties.setBaseUrl(URI.create("http://127.0.0.1:" + server.getAddress().getPort()));
        client = new HttpAgentClient(properties, json);
    }

    @AfterEach void stopServer() { if (server != null) server.stop(0); }

    @Test
    void implementsAllThreeInternalOperationsWithoutQuestionText() {
        UUID id = UUID.randomUUID();
        responses.add(new Response(202, ""));
        responses.add(new Response(200, "{\"running\":true,\"questionId\":101}"));
        responses.add(new Response(202, ""));
        client.start(id, 101);
        assertThat(client.status(id)).isEqualTo(new AgentClient.RunStatus(true, 101L));
        client.cancel(id);
        assertThat(requests).extracting(Request::method).containsExactly("POST", "GET", "POST");
        assertThat(requests).allSatisfy(request -> {
            assertThat(request.protocol()).isEqualTo("HTTP/1.1");
            assertThat(request.upgrade()).isNull();
        });
        assertThat(requests).extracting(Request::path).containsExactly("/internal/agent/runs",
                "/internal/agent/runs/" + id, "/internal/agent/runs/" + id + "/cancel");
        var body = json.readTree(requests.getFirst().body());
        assertThat(body.size()).isEqualTo(2);
        assertThat(body.path("conversationId").asText()).isEqualTo(id.toString());
        assertThat(body.path("questionId").asLong()).isEqualTo(101);
    }

    @Test
    void duplicateStartOfSameQuestionIsIdempotentAfterStatusCheck() {
        responses.add(new Response(409, ""));
        responses.add(new Response(200, "{\"running\":true,\"questionId\":101}"));
        client.start(UUID.randomUUID(), 101);
        assertThat(requests).hasSize(2);
    }

    @Test
    void rejectsFailuresAndMalformedStatusWithoutExposingResponseBody() {
        responses.add(new Response(503, "sensitive-internal-body"));
        assertThatThrownBy(() -> client.start(UUID.randomUUID(), 101)).isInstanceOf(AgentClient.Unavailable.class)
                .hasMessage("AI client request failed");
        responses.add(new Response(200, "{\"running\":true,\"questionId\":null}"));
        assertThatThrownBy(() -> client.status(UUID.randomUUID())).isInstanceOf(AgentClient.Unavailable.class);
    }

    @Test
    void deadlineAlsoCoversResponseBodyAfterHeadersHaveArrived() {
        var properties = new AgentProperties();
        properties.setBaseUrl(URI.create("http://127.0.0.1:" + server.getAddress().getPort()));
        properties.setHttpTimeout(Duration.ofMillis(300));
        var bounded = new HttpAgentClient(properties, json);
        responses.add(new Response(200, "{\"running\":false,\"questionId\":null}", 2000));
        long started = System.nanoTime();
        assertThatThrownBy(() -> bounded.status(UUID.randomUUID())).isInstanceOf(AgentClient.Unavailable.class);
        assertThat(Duration.ofNanos(System.nanoTime() - started)).isLessThan(Duration.ofMillis(1500));
    }

    @Test
    void connectionFailureLogsActualCauseClass(CapturedOutput output) {
        server.stop(0);
        server = null;
        assertThatThrownBy(() -> client.status(UUID.randomUUID())).isInstanceOf(AgentClient.Unavailable.class);
        assertThat(output.getOut()).contains("operation=http-status", "exceptionType=ConnectException")
                .doesNotContain("exceptionType=ExecutionException");
    }
}
