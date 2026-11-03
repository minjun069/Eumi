package com.eumi.backend.reference;

import java.util.List;
import com.eumi.backend.auth.session.SessionPrincipal;
import com.eumi.backend.common.response.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.constraints.Pattern;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ReferenceDataController {
    private final ReferenceDataService service;

    public ReferenceDataController(ReferenceDataService service) { this.service = service; }

    @GetMapping("/regions/sidos")
    public ApiResponse<List<ReferenceDataDtos.SidoItem>> sidos(@AuthenticationPrincipal SessionPrincipal principal,
            HttpServletRequest request) {
        return ApiResponse.of(service.sidos(principal.memberId()), request);
    }

    @GetMapping("/regions/sidos/{sidoCode}/sigungus")
    public ApiResponse<List<ReferenceDataDtos.SigunguItem>> sigungus(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Pattern(regexp = "[0-9]{2}") String sidoCode, HttpServletRequest request) {
        return ApiResponse.of(service.sigungus(principal.memberId(), sidoCode), request);
    }

    @GetMapping("/regions/sigungus/{sigunguCode}/dongs")
    public ApiResponse<List<ReferenceDataDtos.DongItem>> dongs(@AuthenticationPrincipal SessionPrincipal principal,
            @PathVariable @Pattern(regexp = "[0-9]{5}") String sigunguCode, HttpServletRequest request) {
        return ApiResponse.of(service.dongs(principal.memberId(), sigunguCode), request);
    }

    @GetMapping("/organizations/me/members")
    public ApiResponse<List<ReferenceDataDtos.MemberOption>> members(@AuthenticationPrincipal SessionPrincipal principal,
            HttpServletRequest request) {
        return ApiResponse.of(service.members(principal.memberId()), request);
    }
}
