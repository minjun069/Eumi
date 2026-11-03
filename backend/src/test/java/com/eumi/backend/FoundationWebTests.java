package com.eumi.backend;

import java.time.OffsetDateTime;
import java.util.UUID;

import com.eumi.backend.auth.csrf.CsrfController;
import com.eumi.backend.auth.session.SessionAuthenticationSupport;
import com.eumi.backend.auth.session.SessionPrincipal;
import com.eumi.backend.common.HealthController;
import com.eumi.backend.common.error.ApiErrorWriter;
import com.eumi.backend.common.error.ApiErrorController;
import com.eumi.backend.common.error.GlobalExceptionHandler;
import com.eumi.backend.common.security.ApiAccessDeniedHandler;
import com.eumi.backend.common.security.ApiAuthenticationEntryPoint;
import com.eumi.backend.common.web.RequestIdFilter;
import com.eumi.backend.config.SecurityConfig;
import com.eumi.backend.support.FoundationFixture;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.DispatcherType;
import jakarta.servlet.RequestDispatcher;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import tools.jackson.databind.json.JsonMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.authentication;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(controllers = {HealthController.class, CsrfController.class, ApiErrorController.class},
        properties = "spring.test.mockmvc.print=none")
@Import({SecurityConfig.class, SessionAuthenticationSupport.class, ApiErrorWriter.class,
        ApiAuthenticationEntryPoint.class, ApiAccessDeniedHandler.class, RequestIdFilter.class,
        GlobalExceptionHandler.class, FoundationFixture.class})
class FoundationWebTests {
    @Autowired MockMvc mvc;
    @Autowired JsonMapper mapper;

    @Test
    void healthRetainsOriginalBody() throws Exception {
        mvc.perform(get("/health")).andExpect(status().isOk())
                .andExpect(content().json("{\"status\":\"UP\"}"))
                .andExpect(jsonPath("$.success").doesNotExist());
    }

    @Test
    void protectedPathsReturnJson401AndNeverRedirect() throws Exception {
        for (String path : new String[]{"/auth/me", "/regions/sidos", "/organizations/me/members", "/members/me"}) {
            var result = mvc.perform(get(path)).andExpect(status().isUnauthorized())
                    .andExpect(header().doesNotExist("Location"))
                    .andExpect(jsonPath("$.error.code").value("UNAUTHENTICATED")).andReturn();
            assertMeta(result);
        }
    }

    @Test
    void csrfEndpointIssuesReadableRootCookieAndEmpty204() throws Exception {
        var result = mvc.perform(get("/auth/csrf")).andExpect(status().isNoContent())
                .andExpect(content().string("")).andExpect(header().string("Cache-Control", "no-store"))
                .andReturn();
        Cookie cookie = result.getResponse().getCookie("XSRF-TOKEN");
        assertThat(cookie).isNotNull();
        assertThat(cookie.getValue()).isNotBlank();
        assertThat(cookie.getPath()).isEqualTo("/");
        assertThat(cookie.isHttpOnly()).isFalse();
        assertThat(cookie.getSecure()).isFalse();
        assertThat(cookie.getAttribute("SameSite")).isEqualTo("Lax");
        assertThat(cookie.getDomain()).isNull();
        assertThat(result.getResponse().getCookie("SESSION")).isNull();
    }

    @Test
    void publicMutationsStillRequireCsrf() throws Exception {
        for (String path : new String[]{"/auth/login", "/auth/logout", "/auth/temp-password",
                "/members", "/signup/email-verifications", "/signup/email-verifications/verify"}) {
            var result = mvc.perform(post(path)).andExpect(status().isForbidden())
                    .andExpect(jsonPath("$.error.code").value("CSRF_INVALID")).andReturn();
            assertMeta(result);
        }
    }

    @Test
    void rawCookieHeaderPassesSpaCsrfAndWrongHeaderFails() throws Exception {
        var prepared = mvc.perform(get("/auth/csrf")).andReturn();
        Cookie cookie = prepared.getResponse().getCookie("XSRF-TOKEN");
        mvc.perform(post("/signup/email-verifications/verify").cookie(cookie)
                        .header("X-XSRF-TOKEN", cookie.getValue())
                        .contentType(MediaType.APPLICATION_JSON).content("{\"name\":\"fixture\"}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.success").value(true));
        mvc.perform(post("/signup/email-verifications/verify").cookie(cookie)
                        .header("X-XSRF-TOKEN", "wrong-token")
                        .contentType(MediaType.APPLICATION_JSON).content("{\"name\":\"fixture\"}"))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.error.code").value("CSRF_INVALID"));
    }

