package com.eumi.backend.auth.signup;

import java.util.List;
import com.eumi.backend.common.response.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
public class SignupController {
    private final SignupService service;
    public SignupController(SignupService service) {this.service=service;}
    @GetMapping("/organizations")
    public ApiResponse<List<SignupDtos.OrganizationSearchItem>> organizations(@RequestParam(required=false) String keyword,HttpServletRequest request) {
        return ApiResponse.of(service.organizations(keyword),request);
    }
    @PostMapping("/signup/email-verifications")
    public ResponseEntity<ApiResponse<SignupDtos.VerificationSent>> send(@Valid @RequestBody SignupDtos.SendVerificationRequest input,HttpServletRequest request) {
        return ResponseEntity.status(201).body(ApiResponse.of(service.send(input),request));
    }
    @PostMapping("/signup/email-verifications/verify")
    public ApiResponse<SignupDtos.VerificationTokenData> verify(@Valid @RequestBody SignupDtos.VerifyCodeRequest input,HttpServletRequest request) {
        return ApiResponse.of(service.verify(input),request);
    }
    @PostMapping("/members")
    public ResponseEntity<ApiResponse<SignupDtos.MemberCreated>> signup(@Valid @RequestBody SignupDtos.SignupRequest input,HttpServletRequest request) {
        return ResponseEntity.status(201).body(ApiResponse.of(service.signup(input),request));
    }
}
