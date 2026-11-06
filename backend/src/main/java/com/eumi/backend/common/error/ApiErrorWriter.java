package com.eumi.backend.common.error;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

import com.eumi.backend.common.web.RequestIdFilter;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import tools.jackson.databind.json.JsonMapper;

/** MVC 밖에서 발생하는 Security 오류도 같은 응답 모델로 쓴다. */
@Component
public class ApiErrorWriter {
    private final JsonMapper mapper;

    public ApiErrorWriter(JsonMapper mapper) { this.mapper = mapper; }

    public void write(HttpServletRequest request, HttpServletResponse response, ErrorCode code)
            throws IOException {
        response.setStatus(code.status().value());
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setHeader(HttpHeaders.CACHE_CONTROL, "no-store");
        response.setHeader(RequestIdFilter.HEADER, RequestIdFilter.requestId(request));
        mapper.writeValue(response.getOutputStream(), ApiErrorResponse.of(code, request));
    }
}
