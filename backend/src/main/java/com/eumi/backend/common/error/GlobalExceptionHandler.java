package com.eumi.backend.common.error;

import java.util.List;

import com.eumi.backend.common.web.RequestIdFilter;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.ConstraintViolationException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.context.request.ServletWebRequest;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

@RestControllerAdvice
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {
    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(ApiException.class)
    ResponseEntity<Object> apiException(ApiException ex, HttpServletRequest request) {
        return response(ex.code(), ex.code().status(), request, ex.fieldErrors());
    }

    @ExceptionHandler(ConstraintViolationException.class)
    ResponseEntity<Object> constraintViolation(ConstraintViolationException ex, HttpServletRequest request) {
        var fields = ex.getConstraintViolations().stream()
                .map(v -> new ApiErrorResponse.FieldError(v.getPropertyPath().toString(), "입력값을 확인해 주세요."))
                .toList();
        return response(ErrorCode.VALIDATION_ERROR, ErrorCode.VALIDATION_ERROR.status(), request, fields);
    }

    @ExceptionHandler(AuthenticationException.class)
    ResponseEntity<Object> unauthenticated(AuthenticationException ex, HttpServletRequest request) {
        return response(ErrorCode.UNAUTHENTICATED, ErrorCode.UNAUTHENTICATED.status(), request, List.of());
    }

    @ExceptionHandler(AccessDeniedException.class)
    ResponseEntity<Object> forbidden(AccessDeniedException ex, HttpServletRequest request) {
        return response(ErrorCode.FORBIDDEN, ErrorCode.FORBIDDEN.status(), request, List.of());
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<Object> unexpected(Exception ex, HttpServletRequest request) {
        // 예외 메시지·스택에는 SQL, SMTP 접속 정보와 입력 원문이 포함될 수 있다.
        log.error("Unhandled request failure requestId={} exceptionType={}",
                RequestIdFilter.requestId(request), ex.getClass().getSimpleName());
        return response(ErrorCode.INTERNAL_SERVER_ERROR, ErrorCode.INTERNAL_SERVER_ERROR.status(), request, List.of());
    }

    @Override
    protected ResponseEntity<Object> handleMethodArgumentNotValid(MethodArgumentNotValidException ex,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        var fields = ex.getBindingResult().getFieldErrors().stream()
                .map(e -> new ApiErrorResponse.FieldError(e.getField(), "입력값을 확인해 주세요."))
                .toList();
        return response(ErrorCode.VALIDATION_ERROR, status, servletRequest(request), fields);
    }

    @Override
    protected ResponseEntity<Object> handleHttpMessageNotReadable(HttpMessageNotReadableException ex,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        return response(ErrorCode.INVALID_JSON, status, servletRequest(request), List.of());
    }

    @Override
    protected ResponseEntity<Object> handleExceptionInternal(Exception ex, Object body,
            HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        return response(codeForStatus(status.value()), status, servletRequest(request), List.of());
    }

    static ErrorCode codeForStatus(int status) {
        return switch (status) {
            case 401 -> ErrorCode.UNAUTHENTICATED;
            case 403 -> ErrorCode.FORBIDDEN;
            case 404 -> ErrorCode.NOT_FOUND;
            case 413 -> ErrorCode.FILE_TOO_LARGE;
            case 415 -> ErrorCode.UNSUPPORTED_MEDIA_TYPE;
            default -> status < 500 ? ErrorCode.VALIDATION_ERROR : ErrorCode.INTERNAL_SERVER_ERROR;
        };
    }

    private HttpServletRequest servletRequest(WebRequest request) {
        return ((ServletWebRequest) request).getRequest();
    }

    private ResponseEntity<Object> response(ErrorCode code, HttpStatusCode status,
            HttpServletRequest request, List<ApiErrorResponse.FieldError> fields) {
        return ResponseEntity.status(status)
                .header(HttpHeaders.CACHE_CONTROL, "no-store")
                .header(RequestIdFilter.HEADER, RequestIdFilter.requestId(request))
                .body(ApiErrorResponse.of(code, request, fields));
    }
}
