package com.eumi.backend.auth.password;

import java.time.Clock;
import java.time.Duration;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import com.eumi.backend.common.mail.MailService;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class TempPasswordService {
    private static final DateTimeFormatter SEOUL_TIME = DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm:ss XXX '(서울)'")
            .withZone(ZoneId.of("Asia/Seoul"));
    private final TempPasswordRepository repository;
    private final PasswordChangeRepository sessions;
    private final TemporaryPasswordGenerator generator;
    private final PasswordEncoder passwords;
    private final MailService mail;
    private final Clock clock;
    private final TransactionTemplate transaction;

    public TempPasswordService(TempPasswordRepository repository, PasswordChangeRepository sessions,
            TemporaryPasswordGenerator generator, PasswordEncoder passwords, MailService mail,
            Clock clock, PlatformTransactionManager manager) {
        this.repository = repository; this.sessions = sessions; this.generator = generator;
        this.passwords = passwords; this.mail = mail; this.clock = clock;
        transaction = new TransactionTemplate(manager);
    }
    public void issue(TempPasswordRequest input) {
        var before = repository.findByEmail(input.email());
        // 조회 연결을 반환한 뒤 모든 유효 요청에서 PBKDF2를 정확히 한 번 수행한다.
        String raw = generator.generate();
        String hash = passwords.encode(raw);
        if (before.isEmpty() || !before.get().eligible(input, clock.instant())) return;

        transaction.executeWithoutResult(status -> {
            var current = repository.lockMember(before.get().memberId());
            var now = clock.instant();
            if (current.isEmpty() || !current.get().eligible(input, now)) return;
            var expires = now.plus(Duration.ofHours(24));
            repository.replacePassword(current.get().memberId(), hash, expires, now);
            sessions.deleteAllSessions(current.get().memberId());
            mail.sendPlainText(current.get().email(), "[이음이] 임시 비밀번호 안내",
                    "임시 비밀번호: " + raw + "\n만료 시각: " + SEOUL_TIME.format(expires)
                    + "\n발급 후 24시간 동안 유효합니다. 로그인 후 바로 비밀번호를 변경해 주세요.");
        });
    }
}
