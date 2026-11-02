package com.eumi.backend.common.error;

import java.util.List;

/** 응답과 로그에 원문 입력이 섞이지 않도록 안정적인 코드만 보관한다. */
public class ApiException extends RuntimeException {
    private final ErrorCode code;
    private final List<ApiErrorResponse.FieldError> fieldErrors;

    public ApiException(ErrorCode code) {
        this(code, List.of());
    }

    public ApiException(ErrorCode code, List<ApiErrorResponse.FieldError> fieldErrors) {
        super(code.name());
        this.code = code;
        this.fieldErrors = List.copyOf(fieldErrors);
    }

    public ErrorCode code() { return code; }
    public List<ApiErrorResponse.FieldError> fieldErrors() { return fieldErrors; }
}
