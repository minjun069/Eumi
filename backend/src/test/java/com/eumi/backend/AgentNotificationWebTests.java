package com.eumi.backend;

import java.util.UUID;
import com.eumi.backend.agent.*;
import com.eumi.backend.auth.session.SessionPrincipal;
import com.eumi.backend.common.error.*;
import com.eumi.backend.common.security.*;
import com.eumi.backend.common.web.RequestIdFilter;
import com.eumi.backend.config.SecurityConfig;
import com.eumi.backend.internal.InternalSecurityConfiguration;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(controllers = {AgentNotificationController.class, AgentController.class}, properties = "spring.test.mockmvc.print=none")
@Import({SecurityConfig.class, InternalSecurityConfiguration.class, ApiErrorWriter.class, ApiAuthenticationEntryPoint.class,
        ApiAccessDeniedHandler.class, GlobalExceptionHandler.class, RequestIdFilter.class})
class AgentNotificationWebTests {
    private static final String AI = UUID.randomUUID().toString(), PIPELINE = UUID.randomUUID().toString();
    private static final String PATH = "/internal/agent/notifications";
    @Autowired MockMvc mvc;
    @MockitoBean AgentLifecycle lifecycle;
    @MockitoBean AgentService service;
    @DynamicPropertySource static void tokens(DynamicPropertyRegistry registry) {
        registry.add("eumi.internal.ai-token", () -> AI); registry.add("eumi.internal.pipeline-token", () -> PIPELINE);
    }

    @Test void notificationIsStatelessAndHasEmpty204WithoutCsrf() throws Exception {
        UUID id = UUID.randomUUID();
        var result = mvc.perform(post(PATH).header("Authorization", "Bearer " + AI).contentType(MediaType.APPLICATION_JSON)
                .content("{\"conversationId\":\"" + id + "\",\"messageId\":102}"))
                .andExpect(status().isNoContent()).andExpect(content().string("")).andReturn();
        verify(lifecycle).notified(id, 102);
        assertThat(result.getRequest().getSession(false)).isNull();
        assertThat(result.getResponse().getHeaders("Set-Cookie")).isEmpty();
    }

    @Test void serviceTokensCannotBeReplacedByBrowserSessionOrCrossCallerToken() throws Exception {
        mvc.perform(post(PATH).with(user("browser"))).andExpect(status().isUnauthorized());
        mvc.perform(post(PATH).header("Authorization", "Bearer invalid")).andExpect(status().isUnauthorized());
        mvc.perform(post(PATH).header("Authorization", "Bearer " + PIPELINE)).andExpect(status().isForbidden());
        mvc.perform(post(PATH).header("Authorization", "Bearer " + AI, "Bearer " + PIPELINE)).andExpect(status().isUnauthorized());
        mvc.perform(post("/internal/analysis/unknown").header("Authorization", "Bearer " + PIPELINE))
                .andExpect(status().isForbidden());
        mvc.perform(post("/agent/questions").header("Authorization", "Bearer " + AI)).andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error.code").value("CSRF_INVALID"));
        verifyNoInteractions(lifecycle, service);
    }

    @Test void invalidNotificationsUseCommon400AndMissingAiRowUses404() throws Exception {
        String valid = "{\"conversationId\":\"" + UUID.randomUUID() + "\",\"messageId\":102}";
        for (String body : new String[]{"{}", valid.replace("102", "0"), valid.replace("102", "1.5"),
                valid.replace("102", "\"102\""), valid.replace("102", "null")}) {
            mvc.perform(post(PATH).header("Authorization", "Bearer " + AI).contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isBadRequest());
        }
        doThrow(new ApiException(ErrorCode.NOT_FOUND)).when(lifecycle).notified(any(), anyLong());
        mvc.perform(post(PATH).header("Authorization", "Bearer " + AI).contentType(MediaType.APPLICATION_JSON).content(valid))
                .andExpect(status().isNotFound()).andExpect(jsonPath("$.error.code").value("NOT_FOUND"));
    }

    @Test void contextIsOptionalAndMalformedContextFailsBeforeService() throws Exception {
        var principal = UsernamePasswordAuthenticationToken.authenticated(new SessionPrincipal(1, false), null, java.util.List.of());
        for (String context : new String[]{"{\"dongCode\":\"123\"}", "{\"dongCode\":1168064000}",
                "{\"month\":\"2025-13\"}", "{\"month\":\"0000-01\"}", "{\"unknown\":true}", "[]"}) {
            mvc.perform(post("/agent/questions").with(authentication(principal)).with(csrf()).contentType(MediaType.APPLICATION_JSON)
                    .content("{\"conversationId\":null,\"question\":\"Synthetic\",\"context\":" + context + "}"))
                    .andExpect(status().isBadRequest());
        }
        verifyNoInteractions(service);
        when(service.ask(eq(1L), any())).thenReturn(new AgentDtos.QuestionCreated(UUID.randomUUID(), 101));
        for (String extra : new String[]{"", ",\"context\":{}", ",\"context\":{\"dongCode\":\"1168064000\",\"month\":\"2025-12\"}"}) {
            mvc.perform(post("/agent/questions").with(authentication(principal)).with(csrf()).contentType(MediaType.APPLICATION_JSON)
                    .content("{\"conversationId\":null,\"question\":\"Synthetic\"" + extra + "}"))
                    .andExpect(status().isAccepted()).andExpect(jsonPath("$.data.questionId").value(101))
                    .andExpect(jsonPath("$.data.messageId").doesNotExist());
        }
    }
}
