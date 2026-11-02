package com.eumi.backend;

import com.eumi.backend.auth.csrf.CsrfController;
import com.eumi.backend.common.error.ApiErrorWriter;
import com.eumi.backend.common.security.ApiAccessDeniedHandler;
import com.eumi.backend.common.security.ApiAuthenticationEntryPoint;
import com.eumi.backend.common.web.RequestIdFilter;
import com.eumi.backend.config.SecurityConfig;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(controllers = CsrfController.class, properties = {
        "server.servlet.session.cookie.secure=true", "spring.test.mockmvc.print=none"})
@Import({SecurityConfig.class, ApiErrorWriter.class, ApiAuthenticationEntryPoint.class,
        ApiAccessDeniedHandler.class, RequestIdFilter.class})
class ProductionCsrfCookieTests {
    @Autowired MockMvc mvc;

    @Test
    void secureSettingAlsoAppliesToReadableCsrfCookie() throws Exception {
        var result = mvc.perform(get("/auth/csrf").secure(true)).andExpect(status().isNoContent()).andReturn();
        var cookie = result.getResponse().getCookie("XSRF-TOKEN");
        assertThat(cookie).isNotNull();
        assertThat(cookie.getSecure()).isTrue();
        assertThat(cookie.isHttpOnly()).isFalse();
        assertThat(cookie.getPath()).isEqualTo("/");
    }
}
