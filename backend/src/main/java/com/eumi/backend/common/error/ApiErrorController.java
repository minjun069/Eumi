package com.eumi.backend.common.error;

import com.eumi.backend.common.web.RequestIdFilter;
import jakarta.servlet.RequestDispatcher;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.boot.webmvc.error.ErrorController;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Servlet 오류 dispatch에도 기본 HTML/ProblemDetail 대신 계약 응답을 사용한다. */
@RestController
public class ApiErrorController implements ErrorController {
    @RequestMapping("/error")
    public ResponseEntity<ApiErrorResponse> error(HttpServletRequest request) {
        Object value = request.getAttribute(RequestDispatcher.ERROR_STATUS_CODE);
        int status = value instanceof Integer number && number >= 400 && number <= 599 ? number : 500;
        return ResponseEntity.status(status).contentType(MediaType.APPLICATION_JSON)
                .header(HttpHeaders.CACHE_CONTROL, "no-store")
                .header(RequestIdFilter.HEADER, RequestIdFilter.requestId(request))
                .body(ApiErrorResponse.of(GlobalExceptionHandler.codeForStatus(status), request));
    }
}
