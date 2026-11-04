package com.eumi.backend.resources;

import com.eumi.backend.auth.session.SessionPrincipal;
import com.eumi.backend.common.response.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import static com.eumi.backend.resources.ResourceDtos.MAX_ID;

@RestController
@RequestMapping("/resources")
public class ResourceController {
    private final ResourceService service;
    public ResourceController(ResourceService service) { this.service=service; }

    @GetMapping
    public ApiResponse<ResourceDtos.Page> search(@AuthenticationPrincipal SessionPrincipal principal,
            @Valid @ModelAttribute ResourceDtos.Search search,HttpServletRequest request) {
        return ApiResponse.of(service.search(principal.memberId(),search),request);
    }
    @GetMapping("/{resourceId}")
    public ApiResponse<ResourceDtos.Detail> detail(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Min(1) @Max(MAX_ID) long resourceId,HttpServletRequest request) {
        return ApiResponse.of(service.detail(principal.memberId(),resourceId),request);
    }
    @PostMapping
    public ResponseEntity<ApiResponse<ResourceDtos.Created>> create(@AuthenticationPrincipal SessionPrincipal principal,
            @Valid @RequestBody ResourceDtos.Input input,HttpServletRequest request) {
        return ResponseEntity.status(201).body(ApiResponse.of(service.create(principal.memberId(),input),request));
    }
    @PutMapping("/{resourceId}")
    public ResponseEntity<Void> update(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Min(1) @Max(MAX_ID) long resourceId,@Valid @RequestBody ResourceDtos.Input input) {
        service.update(principal.memberId(),resourceId,input); return ResponseEntity.noContent().build();
    }
    @DeleteMapping("/{resourceId}")
    public ResponseEntity<Void> delete(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Min(1) @Max(MAX_ID) long resourceId) {
        service.delete(principal.memberId(),resourceId); return ResponseEntity.noContent().build();
    }
}
