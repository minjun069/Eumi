package com.eumi.backend;

import java.time.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import com.eumi.backend.auth.password.*;
import com.eumi.backend.auth.login.LoginRequest;
import com.eumi.backend.common.error.*;
import com.eumi.backend.common.mail.MailService;
import jakarta.validation.Validation;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class TempPasswordTests {
    private static final Instant NOW = Instant.parse("2026-11-10T00:00:00Z");
    private final TempPasswordRepository repository = mock(TempPasswordRepository.class);
    private final PasswordChangeRepository sessions = mock(PasswordChangeRepository.class);
    private final PasswordEncoder passwords = mock(PasswordEncoder.class);
    private final MailService mail = mock(MailService.class);
    private final PlatformTransactionManager manager = mock(PlatformTransactionManager.class);
    private final List<String> operations = new ArrayList<>();
    private final AtomicInteger hashes = new AtomicInteger();
    private final TempPasswordRequest input = new TempPasswordRequest("member@eumi.test", "Synthetic member");
    private TempPasswordService service;

    @BeforeEach void setup() {
        service = new TempPasswordService(repository, sessions, new TemporaryPasswordGenerator(), passwords, mail,
                Clock.fixed(NOW, ZoneOffset.UTC), manager);
        when(manager.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        when(passwords.encode(anyString())).thenAnswer(call -> { hashes.incrementAndGet(); operations.add("hash"); return "synthetic-hash"; });
        doAnswer(call -> { operations.add("update"); return null; }).when(repository).replacePassword(anyLong(), anyString(), any(), any());
        doAnswer(call -> { operations.add("sessions"); return null; }).when(sessions).deleteAllSessions(anyLong());
        doAnswer(call -> { operations.add("mail"); return null; }).when(mail).sendPlainText(anyString(), anyString(), anyString());
        doAnswer(call -> { operations.add("commit"); return null; }).when(manager).commit(any());
    }
    private TempPasswordRepository.Member member(String name, Instant expires, boolean withdrawn) {
        return new TempPasswordRepository.Member(1, input.email(), name, expires, withdrawn);
    }
    @Test void generatorAlwaysSatisfiesTwelveCharacterContract() {
        var generator = new TemporaryPasswordGenerator();
        for (int i=0; i<100; i++) {
            String value = generator.generate();
            // 실패 메시지에도 생성한 비밀번호를 출력하지 않는다.
            assertThat(value.length() == 12).isTrue();
            assertThat(value.matches(".*[A-Z].*")).isTrue();
            assertThat(value.matches(".*[a-z].*")).isTrue();
            assertThat(value.matches(".*[2-9].*")).isTrue();
            assertThat(value.matches(".*[!@#$%^&*].*")).isTrue();
            assertThat(value.matches("[A-HJ-NP-Za-km-np-z2-9!@#$%^&*]{12}")).isTrue();
        }
    }
    @Test void requestNormalizesIdentityAndRedactsToString() {
        var value = new TempPasswordRequest("  MEMBER@EUMI.TEST  ", "  Synthetic Member  ");
        assertThat(value.email()).isEqualTo("member@eumi.test");
        assertThat(value.name()).isEqualTo("Synthetic Member");
        assertThat(value.toString()).isEqualTo("TempPasswordRequest[redacted]");
    }
    @ParameterizedTest @ValueSource(ints = {0x20,0x3000,0x01})
    void identityWhitespaceRulesMatchLoginTrim(int codePoint) {
        String padding = Character.toString(codePoint);
        String email = padding + "MEMBER@EUMI.TEST" + padding;
        var request = new TempPasswordRequest(email,padding + "Synthetic Member" + padding);
        var login = new LoginRequest(email,UUID.randomUUID().toString());
        String expectedEmail = codePoint == 0x3000 ? padding + "member@eumi.test" + padding : "member@eumi.test";
        String expectedName = codePoint == 0x3000 ? padding + "Synthetic Member" + padding : "Synthetic Member";
        assertThat(request.email()).isEqualTo(login.email()).isEqualTo(expectedEmail);
        assertThat(request.name()).isEqualTo(expectedName);
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            boolean emailValid = factory.getValidator().validate(request).stream()
                    .noneMatch(v -> v.getPropertyPath().toString().equals("email"));
            boolean loginEmailValid = factory.getValidator().validate(login).stream()
                    .noneMatch(v -> v.getPropertyPath().toString().equals("email"));
            assertThat(emailValid).isEqualTo(loginEmailValid);
        }
    }
    @ParameterizedTest @ValueSource(ints = {100,101})
    void nameLimitUsesCodePoints(int count) {
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            var violations = factory.getValidator().validate(new TempPasswordRequest("member@eumi.test", "😀".repeat(count)));
            assertThat(violations.isEmpty()).isEqualTo(count == 100);
        }
    }
    @ParameterizedTest @ValueSource(strings = {"missing","name","withdrawn","unexpired"})
    void ineligibleRequestHashesOnceAndDoesNotOpenTransaction(String reason) {
        var row = switch (reason) {
            case "missing" -> Optional.<TempPasswordRepository.Member>empty();
            case "name" -> Optional.of(member("Different", null, false));
            case "withdrawn" -> Optional.of(member(input.name(), null, true));
            default -> Optional.of(member(input.name(), NOW.plusSeconds(1), false));
        };
        when(repository.findByEmail(input.email())).thenReturn(row);
        service.issue(input);
        assertThat(hashes.get()).isEqualTo(1);
        assertThat(operations).containsExactly("hash");
        verifyNoInteractions(manager, sessions);
    }
    @ParameterizedTest @ValueSource(strings = {"missing","name","withdrawn","unexpired"})
    void eligibilityIsCheckedAgainAfterLock(String reason) {
        when(repository.findByEmail(input.email())).thenReturn(Optional.of(member(input.name(), null, false)));
        var row = switch (reason) {
            case "missing" -> Optional.<TempPasswordRepository.Member>empty();
            case "name" -> Optional.of(member("Changed", null, false));
            case "withdrawn" -> Optional.of(member(input.name(), null, true));
            default -> Optional.of(member(input.name(), NOW.plusSeconds(1), false));
        };
        when(repository.lockMember(1)).thenAnswer(call -> { operations.add("lock"); return row; });
        service.issue(input);
        assertThat(hashes.get()).isEqualTo(1);
        assertThat(operations).containsExactly("hash", "lock", "commit");
    }
    @Test void expiryBoundaryCanBeReissuedAndMailFollowsDatabaseAndSessionChanges() {
        when(repository.findByEmail(input.email())).thenReturn(Optional.of(member(input.name(), NOW, false)));
        when(repository.lockMember(1)).thenAnswer(call -> { operations.add("lock"); return Optional.of(member(input.name(), NOW, false)); });
        service.issue(input);
        assertThat(operations).containsExactly("hash", "lock", "update", "sessions", "mail", "commit");
        verify(repository).replacePassword(1, "synthetic-hash", NOW.plus(Duration.ofHours(24)), NOW);
    }
    @Test void mailFailureRequestsTransactionRollback() {
        when(repository.findByEmail(input.email())).thenReturn(Optional.of(member(input.name(), null, false)));
        when(repository.lockMember(1)).thenReturn(Optional.of(member(input.name(), null, false)));
        doThrow(new ApiException(ErrorCode.INTERNAL_SERVER_ERROR)).when(mail).sendPlainText(anyString(), anyString(), anyString());
        assertThatThrownBy(() -> service.issue(input)).isInstanceOfSatisfying(ApiException.class,
                ex -> assertThat(ex.code()).isEqualTo(ErrorCode.INTERNAL_SERVER_ERROR));
        verify(manager).rollback(any());
        verify(manager, never()).commit(any());
    }
}
