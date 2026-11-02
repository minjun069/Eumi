package com.eumi.backend.common.security;

import java.io.IOException;

import com.eumi.backend.common.error.ApiErrorWriter;
import com.eumi.backend.common.error.ErrorCode;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.web.access.AccessDeniedHandler;
import org.springframework.security.web.csrf.CsrfException;
import org.springframework.stereotype.Component;

@Component
public class ApiAccessDeniedHandler implements AccessDeniedHandler {
    private final ApiErrorWriter writer;

    public ApiAccessDeniedHandler(ApiErrorWriter writer) { this.writer = writer; }

    @Override
    public void handle(HttpServletRequest request, HttpServletResponse response,
            AccessDeniedException exception) throws IOException {
        writer.write(request, response, exception instanceof CsrfException
                ? ErrorCode.CSRF_INVALID : ErrorCode.FORBIDDEN);
    }
}
