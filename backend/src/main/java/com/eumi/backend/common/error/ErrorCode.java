package com.eumi.backend.common.error;

import org.springframework.http.HttpStatus;

public enum ErrorCode {
    VALIDATION_ERROR(HttpStatus.BAD_REQUEST, "요청을 처리하지 못했습니다."),
    INVALID_JSON(HttpStatus.BAD_REQUEST, "요청을 처리하지 못했습니다."),
    UNAUTHENTICATED(HttpStatus.UNAUTHORIZED, "로그인이 필요합니다."),
    INVALID_CREDENTIALS(HttpStatus.UNAUTHORIZED, "이메일 또는 비밀번호가 일치하지 않습니다."),
    FORBIDDEN(HttpStatus.FORBIDDEN, "요청을 처리하지 못했습니다."),
    PASSWORD_CHANGE_REQUIRED(HttpStatus.FORBIDDEN, "비밀번호를 먼저 변경해야 합니다."),
    CSRF_INVALID(HttpStatus.FORBIDDEN, "요청 인증 정보를 새로 준비해 주세요."),
    NOT_FOUND(HttpStatus.NOT_FOUND, "요청을 처리하지 못했습니다."),
    RUN_ALREADY_ACTIVE(HttpStatus.CONFLICT, "요청을 처리하지 못했습니다."),
    FILE_TOO_LARGE(HttpStatus.PAYLOAD_TOO_LARGE, "요청을 처리하지 못했습니다."),
    UNSUPPORTED_MEDIA_TYPE(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "요청을 처리하지 못했습니다."),
    INTERNAL_SERVER_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "요청을 처리하지 못했습니다.");

    private final HttpStatus status;
    private final String message;

    ErrorCode(HttpStatus status, String message) {
        this.status = status;
        this.message = message;
    }

    public HttpStatus status() { return status; }
    public String message() { return message; }
}
