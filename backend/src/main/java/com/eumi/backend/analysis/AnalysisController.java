package com.eumi.backend.analysis;

import com.eumi.backend.auth.session.SessionPrincipal;
import com.eumi.backend.common.response.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.constraints.Pattern;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/analysis")
public class AnalysisController {
    private final AnalysisService service;

    public AnalysisController(AnalysisService service) { this.service = service; }

    @GetMapping("/sigungus/{sigunguCode}/months")
    public ApiResponse<AnalysisDtos.LoadedMonths> months(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Pattern(regexp = "[0-9]{5}") String sigunguCode, HttpServletRequest request) {
        return ApiResponse.of(service.months(principal.memberId(), sigunguCode), request);
    }

    @GetMapping("/dongs/{dongCode}/insight")
    public ApiResponse<AnalysisDtos.DongInsightData> insight(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Pattern(regexp = "[0-9]{10}") String dongCode,
            @RequestParam @Pattern(regexp = "(?!0000)[0-9]{4}-(0[1-9]|1[0-2])") String month,
            HttpServletRequest request) {
        return ApiResponse.of(service.insight(principal.memberId(), dongCode, month), request);
    }

    @GetMapping("/dongs/{dongCode}/report")
    public ApiResponse<AnalysisDtos.InsightReportData> report(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Pattern(regexp = "[0-9]{10}") String dongCode,
            @RequestParam @Pattern(regexp = "(?!0000)[0-9]{4}-(0[1-9]|1[0-2])") String month,
            HttpServletRequest request) {
        return ApiResponse.of(service.report(principal.memberId(), dongCode, month), request);
    }
}
