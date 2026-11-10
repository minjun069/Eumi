package com.eumi.backend;

import java.time.LocalDate;
import java.util.List;
import java.util.UUID;
import com.eumi.backend.analysis.*;
import com.eumi.backend.common.error.*;
import com.eumi.backend.common.security.*;
import com.eumi.backend.common.web.RequestIdFilter;
import com.eumi.backend.config.SecurityConfig;
import com.eumi.backend.internal.InternalSecurityConfiguration;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/** 실제 MVC/보안/서비스, DB와 AI 경계는 mock. 토큰은 메모리에서만 만든다. */
@WebMvcTest(controllers = ReportIntegrationController.class, properties = "spring.test.mockmvc.print=none")
@ExtendWith(OutputCaptureExtension.class)
@Import({SecurityConfig.class, InternalSecurityConfiguration.class, ReportIntegrationService.class, ApiErrorWriter.class,
        ApiAuthenticationEntryPoint.class, ApiAccessDeniedHandler.class, RequestIdFilter.class, GlobalExceptionHandler.class})
class ReportIntegrationWebTests {
    private static final String PIPELINE = UUID.randomUUID().toString(), AI = UUID.randomUUID().toString();
    private static final String ACCEPT = "/internal/analysis/pipeline-completions", COMPLETE = "/internal/analysis/insight-report-completions";
    @Autowired MockMvc mvc;
    @Autowired JsonMapper json;
    @MockitoBean AnalysisRepository repository;
    @MockitoBean ReportGenerationClient client;
    @DynamicPropertySource static void settings(DynamicPropertyRegistry registry) {
        registry.add("eumi.internal.pipeline-token", () -> PIPELINE); registry.add("eumi.internal.ai-token", () -> AI);
    }

    @Test void acceptedRequestUsesOneServerGeneratedIdAndDefaultReason() throws Exception {
        when(repository.reportTargets(LocalDate.of(2025,12,1))).thenReturn(List.of("1168064000", "1168066000"));
        when(client.generate(any())).thenReturn(ReportGenerationClient.Admission.FAKE_ACCEPTED);
        String incoming = UUID.randomUUID().toString();
        var result = mvc.perform(post(ACCEPT).header("Authorization", "Bearer " + PIPELINE).header("X-Request-Id", incoming)
                .contentType(MediaType.APPLICATION_JSON).content("{\"month\":\"2025-12\"}"))
                .andExpect(status().isAccepted()).andExpect(jsonPath("$.data.targetCount").value(2)).andReturn();
        String id = result.getResponse().getHeader("X-Request-Id");
        assertThat(id).isNotEqualTo(incoming);
        assertThat(json.readTree(result.getResponse().getContentAsString()).path("meta").path("requestId").asText()).isEqualTo(id);
        var captured = ArgumentCaptor.forClass(ReportDtos.GenerationRequest.class);
        verify(client).generate(captured.capture());
        assertThat(captured.getValue().requestId()).isEqualTo(UUID.fromString(id));
        assertThat(captured.getValue().dongCodes()).containsExactly("1168064000", "1168066000");
        assertThat(result.getRequest().getSession(false)).isNull();
        assertThat(result.getResponse().getHeaders("Set-Cookie")).isEmpty();
    }

    @Test void tokensAreSeparatedAndBrowserSessionCannotReplaceThem() throws Exception {
        mvc.perform(post(ACCEPT)).andExpect(status().isUnauthorized()).andExpect(jsonPath("$.error.code").value("UNAUTHENTICATED"));
        mvc.perform(post(ACCEPT).with(user("browser"))).andExpect(status().isUnauthorized());
        mvc.perform(post(ACCEPT).header("Authorization", "Bearer " + UUID.randomUUID())).andExpect(status().isUnauthorized());
        mvc.perform(post(ACCEPT).header("Authorization", "Bearer " + AI)).andExpect(status().isForbidden());
        mvc.perform(post(COMPLETE).header("Authorization", "Bearer " + PIPELINE)).andExpect(status().isForbidden());
        mvc.perform(post(COMPLETE)).andExpect(status().isUnauthorized());
        verifyNoInteractions(repository, client);
    }

    @Test void pipelineTypeAndUnknownFieldErrorsAreInvalidJson() throws Exception {
        for (String body : List.of("not-json", "[]", "{\"month\":202512}", "{\"month\":\"2025-12\",\"extra\":true}",
                "{\"month\":\"2025-12\",\"pipelineRunId\":123}", "{\"month\":\"2025-12\",\"reason\":0}")) {
            assert400(ACCEPT, PIPELINE, body, "INVALID_JSON");
        }
        verifyNoInteractions(repository, client);
    }

