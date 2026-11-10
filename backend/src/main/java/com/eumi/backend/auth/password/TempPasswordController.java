package com.eumi.backend.auth.password;

import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class TempPasswordController {
    private final TempPasswordService service;
    public TempPasswordController(TempPasswordService service) { this.service = service; }
    @PostMapping("/auth/temp-password")
    public ResponseEntity<Void> issue(@Valid @RequestBody TempPasswordRequest input) {
        service.issue(input);
        return ResponseEntity.noContent().build();
    }
}
