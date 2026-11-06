package com.eumi.backend.auth.csrf;

import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class CsrfController {
    @GetMapping("/auth/csrf")
    public ResponseEntity<Void> prepare(CsrfToken token) {
        token.getToken(); // deferred token을 실제 생성하여 쿠키를 발급한다.
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }
}
