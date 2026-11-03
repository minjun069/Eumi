package com.eumi.backend.agent;

import java.util.UUID;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.CompletionException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/** 원문·응답 본문·예외 메시지·스택을 남기지 않는 AI 운영 진단. */
final class AgentDiagnostics {
    private static final Logger log = LoggerFactory.getLogger(AgentDiagnostics.class);
    private AgentDiagnostics() { }

    static void failure(UUID id, String operation, Throwable failure) {
        Throwable reported = failure;
        for (int depth = 0; depth < 8 && (reported instanceof ExecutionException || reported instanceof CompletionException)
                && reported.getCause() != null && reported.getCause() != reported; depth++) {
            reported = reported.getCause();
        }
        log.warn("AI operation failed conversationId={} operation={} exceptionType={}",
                id, operation, reported.getClass().getSimpleName());
    }

    static void httpStatus(UUID id, String operation, int status) {
        log.warn("AI HTTP response rejected conversationId={} operation={} status={}", id, operation, status);
    }

    static void substituted(UUID id, long questionId, String operation, String status) {
        log.warn("AI terminal message substituted conversationId={} questionId={} operation={} status={}",
                id, questionId, operation, status);
    }
}
