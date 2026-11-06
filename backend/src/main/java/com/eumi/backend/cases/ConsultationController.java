package com.eumi.backend.cases;

import java.util.List;
import com.eumi.backend.auth.session.SessionPrincipal;
import com.eumi.backend.common.response.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import static com.eumi.backend.cases.CaseDtos.MAX_ID;

@RestController
@RequestMapping("/cases/{caseId}/consultations")
public class ConsultationController {
    private final ConsultationService service;
    public ConsultationController(ConsultationService service) { this.service = service; }

    @GetMapping
    public ApiResponse<List<ConsultationDtos.ListItem>> list(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Min(1) @Max(MAX_ID) long caseId, HttpServletRequest request) {
        return ApiResponse.of(service.list(principal.memberId(), caseId), request);
    }
    @GetMapping("/{consultationId}")
    public ApiResponse<ConsultationDtos.Detail> detail(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Min(1) @Max(MAX_ID) long caseId, @PathVariable @Min(1) @Max(MAX_ID) long consultationId,
            HttpServletRequest request) {
        return ApiResponse.of(service.detail(principal.memberId(), caseId, consultationId), request);
    }
    @PostMapping
    public ResponseEntity<ApiResponse<ConsultationDtos.Created>> create(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Min(1) @Max(MAX_ID) long caseId, @Valid @RequestBody ConsultationDtos.Input input,
            HttpServletRequest request) {
        return ResponseEntity.status(201).body(ApiResponse.of(service.create(principal.memberId(), caseId, input), request));
    }
    @PutMapping("/{consultationId}")
    public ResponseEntity<Void> update(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Min(1) @Max(MAX_ID) long caseId, @PathVariable @Min(1) @Max(MAX_ID) long consultationId,
            @Valid @RequestBody ConsultationDtos.Input input) {
        service.update(principal.memberId(), caseId, consultationId, input); return ResponseEntity.noContent().build();
    }
    @DeleteMapping("/{consultationId}")
    public ResponseEntity<Void> delete(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Min(1) @Max(MAX_ID) long caseId, @PathVariable @Min(1) @Max(MAX_ID) long consultationId) {
        service.delete(principal.memberId(), caseId, consultationId); return ResponseEntity.noContent().build();
    }
}
