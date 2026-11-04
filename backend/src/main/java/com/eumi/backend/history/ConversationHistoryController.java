package com.eumi.backend.history;

import java.util.UUID;
import com.eumi.backend.auth.session.SessionPrincipal;
import com.eumi.backend.common.response.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/members/me/conversations")
public class ConversationHistoryController {
    private final ConversationHistoryService service;
    public ConversationHistoryController(ConversationHistoryService service) {this.service=service;}
    @GetMapping
    public ApiResponse<ConversationHistoryDtos.Page> list(@AuthenticationPrincipal SessionPrincipal principal,
            @Valid @ModelAttribute ConversationHistoryDtos.Search search,HttpServletRequest request) {
        return ApiResponse.of(service.list(principal.memberId(),search),request);
    }
    @GetMapping("/{conversationId}")
    public ApiResponse<ConversationHistoryDtos.Detail> detail(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable UUID conversationId,HttpServletRequest request) {
        return ApiResponse.of(service.detail(principal.memberId(),conversationId),request);
    }
    @DeleteMapping("/{conversationId}")
    public ResponseEntity<Void> delete(@AuthenticationPrincipal SessionPrincipal principal,@PathVariable UUID conversationId) {
        service.delete(principal.memberId(),conversationId);return ResponseEntity.noContent().build();
    }
}
