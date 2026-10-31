package com.eumi.backend.common.error;

import java.util.List;

import com.eumi.backend.common.response.ResponseMeta;
import jakarta.servlet.http.HttpServletRequest;

public record ApiErrorResponse(boolean success, ErrorDetail error, ResponseMeta meta) {
    public record FieldError(String field, String reason) { }
    public record ErrorDetail(String code, String message, List<FieldError> fieldErrors) {
        public ErrorDetail {
            fieldErrors = List.copyOf(fieldErrors);
        }
    }

    public static ApiErrorResponse of(ErrorCode code, HttpServletRequest request) {
        return of(code, request, List.of());
    }

    public static ApiErrorResponse of(ErrorCode code, HttpServletRequest request, List<FieldError> fields) {
        return new ApiErrorResponse(false, new ErrorDetail(code.name(), code.message(), fields),
                ResponseMeta.from(request));
    }
}
