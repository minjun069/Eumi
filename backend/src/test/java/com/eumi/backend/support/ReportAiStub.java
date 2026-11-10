package com.eumi.backend.support;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.Executors;
import com.sun.net.httpserver.HttpServer;

/** INT-05 전용 loopback 서버. 실제 AI/LLM에 연결할 수 없다. */
public final class ReportAiStub implements AutoCloseable {
    public record Request(String method, String path, String authorization, String body) { }
    public final List<Request> requests = new CopyOnWriteArrayList<>();
    public volatile int status = 202;
    public volatile long delayMillis;
    private final HttpServer server;
    private final java.util.concurrent.ExecutorService executor = Executors.newCachedThreadPool(Thread.ofPlatform().daemon(true).factory());

    public ReportAiStub() {
        try {
            server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        } catch (IOException ex) { throw new IllegalStateException("Cannot start local report stub", ex); }
        server.setExecutor(executor);
        server.createContext("/", exchange -> {
            requests.add(new Request(exchange.getRequestMethod(), exchange.getRequestURI().getPath(),
                    exchange.getRequestHeaders().getFirst("Authorization"),
                    new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8)));
            try {
                if (delayMillis > 0) Thread.sleep(delayMillis);
                exchange.sendResponseHeaders(status, -1);
            } catch (InterruptedException ex) { Thread.currentThread().interrupt(); }
            finally { exchange.close(); }
        });
        server.start();
    }
    public String baseUrl() { return "http://127.0.0.1:" + server.getAddress().getPort(); }
    public void reset() { requests.clear(); status = 202; delayMillis = 0; }
    @Override public void close() { server.stop(0); executor.shutdownNow(); }
}
