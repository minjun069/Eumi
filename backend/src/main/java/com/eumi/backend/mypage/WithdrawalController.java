package com.eumi.backend.mypage;

import com.eumi.backend.auth.session.*;
import com.eumi.backend.common.response.ApiResponse;
import jakarta.servlet.http.*;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/members/me/withdrawal")
public class WithdrawalController {
    private final WithdrawalService service;
    private final SessionAuthenticationSupport sessions;
    public WithdrawalController(WithdrawalService service,SessionAuthenticationSupport sessions) {
        this.service=service; this.sessions=sessions;
    }
    @GetMapping
    public ApiResponse<WithdrawalDtos.Info> info(@AuthenticationPrincipal SessionPrincipal principal,HttpServletRequest request) {
        return ApiResponse.of(service.info(principal.memberId()),request);
    }
    @PostMapping
    public ResponseEntity<Void> withdraw(@AuthenticationPrincipal SessionPrincipal principal,@RequestBody JsonNode body,
            HttpServletRequest request,HttpServletResponse response) {
        service.withdraw(principal.memberId(),WithdrawalDtos.Request.parse(body));
        // 서비스 트랜잭션 커밋 뒤 현재 요청 세션도 무효화해 재저장을 막는다.
        sessions.logout(request,response);
        return ResponseEntity.noContent().header("Cache-Control","no-store").build();
    }
}
