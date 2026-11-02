package com.eumi.backend.common.response;

import java.time.OffsetDateTime;

import com.eumi.backend.common.web.RequestIdFilter;
import jakarta.servlet.http.HttpServletRequest;

public record ResponseMeta(String requestId, OffsetDateTime timestamp) {
    public static ResponseMeta from(HttpServletRequest request) {
        return new ResponseMeta(RequestIdFilter.requestId(request), OffsetDateTime.now());
    }
}
