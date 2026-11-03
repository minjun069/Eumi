package com.eumi.backend.common.response;

import jakarta.servlet.http.HttpServletRequest;

/** 일반 JSON 성공 응답용. Health와 204 응답에는 사용하지 않는다. */
public record ApiResponse<T>(boolean success, T data, ResponseMeta meta) {
    public static <T> ApiResponse<T> of(T data, HttpServletRequest request) {
        return new ApiResponse<>(true, data, ResponseMeta.from(request));
    }
}
