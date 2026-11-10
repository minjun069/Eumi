package com.eumi.backend.common.error;

import org.springframework.http.HttpStatus;

public enum ErrorCode {
    VALIDATION_ERROR(HttpStatus.BAD_REQUEST, "요청을 처리하지 못했습니다."),
    INVALID_JSON(HttpStatus.BAD_REQUEST, "요청을 처리하지 못했습니다."),
    UNAUTHENTICATED(HttpStatus.UNAUTHORIZED, "로그인이 필요합니다."),
    INVALID_CREDENTIALS(HttpStatus.UNAUTHORIZED, "이메일 또는 비밀번호가 일치하지 않습니다."),
    EMAIL_DOMAIN_MISMATCH(HttpStatus.BAD_REQUEST, "요청을 처리하지 못했습니다."),
    EMAIL_ALREADY_EXISTS(HttpStatus.CONFLICT, "요청을 처리하지 못했습니다."),
    VERIFICATION_INVALID(HttpStatus.BAD_REQUEST, "요청을 처리하지 못했습니다."),
    VERIFICATION_EXPIRED(HttpStatus.BAD_REQUEST, "요청을 처리하지 못했습니다."),
    PROOF_INVALID(HttpStatus.BAD_REQUEST, "요청을 처리하지 못했습니다."),
    PROOF_EXPIRED(HttpStatus.BAD_REQUEST, "요청을 처리하지 못했습니다."),
    RATE_LIMITED(HttpStatus.TOO_MANY_REQUESTS, "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."),
    CURRENT_PASSWORD_MISMATCH(HttpStatus.BAD_REQUEST, "현재 비밀번호가 일치하지 않습니다."),
    NEW_PASSWORD_EQUALS_CURRENT(HttpStatus.BAD_REQUEST, "새 비밀번호는 현재 비밀번호와 달라야 합니다."),
    WITHDRAW_PASSWORD_MISMATCH(HttpStatus.BAD_REQUEST, "비밀번호가 일치하지 않습니다."),
    FORBIDDEN(HttpStatus.FORBIDDEN, "요청을 처리하지 못했습니다."),
    PASSWORD_CHANGE_REQUIRED(HttpStatus.FORBIDDEN, "비밀번호를 먼저 변경해야 합니다."),
    CSRF_INVALID(HttpStatus.FORBIDDEN, "요청 인증 정보를 새로 준비해 주세요."),
    NOT_FOUND(HttpStatus.NOT_FOUND, "요청을 처리하지 못했습니다."),
    RUN_ALREADY_ACTIVE(HttpStatus.CONFLICT, "요청을 처리하지 못했습니다."),
    STATE_CONFLICT(HttpStatus.CONFLICT, "처리 대상이 변경되었습니다. 다시 확인해 주세요."),
    MANAGEMENT_NUMBER_EXHAUSTED(HttpStatus.CONFLICT, "요청을 처리하지 못했습니다."),
    FILE_TOO_LARGE(HttpStatus.PAYLOAD_TOO_LARGE, "요청을 처리하지 못했습니다."),
    UNSUPPORTED_MEDIA_TYPE(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "요청을 처리하지 못했습니다."),
    INTERNAL_SERVER_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "요청을 처리하지 못했습니다."),
    AI_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "AI 서비스에 연결하지 못했습니다.");

    private final HttpStatus status;
    private final String message;

    ErrorCode(HttpStatus status, String message) {
        this.status = status;
        this.message = message;
    }

    public HttpStatus status() { return status; }
    public String message() { return message; }
}
