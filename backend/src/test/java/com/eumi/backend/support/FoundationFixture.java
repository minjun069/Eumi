package com.eumi.backend.support;

import com.eumi.backend.auth.session.SessionAuthenticationSupport;
import com.eumi.backend.auth.session.SessionPrincipal;
import com.eumi.backend.common.response.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.context.TestComponent;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/** 테스트 컨텍스트에만 등록한다. 실제 로그인·회원 업무 구현이 아니다. */
@TestConfiguration(proxyBeanMethods = false)
public class FoundationFixture {
    @TestComponent
    @RestController
    public static class FixtureController {
        private final SessionAuthenticationSupport sessions;

        FixtureController(SessionAuthenticationSupport sessions) { this.sessions = sessions; }

        public record Input(@NotBlank String name) { }

        @PostMapping("/signup/email-verifications/verify")
        public ApiResponse<Input> validate(@Valid @RequestBody Input input, HttpServletRequest request) {
            return ApiResponse.of(input, request);
        }

        @PostMapping("/auth/login")
        public ResponseEntity<Void> signIn(HttpServletRequest request, HttpServletResponse response) {
            sessions.establish(new SessionPrincipal(910000001L, false), request, response);
            return ResponseEntity.noContent().build();
        }

        @GetMapping("/auth/me")
        public ApiResponse<String> current(HttpServletRequest request) {
            return ApiResponse.of(request.getUserPrincipal().getName(), request);
        }

        @GetMapping("/fixture/forbidden")
        public void forbidden() { throw new AccessDeniedException("sensitive fixture input"); }

        @GetMapping("/fixture/failure")
        public void failure() { throw new IllegalStateException("SQL password secret-code fixture"); }

        @GetMapping("/fixture/empty")
        public ResponseEntity<Void> empty() { return ResponseEntity.noContent().build(); }
    }
}
