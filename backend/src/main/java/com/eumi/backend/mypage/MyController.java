package com.eumi.backend.mypage;

import com.eumi.backend.auth.session.SessionPrincipal;
import com.eumi.backend.common.response.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/members/me")
public class MyController {
    private final MyService service;
    public MyController(MyService service) {this.service=service;}
    @GetMapping
    public ApiResponse<MyDtos.MyInfo> info(@AuthenticationPrincipal SessionPrincipal principal,HttpServletRequest request) {
        return ApiResponse.of(service.info(principal.memberId()),request);
    }
    @PatchMapping
    public ApiResponse<MyDtos.MyInfo> patch(@AuthenticationPrincipal SessionPrincipal principal,
            @RequestBody JsonNode body,HttpServletRequest request) {
        return ApiResponse.of(service.patch(principal.memberId(),MyDtos.Patch.parse(body)),request);
    }
    @GetMapping("/resources")
    public ApiResponse<MyDtos.MyResources> resources(@AuthenticationPrincipal SessionPrincipal principal,HttpServletRequest request) {
        return ApiResponse.of(service.resources(principal.memberId()),request);
    }
}
