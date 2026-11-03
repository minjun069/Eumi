package com.eumi.backend.auth.login;

import com.eumi.backend.auth.session.SessionAuthenticationSupport;
import com.eumi.backend.auth.session.SessionPrincipal;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.response.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/auth")
public class AuthController {
    private final AuthService auth;
    private final SessionAuthenticationSupport sessions;

    public AuthController(AuthService auth, SessionAuthenticationSupport sessions) {
        this.auth = auth;
        this.sessions = sessions;
    }

    @PostMapping("/login")
    public ApiResponse<SessionLoginData> login(@Valid @RequestBody LoginRequest input,
            HttpServletRequest request, HttpServletResponse response) {
        var user = auth.authenticate(input);
        sessions.establish(new SessionPrincipal(user.memberId(), user.mustChangePassword()), request, response);
        return ApiResponse.of(new SessionLoginData(user), request);
    }

    @GetMapping("/me")
    public ApiResponse<MenuProfile> me(@AuthenticationPrincipal SessionPrincipal principal,
            HttpServletRequest request, HttpServletResponse response) {
        try {
            return ApiResponse.of(auth.currentUser(principal.memberId()).menuProfile(), request);
        } catch (ApiException ex) {
            sessions.logout(request, response);
            throw ex;
        }
    }

    @PostMapping("/logout")
    public ResponseEntity<Void> logout(HttpServletRequest request, HttpServletResponse response) {
        sessions.logout(request, response);
        return ResponseEntity.noContent().build();
    }
}
