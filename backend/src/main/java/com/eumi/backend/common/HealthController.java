package com.eumi.backend.common;

import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 서버가 살아 있는지 확인하는 주소: GET /api/health
 * Docker HEALTHCHECK와 배포 스크립트(scripts/deploy.sh)가 이 주소를 부른다.
 */
@RestController
public class HealthController {

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "UP");
    }
}
