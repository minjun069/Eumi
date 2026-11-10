package com.eumi.backend;

import java.net.*;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import com.eumi.backend.agent.AgentProperties;
import com.eumi.backend.analysis.*;
import com.eumi.backend.common.error.*;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.*;

/** Loopback HTTP 서버만 사용한다. 실제 AI/LLM을 호출하지 않는다. */
@ExtendWith(OutputCaptureExtension.class)
class ReportGenerationClientTests {
    private HttpServer server;
    private ExecutorService executor;
    private final AtomicInteger status = new AtomicInteger(202);
    private final List<Request> requests = new CopyOnWriteArrayList<>();
    private final JsonMapper json = JsonMapper.builder().build();
    private AgentProperties properties;
    private volatile boolean delayedBody;
    private record Request(String method, String path, String authorization, String body) { }
    private final ReportDtos.GenerationRequest body = new ReportDtos.GenerationRequest(UUID.randomUUID(), "2025-12", List.of("1168064000", "1168066000"));

    @BeforeEach void start() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        executor = Executors.newCachedThreadPool(Thread.ofPlatform().daemon(true).factory()); server.setExecutor(executor);
        server.createContext("/", exchange -> {
            requests.add(new Request(exchange.getRequestMethod(), exchange.getRequestURI().getPath(), exchange.getRequestHeaders().getFirst("Authorization"),
                    new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8)));
            byte[] bytes = "synthetic-private-ai-body".getBytes(StandardCharsets.UTF_8);
            if (status.get() == 202 && !delayedBody) exchange.sendResponseHeaders(202, -1);
            else {
                exchange.sendResponseHeaders(status.get(), bytes.length);
                if (delayedBody) try { Thread.sleep(1500); } catch (InterruptedException ex) { Thread.currentThread().interrupt(); }
                try { exchange.getResponseBody().write(bytes); } catch (java.io.IOException ignored) { }
            }
            exchange.close();
        });
        server.start(); properties = new AgentProperties(); properties.setMode("http");
        properties.setBaseUrl(URI.create("http://127.0.0.1:" + server.getAddress().getPort()));
    }
    @AfterEach void stop() { server.stop(0); executor.shutdownNow(); }

    @Test void acceptsEmpty202AndSendsExactlyTheCurrentContractWithoutAuthorization() {
        assertThat(new ReportGenerationClient(properties,json).generate(body)).isEqualTo(ReportGenerationClient.Admission.AI_ACCEPTED);
        assertThat(requests).hasSize(1); var sent = requests.getFirst();
        assertThat(sent.method()).isEqualTo("POST"); assertThat(sent.path()).isEqualTo("/internal/insight-reports/runs");
        assertThat(sent.authorization()).isNull();
        var value = json.readTree(sent.body());
        assertThat(value.propertyNames()).containsExactlyInAnyOrder("requestId", "month", "dongCodes");
        assertThat(value.path("requestId").asText()).isEqualTo(body.requestId().toString());
        assertThat(value.path("dongCodes")).isEqualTo(json.valueToTree(body.dongCodes()));
    }
    @Test void fakeNeverSendsAnHttpRequest() {
        properties.setMode("fake");
        assertThat(new ReportGenerationClient(properties,json).generate(body)).isEqualTo(ReportGenerationClient.Admission.FAKE_ACCEPTED);
        assertThat(requests).isEmpty();
    }
    @ParameterizedTest @ValueSource(ints = {200,204,400,409,503})
    void non202Is503WithoutRetryOrBodyDisclosure(int code, CapturedOutput output) {
        status.set(code); unavailable(new ReportGenerationClient(properties,json));
        assertThat(requests).hasSize(1);
        assertThat(output.getOut()).doesNotContain("synthetic-private-ai-body");
    }
    @Test void deadlineAlsoBoundsDelayedBodyAndDoesNotRetry() {
        delayedBody = true; properties.setHttpTimeout(Duration.ofMillis(100));
        long start = System.nanoTime(); unavailable(new ReportGenerationClient(properties,json));
        assertThat(Duration.ofNanos(System.nanoTime()-start)).isLessThan(Duration.ofSeconds(1));
        assertThat(requests).hasSize(1);
    }
    @Test void connectionFailureBecomesUnavailable() {
        var client = new ReportGenerationClient(properties,json);
        server.stop(0); unavailable(client);
    }
    private void unavailable(ReportGenerationClient client) {
        assertThatThrownBy(() -> client.generate(body)).isInstanceOfSatisfying(ApiException.class,
                ex -> assertThat(ex.code()).isEqualTo(ErrorCode.AI_UNAVAILABLE));
    }
}