    @Test
    void invalidJsonAndValidationUseContractWithoutRejectedValue() throws Exception {
        var invalid = mvc.perform(post("/signup/email-verifications/verify").with(rawCsrf())
                        .contentType(MediaType.APPLICATION_JSON).content("{secret-invalid-json"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.error.code").value("INVALID_JSON"))
                .andReturn();
        assertThat(invalid.getResponse().getContentAsString()).doesNotContain("secret-invalid-json");
        assertMeta(invalid);
        var fields = mvc.perform(post("/signup/email-verifications/verify").with(rawCsrf())
                        .contentType(MediaType.APPLICATION_JSON).content("{\"name\":\"\"}"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"))
                .andExpect(jsonPath("$.error.fieldErrors[0].field").value("name"))
                .andExpect(jsonPath("$.error.fieldErrors[0].reason").isNotEmpty()).andReturn();
        assertMeta(fields);
    }

    @Test
    void mvcForbiddenAndInternalErrorUseSafeResponses() throws Exception {
        var denied = mvc.perform(get("/fixture/forbidden").with(user("fixture")))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.error.code").value("FORBIDDEN"))
                .andReturn();
        assertMeta(denied);
        var failure = mvc.perform(get("/fixture/failure").with(user("fixture")))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.error.code").value("INTERNAL_SERVER_ERROR")).andReturn();
        assertThat(failure.getResponse().getContentAsString()).doesNotContain("SQL", "password", "secret-code");
        assertMeta(failure);
    }

    @Test
    void successAndNoContentKeepTheirRespectiveContracts() throws Exception {
        var success = mvc.perform(post("/signup/email-verifications/verify").with(rawCsrf())
                        .contentType(MediaType.APPLICATION_JSON).content("{\"name\":\"fixture\"}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.name").value("fixture")).andReturn();
        assertMeta(success);
        mvc.perform(get("/fixture/empty").with(user("fixture")))
                .andExpect(status().isNoContent()).andExpect(content().string(""));
    }

    @Test
    void restrictedSessionCanRestoreButCannotReadBusinessEndpoints() throws Exception {
        var restricted = org.springframework.security.authentication.UsernamePasswordAuthenticationToken
                .authenticated(new SessionPrincipal(910000002L, true), null, java.util.List.of());
        mvc.perform(get("/auth/me").with(authentication(restricted)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data").value("910000002"));
        mvc.perform(get("/regions/sidos").with(authentication(restricted)))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error.code").value("PASSWORD_CHANGE_REQUIRED"));
        mvc.perform(post("/auth/logout").with(authentication(restricted)).with(rawCsrf()))
                .andExpect(status().isNotFound()); // A1 컨트롤러는 아직 없지만 보안 경계는 통과한다.
        mvc.perform(put("/members/me/password").with(authentication(restricted)).with(rawCsrf()))
                .andExpect(status().isNotFound()); // A3 컨트롤러 구현과 구분한다.
    }

    @Test
    void servletErrorDispatchUsesJsonEvenWhenHtmlIsRequested() throws Exception {
        mvc.perform(get("/error").with(request -> { request.setDispatcherType(DispatcherType.ERROR); return request; })
                        .requestAttr(RequestDispatcher.ERROR_STATUS_CODE, 500)
                        .requestAttr(RequestDispatcher.ERROR_MESSAGE, "SQL secret fixture")
                        .accept(MediaType.TEXT_HTML))
                .andExpect(status().isInternalServerError())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.error.code").value("INTERNAL_SERVER_ERROR"));
    }

    private org.springframework.test.web.servlet.request.RequestPostProcessor rawCsrf() throws Exception {
        var prepared = mvc.perform(get("/auth/csrf")).andReturn();
        Cookie cookie = prepared.getResponse().getCookie("XSRF-TOKEN");
        return request -> {
            request.setCookies(cookie);
            request.addHeader("X-XSRF-TOKEN", cookie.getValue());
            return request;
        };
    }

    private void assertMeta(MvcResult result) throws Exception {
        var json = mapper.readTree(result.getResponse().getContentAsString());
        String id = json.path("meta").path("requestId").asText();
        UUID.fromString(id);
        OffsetDateTime.parse(json.path("meta").path("timestamp").asText());
        assertThat(result.getResponse().getHeader("X-Request-Id")).isEqualTo(id);
        assertThat(result.getResponse().getHeader("Cache-Control")).isEqualTo("no-store");
    }
}
