package com.eumi.backend.analysis;

import java.time.LocalDate;
import java.util.UUID;
import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

@Service
public class ReportIntegrationService {
    private static final Logger log = LoggerFactory.getLogger(ReportIntegrationService.class);
    private final AnalysisRepository repository;
    private final ReportGenerationClient client;
    public ReportIntegrationService(AnalysisRepository repository, ReportGenerationClient client) {
        this.repository = repository; this.client = client;
    }

    public ReportDtos.Accepted accept(ReportDtos.PipelineCompletion body, UUID requestId) {
        var targets = repository.reportTargets(LocalDate.parse(body.month() + "-01"));
        if (targets.isEmpty()) {
            record(body, requestId, 0, 404);
            throw new ApiException(ErrorCode.NOT_FOUND);
        }
        // 조회 트랜잭션이 종료된 뒤 HTTP를 호출한다. 생성 상태/보고서를 DB에 쓰지 않는다.
        try {
            client.generate(new ReportDtos.GenerationRequest(requestId, body.month(), targets));
            record(body, requestId, targets.size(), 202);
        } catch (ApiException ex) {
            record(body, requestId, targets.size(), ex.code().status().value());
            throw ex;
        }
        return new ReportDtos.Accepted(body.month(), targets.size());
    }

    public void completed(ReportDtos.Completion body) {
        // requestId는 UUID로 제한하지 않는다. 로그의 줄/제어 문자는 이스케이프한다.
        String requestId = body.requestId().replaceAll("[\\p{Cc}\\p{Cf}\\p{Zl}\\p{Zp}]", "_");
        log.info("Report generation completion requestId={} month={} status=204", requestId, body.month());
    }

    private void record(ReportDtos.PipelineCompletion body, UUID requestId, int targetCount, int status) {
        log.info("Report pipeline completion requestId={} month={} targetCount={} status={}",
                requestId, body.month(), targetCount, status);
    }
}
