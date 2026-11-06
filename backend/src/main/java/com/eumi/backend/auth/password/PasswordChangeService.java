package com.eumi.backend.auth.password;

import java.time.Clock;
import java.util.Objects;
import com.eumi.backend.auth.login.*;
import com.eumi.backend.common.error.*;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class PasswordChangeService {
    private final PasswordChangeRepository repository;
    private final PasswordEncoder passwords;
    private final AuthService auth;
    private final Clock clock;
    private final TransactionTemplate transaction;
    public PasswordChangeService(PasswordChangeRepository repository,PasswordEncoder passwords,AuthService auth,
            Clock clock,PlatformTransactionManager manager) {
        this.repository=repository;this.passwords=passwords;this.auth=auth;this.clock=clock;
        transaction=new TransactionTemplate(manager);
    }
    public LoginUser change(long member,String session,PasswordChangeRequest input) {
        var before=active(repository.account(member,false));
        // 조회 커넥션을 반환한 뒤 PBKDF2 비교·새 해시 생성을 수행한다.
        boolean matches=matches(input.currentPassword(),before.hash());
        if(!matches || before.temporaryExpired(clock.instant()))throw new ApiException(ErrorCode.CURRENT_PASSWORD_MISMATCH);
        if(matches(input.newPassword(),before.hash()))throw new ApiException(ErrorCode.NEW_PASSWORD_EQUALS_CURRENT);
        String hash=passwords.encode(input.newPassword());
        return transaction.execute(tx->{
            repository.lockOrganization(before.orgId());var current=active(repository.account(member,true));
            if(current.orgId()!=before.orgId())throw new ApiException(ErrorCode.FORBIDDEN);
            if(!Objects.equals(current.hash(),before.hash()) || current.temporaryExpired(clock.instant())) {
                throw new ApiException(ErrorCode.CURRENT_PASSWORD_MISMATCH);
            }
            if(!repository.lockCurrentSession(member,session,clock.instant()))throw new ApiException(ErrorCode.UNAUTHENTICATED);
            repository.changeHash(member,hash);repository.deleteOtherSessions(member,session);
            return auth.currentUser(member);
        });
    }
    private PasswordChangeRepository.Account active(java.util.Optional<PasswordChangeRepository.Account> account) {
        return account.filter(a->!a.withdrawn()).orElseThrow(()->new ApiException(ErrorCode.UNAUTHENTICATED));
    }
    private boolean matches(String raw,String hash) {
        try {return passwords.matches(raw,hash);}catch(IllegalArgumentException ex){return false;}
    }
}
