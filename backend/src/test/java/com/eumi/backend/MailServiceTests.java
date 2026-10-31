package com.eumi.backend;

import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import com.eumi.backend.common.mail.MailService;
import com.eumi.backend.config.EumiMailProperties;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.mail.MailSendException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowableOfType;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(OutputCaptureExtension.class)
class MailServiceTests {
    @Test
    void smtpFailureDoesNotExposeOriginalExceptionOrMessage(CapturedOutput output) {
        JavaMailSender sender = mock(JavaMailSender.class);
        doThrow(new MailSendException("fixture-smtp-secret")).when(sender).send(any(SimpleMailMessage.class));
        var properties = new EumiMailProperties();
        properties.setFrom("no-reply@eumi.test");
        var service = new MailService(sender, properties);

        ApiException failure = catchThrowableOfType(ApiException.class,
                () -> service.sendPlainText("recipient@eumi.test", "fixture-subject", "fixture-code-secret"));
        assertThat(failure.code()).isEqualTo(ErrorCode.INTERNAL_SERVER_ERROR);
        assertThat(failure.getCause()).isNull();
        assertThat(output.getAll()).doesNotContain("fixture-smtp-secret", "fixture-code-secret", "recipient@eumi.test");
    }
}
