package com.eumi.backend.cases;

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
@RequestMapping("/cases")
public class CaseController {
    private final CaseService service;
    public CaseController(CaseService service) { this.service = service; }

    @GetMapping
    public ApiResponse<CaseDtos.Page> search(@AuthenticationPrincipal SessionPrincipal principal,
            @Valid @ModelAttribute CaseDtos.Search search, HttpServletRequest request) {
        return ApiResponse.of(service.search(principal.memberId(), search), request);
    }
    @GetMapping("/{caseId}")
    public ApiResponse<CaseDtos.Detail> detail(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Min(1) @Max(MAX_ID) long caseId, HttpServletRequest request) {
        return ApiResponse.of(service.detail(principal.memberId(), caseId), request);
    }
    @PostMapping("/duplicate-check")
    public ApiResponse<CaseDtos.Duplicates> duplicates(@AuthenticationPrincipal SessionPrincipal principal,
            @Valid @RequestBody CaseDtos.DuplicateInput input, HttpServletRequest request) {
        return ApiResponse.of(service.duplicates(principal.memberId(), input), request);
    }
    @PostMapping
    public ResponseEntity<ApiResponse<CaseDtos.Created>> create(@AuthenticationPrincipal SessionPrincipal principal,
            @Valid @RequestBody CaseDtos.Input input, HttpServletRequest request) {
        return ResponseEntity.status(201).body(ApiResponse.of(service.create(principal.memberId(), input), request));
    }
    @PutMapping("/{caseId}")
    public ResponseEntity<Void> update(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Min(1) @Max(MAX_ID) long caseId, @Valid @RequestBody CaseDtos.Input input) {
        service.update(principal.memberId(), caseId, input); return ResponseEntity.noContent().build();
    }
    @DeleteMapping("/{caseId}")
    public ResponseEntity<Void> delete(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Min(1) @Max(MAX_ID) long caseId) {
        service.delete(principal.memberId(), caseId); return ResponseEntity.noContent().build();
    }
}
