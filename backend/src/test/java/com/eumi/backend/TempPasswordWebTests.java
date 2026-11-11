package com.eumi.backend;

import com.eumi.backend.auth.password.*;
import com.eumi.backend.auth.session.SessionPrincipal;
import com.eumi.backend.common.error.*;
import com.eumi.backend.common.security.*;
import com.eumi.backend.common.web.RequestIdFilter;
import com.eumi.backend.config.SecurityConfig;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(controllers = TempPasswordController.class, properties = "spring.test.mockmvc.print=none")
@Import({SecurityConfig.class, ApiErrorWriter.class, ApiAuthenticationEntryPoint.class, ApiAccessDeniedHandler.class,
        RequestIdFilter.class, GlobalExceptionHandler.class})
class TempPasswordWebTests {
    @Autowired MockMvc mvc;
    @MockitoBean TempPasswordService service;
    private static final String PATH = "/auth/temp-password";
    private static final String INPUT = "{\"email\":\" MEMBER@EUMI.TEST \",\"name\":\" Synthetic member \"}";

    @Test void anonymousRequestWithCsrfReturnsEmpty204AndNormalizedIdentity() throws Exception {
        mvc.perform(post(PATH).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(INPUT))
                .andExpect(status().isNoContent()).andExpect(content().string(""));
        verify(service).issue(new TempPasswordRequest("member@eumi.test", "Synthetic member"));
    }
    @Test void typeAndUnknownFieldErrorsAreInvalidJson() throws Exception {
        for (String input : java.util.List.of("not-json", "[]", "{}", "{\"email\":123,\"name\":\"Synthetic\"}",
                "{\"email\":\"member@eumi.test\",\"name\":true}", INPUT.substring(0, INPUT.length()-1) + ",\"extra\":1}")) {
            invalid(input, "INVALID_JSON");
        }
        verifyNoInteractions(service);
    }
    @Test void invalidIdentityIsValidationError() throws Exception {
        for (String input : java.util.List.of("{\"email\":null,\"name\":\"Synthetic\"}",
                "{\"email\":\"not-email\",\"name\":\"Synthetic\"}", "{\"email\":\"member@eumi.test\",\"name\":\"  \"}",
                "{\"email\":\"member@eumi.test\",\"name\":\"" + "😀".repeat(101) + "\"}")) invalid(input, "VALIDATION_ERROR");
        verifyNoInteractions(service);
    }
    @Test void csrfAndExistingTemporaryPasswordSessionRulesArePreserved() throws Exception {
        mvc.perform(post(PATH).contentType(MediaType.APPLICATION_JSON).content(INPUT))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.error.code").value("CSRF_INVALID"));
        var restricted = UsernamePasswordAuthenticationToken.authenticated(new SessionPrincipal(1, true), null, java.util.List.of());
        mvc.perform(post(PATH).with(csrf()).with(authentication(restricted)).contentType(MediaType.APPLICATION_JSON).content(INPUT))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.error.code").value("PASSWORD_CHANGE_REQUIRED"));
        verifyNoInteractions(service);
    }
    private void invalid(String input, String code) throws Exception {
        var result = mvc.perform(post(PATH).with(csrf()).contentType(MediaType.APPLICATION_JSON).content(input))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.error.code").value(code)).andReturn();
        assertThat(result.getResponse().getHeader("Cache-Control")).isEqualTo("no-store");
    }
}
