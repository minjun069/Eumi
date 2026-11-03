package com.eumi.backend.common.mail;

import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import com.eumi.backend.config.EumiMailProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.mail.MailException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.stereotype.Service;

@Service
public class MailService {
    private static final Logger log = LoggerFactory.getLogger(MailService.class);
    private final JavaMailSender sender;
    private final EumiMailProperties properties;

    public MailService(JavaMailSender sender, EumiMailProperties properties) {
        this.sender = sender;
        this.properties = properties;
    }

    /** SMTP 접수만 확인한다. DB 커밋과 최종 배달의 원자성을 보장하지 않는다. */
    public void sendPlainText(String recipient, String subject, String text) {
        var message = new SimpleMailMessage();
        message.setFrom(properties.getFrom());
        message.setTo(recipient);
        message.setSubject(subject);
        message.setText(text);
        try {
            sender.send(message);
        } catch (MailException ex) {
            // SMTP 예외 메시지·스택·메일 본문·수신자를 로그에 전달하지 않는다.
            log.error("Mail submission failed exceptionType={}", ex.getClass().getSimpleName());
            throw new ApiException(ErrorCode.INTERNAL_SERVER_ERROR);
        }
    }
}
