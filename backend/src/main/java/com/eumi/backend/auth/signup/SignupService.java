package com.eumi.backend.auth.signup;

import java.security.MessageDigest;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import com.eumi.backend.common.error.*;
import com.eumi.backend.common.mail.MailService;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class SignupService {
    private static final Duration CODE_VALIDITY=Duration.ofMinutes(10),PROOF_VALIDITY=Duration.ofMinutes(10),RESEND_INTERVAL=Duration.ofSeconds(60);
    private static final int MAX_FAILURES=5;
    private static final DateTimeFormatter SEOUL_TIME=DateTimeFormatter.ofPattern("uuuu-MM-dd'T'HH:mm:ssxxx",Locale.ROOT).withZone(ZoneId.of("Asia/Seoul"));
    private final SignupRepository repository;
    private final SignupSecrets secrets;
    private final MailService mail;
    private final PasswordEncoder passwords;
    private final Clock clock;
    private final TransactionTemplate transaction;
    public SignupService(SignupRepository repository,SignupSecrets secrets,MailService mail,PasswordEncoder passwords,Clock clock,PlatformTransactionManager manager) {
        this.repository=repository;this.secrets=secrets;this.mail=mail;this.passwords=passwords;this.clock=clock;transaction=new TransactionTemplate(manager);
    }
    public List<SignupDtos.OrganizationSearchItem> organizations(String keyword) {
        keyword=keyword==null ? "" : keyword.trim();
        if(keyword.isEmpty() || keyword.codePointCount(0,keyword.length())>200) throw field("keyword");
        return repository.organizations(keyword);
    }
    public SignupDtos.VerificationSent send(SignupDtos.SendVerificationRequest input) {
        var org=repository.organization(input.orgId()).orElseThrow(()->field("orgId"));
        if(!input.email().substring(input.email().lastIndexOf('@')+1).equals(org.officialDomain())) throw new ApiException(ErrorCode.EMAIL_DOMAIN_MISMATCH);
        if(repository.memberExists(input.email())) throw new ApiException(ErrorCode.EMAIL_ALREADY_EXISTS);
        try {
            return transaction.execute(status->{
                var previous=repository.verification(input.email(),true);var now=clock.instant();
                if(repository.memberExists(input.email())) throw new ApiException(ErrorCode.EMAIL_ALREADY_EXISTS);
                if(previous.isPresent() && previous.get().createdAt().plus(RESEND_INTERVAL).isAfter(now)) throw new ApiException(ErrorCode.RATE_LIMITED);
                String code;byte[] hash;
                do {code=secrets.code();hash=secrets.codeHash(input.email(),code);}
                while(previous.isPresent() && MessageDigest.isEqual(previous.get().codeHash(),hash));
                var expires=now.plus(CODE_VALIDITY);
                repository.replaceVerification(previous.map(SignupRepository.Verification::id).orElse(null),input.orgId(),input.email(),hash,now,expires);
                mail.sendPlainText(input.email(),"[이음이] 가입 인증 코드","인증 코드: "+code+"\n10분 동안 유효합니다.\n만료 시각: "+SEOUL_TIME.format(expires)+" (서울)");
                return new SignupDtos.VerificationSent(SEOUL_TIME.format(expires));
            });
        } catch(DuplicateKeyException ex) {throw new ApiException(ErrorCode.RATE_LIMITED);}
    }
    public SignupDtos.VerificationTokenData verify(SignupDtos.VerifyCodeRequest input) {
        byte[] supplied=secrets.codeHash(input.email(),input.code());
        VerificationResult result=transaction.execute(status->{
            var found=repository.verification(input.email(),true);var now=clock.instant();
            if(found.isEmpty() || found.get().failedAttempts()>=MAX_FAILURES) return new VerificationResult(ErrorCode.VERIFICATION_INVALID,null);
            var row=found.get();
            if(!row.expiresAt().isAfter(now)) return new VerificationResult(ErrorCode.VERIFICATION_EXPIRED,null);
            if(!MessageDigest.isEqual(row.codeHash(),supplied)) {
                repository.failedAttempt(row.id());return new VerificationResult(ErrorCode.VERIFICATION_INVALID,null);
            }
            String proof;byte[] hash;
            do {proof=secrets.proof();hash=secrets.proofHash(proof);}
            while(row.proofHash()!=null && MessageDigest.isEqual(row.proofHash(),hash));
            repository.verify(row.id(),hash,now,now.plus(PROOF_VALIDITY));
            return new VerificationResult(null,proof);
        });
        // 실패 횟수도 같은 트랜잭션에서 커밋한 뒤 오류를 반환한다.
        if(result.error()!=null) throw new ApiException(result.error());
        return new SignupDtos.VerificationTokenData(result.proof());
    }
    private record VerificationResult(ErrorCode error,String proof) {
        @Override public String toString() {return "VerificationResult[redacted]";}
    }
    public SignupDtos.MemberCreated signup(SignupDtos.SignupRequest input) {
        byte[] supplied=secrets.proofHash(input.verificationToken());
        requireProof(repository.verification(input.email(),false),input.orgId(),supplied,clock.instant());
        if(repository.memberExists(input.email())) throw new ApiException(ErrorCode.EMAIL_ALREADY_EXISTS);
        String hash=passwords.encode(input.password());
        try {
            return transaction.execute(status->{
                var found=repository.verification(input.email(),true);var now=clock.instant();
                requireProof(found,input.orgId(),supplied,now);
                if(repository.memberExists(input.email())) throw new ApiException(ErrorCode.EMAIL_ALREADY_EXISTS);
                long id=repository.insertMember(input,hash,now);
                repository.deleteVerification(found.orElseThrow().id());
                return new SignupDtos.MemberCreated(id);
            });
        } catch(DuplicateKeyException ex) {throw new ApiException(ErrorCode.EMAIL_ALREADY_EXISTS);}
    }
    private void requireProof(Optional<SignupRepository.Verification> found,long org,byte[] supplied,Instant now) {
        if(found.isEmpty() || found.get().verifiedAt()==null || found.get().proofHash()==null || found.get().orgId()!=org
                || !MessageDigest.isEqual(found.get().proofHash(),supplied)) throw new ApiException(ErrorCode.PROOF_INVALID);
        if(found.get().proofExpiresAt()==null || !found.get().proofExpiresAt().isAfter(now)) throw new ApiException(ErrorCode.PROOF_EXPIRED);
    }
    private static ApiException field(String field) {return new ApiException(ErrorCode.VALIDATION_ERROR,List.of(new ApiErrorResponse.FieldError(field,"입력값을 확인해 주세요.")));}
}
