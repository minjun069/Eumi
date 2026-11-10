package com.eumi.backend.analysis;

import java.util.UUID;
import com.eumi.backend.common.response.ApiResponse;
import com.eumi.backend.common.web.RequestIdFilter;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/internal/analysis")
public class ReportIntegrationController {
    private final ReportIntegrationService service;
    public ReportIntegrationController(ReportIntegrationService service) { this.service = service; }

    @PostMapping("/pipeline-completions")
    public ResponseEntity<ApiResponse<ReportDtos.Accepted>> accept(@Valid @RequestBody ReportDtos.PipelineCompletion body,
            HttpServletRequest request) {
        var accepted = service.accept(body, UUID.fromString(RequestIdFilter.requestId(request)));
        return ResponseEntity.accepted().body(ApiResponse.of(accepted, request));
    }
    @PostMapping("/insight-report-completions")
    public ResponseEntity<Void> completed(@Valid @RequestBody ReportDtos.Completion body) {
        service.completed(body);
        return ResponseEntity.noContent().build();
    }
}
