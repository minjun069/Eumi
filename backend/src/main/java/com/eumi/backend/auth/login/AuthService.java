package com.eumi.backend.auth.login;

import java.time.Instant;
import java.util.UUID;

import com.eumi.backend.common.error.ApiException;
import com.eumi.backend.common.error.ErrorCode;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuthService {
    private final AuthMemberRepository members;
    private final PasswordEncoder passwords;
    private final String missingMemberHash;

    public AuthService(AuthMemberRepository members, PasswordEncoder passwords) {
        this.members = members;
        this.passwords = passwords;
        this.missingMemberHash = passwords.encode(UUID.randomUUID().toString());
    }

    // JDBC 조회가 커넥션을 반환한 뒤 비용이 큰 PBKDF2 비교를 수행한다.
    public LoginUser authenticate(LoginRequest request) {
        var member = members.findByEmail(request.email());
        boolean matches = matches(request.password(), member.map(AuthMemberRepository.Member::passwordHash)
                .orElse(missingMemberHash));
        if (!matches || member.isEmpty() || !member.get().canAuthenticate(Instant.now())) {
            throw new ApiException(ErrorCode.INVALID_CREDENTIALS);
        }
        return member.get().user();
    }

    @Transactional(readOnly = true)
    public LoginUser currentUser(long memberId) {
        return members.findById(memberId).filter(member -> member.canAuthenticate(Instant.now()))
                .map(AuthMemberRepository.Member::user)
                .orElseThrow(() -> new ApiException(ErrorCode.UNAUTHENTICATED));
    }

    private boolean matches(String raw, String hash) {
        try {
            return passwords.matches(raw, hash);
        } catch (IllegalArgumentException ex) {
            // 알 수 없는 인코더 식별자·잘못된 해시도 동일한 로그인 실패로 처리한다.
            return false;
        }
    }
}
