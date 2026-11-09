package com.eumi.backend.agent;

import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AgentNotificationController {
    private final AgentLifecycle lifecycle;
    public AgentNotificationController(AgentLifecycle lifecycle) { this.lifecycle = lifecycle; }

    @PostMapping("/internal/agent/notifications")
    public ResponseEntity<Void> notified(@Valid @RequestBody AgentDtos.Notification input) {
        lifecycle.notified(input.conversationId(), input.messageId());
        return ResponseEntity.noContent().build();
    }
}
