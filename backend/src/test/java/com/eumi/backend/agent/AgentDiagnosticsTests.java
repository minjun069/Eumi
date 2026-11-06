package com.eumi.backend.agent;

import java.net.ConnectException;
import java.net.http.HttpTimeoutException;
import java.util.UUID;
import java.util.concurrent.ExecutionException;
import java.util.stream.Stream;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import static org.assertj.core.api.Assertions.assertThat;

@ExtendWith(OutputCaptureExtension.class)
class AgentDiagnosticsTests {
    @ParameterizedTest
    @MethodSource("networkCauses")
    void unwrapsFutureFailureClassWithoutExposingMessages(Throwable cause, CapturedOutput output) {
        AgentDiagnostics.failure(UUID.randomUUID(), "http-status", new ExecutionException("private-wrapper-text", cause));
        assertThat(output.getOut()).contains("exceptionType=" + cause.getClass().getSimpleName())
                .doesNotContain("private-wrapper-text", "private-network-text", "exceptionType=ExecutionException");
    }

    static Stream<Throwable> networkCauses() {
        return Stream.of(new ConnectException("private-network-text"), new HttpTimeoutException("private-network-text"));
    }
}