    @Test void pipelineValueErrorsAreValidationErrors() throws Exception {
        for (String body : List.of("{}", "{\"month\":null}", "{\"month\":\"2025-13\"}", "{\"month\":\"0000-01\"}",
                "{\"month\":\"2025-12\",\"reason\":\"UNKNOWN\"}", "{\"month\":\"2025-12\",\"pipelineRunId\":\" \"}",
                "{\"month\":\"2025-12\",\"pipelineRunId\":\"" + "😀".repeat(201) + "\"}")) {
            assert400(ACCEPT, PIPELINE, body, "VALIDATION_ERROR");
        }
        verifyNoInteractions(repository, client);
    }

    @Test void completionIsRepeatableAndValidatesTypesAndValues() throws Exception {
        String base = "{\"requestId\":\"local-1\",\"month\":\"2025-12\",\"savedCount\":0,\"failedDongCodes\":[]}";
        for (int i = 0; i < 2; i++) {
            var result = mvc.perform(post(COMPLETE).header("Authorization", "Bearer " + AI).contentType(MediaType.APPLICATION_JSON).content(base))
                    .andExpect(status().isNoContent()).andExpect(content().string("")).andReturn();
            assertThat(result.getResponse().getHeaders("Set-Cookie")).isEmpty();
        }
        for (String body : List.of(base.replace("\"savedCount\":0", "\"savedCount\":0.5"),
                base.replace("\"savedCount\":0", "\"savedCount\":\"0\""), base.replace("[]", "[1168064000]"),
                base.replace("[]}", "[],\"extra\":1}"), base.replace("\"local-1\"", "123"),
                base.replace("\"local-1\"", "{}"), base.replace("\"local-1\"", "[]"),
                base.replace("\"local-1\"", "true"))) assert400(COMPLETE, AI, body, "INVALID_JSON");
        for (String body : List.of("{}", base.replace("\"savedCount\":0", "\"savedCount\":-1"),
                base.replace("[]", "[\"123\"]"), base.replace("[]", "[null]"), base.replace("2025-12", "2025-13"),
                base.replace("\"local-1\"", "null"))) {
            assert400(COMPLETE, AI, body, "VALIDATION_ERROR");
        }
        verifyNoInteractions(repository, client);
    }

    @Test void reportLogsContainOnlyApprovedFieldsAndEscapeRequestId(CapturedOutput output) throws Exception {
        when(repository.reportTargets(any())).thenReturn(List.of("1168064000"));
        when(client.generate(any())).thenReturn(ReportGenerationClient.Admission.FAKE_ACCEPTED);
        mvc.perform(post(ACCEPT).header("Authorization", "Bearer " + PIPELINE).contentType(MediaType.APPLICATION_JSON)
                .content("{\"month\":\"2025-12\",\"pipelineRunId\":\"synthetic-omitted-run\",\"reason\":\"RESULT_RELOAD\"}"))
                .andExpect(status().isAccepted());
        mvc.perform(post(COMPLETE).header("Authorization", "Bearer " + AI).contentType(MediaType.APPLICATION_JSON)
                .content("{\"requestId\":\"local-1\\nsynthetic-line\",\"month\":\"2025-12\",\"savedCount\":0,\"failedDongCodes\":[\"1168066000\"]}"))
                .andExpect(status().isNoContent());
        assertThat(output.getOut()).contains("month=2025-12 targetCount=1 status=202",
                        "requestId=local-1_synthetic-line month=2025-12 status=204")
                .doesNotContain("pipelineRunId=", "reason=", "savedCount=", "failedDongCodes=", "exceptionType=",
                        "synthetic-omitted-run", "1168066000", "local-1\nsynthetic-line");
    }

    @Test void missingMonthIs404AndAiAdmissionFailureIs503() throws Exception {
        when(repository.reportTargets(any())).thenReturn(List.of());
        mvc.perform(post(ACCEPT).header("Authorization", "Bearer " + PIPELINE).contentType(MediaType.APPLICATION_JSON)
                .content("{\"month\":\"2025-12\"}")).andExpect(status().isNotFound());
        verifyNoInteractions(client);
        when(repository.reportTargets(any())).thenReturn(List.of("1168064000"));
        when(client.generate(any())).thenThrow(new ApiException(ErrorCode.AI_UNAVAILABLE));
        mvc.perform(post(ACCEPT).header("Authorization", "Bearer " + PIPELINE).contentType(MediaType.APPLICATION_JSON)
                .content("{\"month\":\"2025-12\"}")).andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.error.code").value("AI_UNAVAILABLE"));
        verify(client, times(1)).generate(any());
    }

    private void assert400(String path, String token, String body, String code) throws Exception {
        mvc.perform(post(path).header("Authorization", "Bearer " + token).contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.error.code").value(code));
    }
}
