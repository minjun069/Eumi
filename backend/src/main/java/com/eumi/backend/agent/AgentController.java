package com.eumi.backend.agent;

import java.util.UUID;
import com.eumi.backend.auth.session.SessionPrincipal;
import com.eumi.backend.common.response.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Max;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/agent")
public class AgentController {
    private final AgentService service;
    public AgentController(AgentService service) { this.service = service; }

    @PostMapping("/questions")
    public ResponseEntity<ApiResponse<AgentDtos.QuestionCreated>> question(@AuthenticationPrincipal SessionPrincipal principal,
            @Valid @RequestBody AgentDtos.QuestionRequest input, HttpServletRequest request) {
        return ResponseEntity.accepted().body(ApiResponse.of(service.ask(principal.memberId(), input), request));
    }

    @GetMapping("/conversations/{conversationId}/messages")
    public ApiResponse<AgentDtos.Messages> messages(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable UUID conversationId, @RequestParam(defaultValue = "0") @Min(0) @Max(9007199254740991L) long after,
            HttpServletRequest request) {
        return ApiResponse.of(service.messages(principal.memberId(), conversationId, after), request);
    }

    @PostMapping("/conversations/{conversationId}/cancel")
    public ResponseEntity<Void> cancel(@AuthenticationPrincipal SessionPrincipal principal, @PathVariable UUID conversationId) {
        service.cancel(principal.memberId(), conversationId);
        return ResponseEntity.noContent().build();
    }
}
