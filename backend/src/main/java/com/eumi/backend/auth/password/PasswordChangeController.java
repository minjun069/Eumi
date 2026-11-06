package com.eumi.backend.auth.password;

import com.eumi.backend.auth.login.SessionLoginData;
import com.eumi.backend.auth.session.*;
import com.eumi.backend.common.error.*;
import com.eumi.backend.common.response.ApiResponse;
import jakarta.servlet.http.*;
import jakarta.validation.Valid;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/members/me/password")
public class PasswordChangeController {
    private final PasswordChangeService service;
    private final SessionAuthenticationSupport sessions;
    public PasswordChangeController(PasswordChangeService service,SessionAuthenticationSupport sessions) {this.service=service;this.sessions=sessions;}
    @PutMapping
    public ApiResponse<SessionLoginData> change(@AuthenticationPrincipal SessionPrincipal principal,
            @Valid @RequestBody PasswordChangeRequest input,HttpServletRequest request,HttpServletResponse response) {
        var session=request.getSession(false);if(session==null)throw new ApiException(ErrorCode.UNAUTHENTICATED);
        var user=service.change(principal.memberId(),session.getId(),input);
        // DB 커밋 성공 뒤 기존 전략으로 ID 교체 → CSRF 정리 → 제한 해제 principal 저장.
        sessions.establish(new SessionPrincipal(user.memberId(),false),request,response);
        return ApiResponse.of(new SessionLoginData(user),request);
    }
}
