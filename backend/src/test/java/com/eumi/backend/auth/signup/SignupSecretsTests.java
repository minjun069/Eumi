package com.eumi.backend.auth.signup;

import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import java.util.concurrent.*;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import com.eumi.backend.config.AuthHashProperties;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class SignupSecretsTests {
    private AuthHashProperties key() {var p=new AuthHashProperties();p.setHashKey(UUID.randomUUID().toString());return p;}
    @Test void codeKeepsLeadingZerosAndProofIs32BytesWithoutPadding() {
        var random=mock(SecureRandom.class);when(random.nextInt(1_000_000)).thenReturn(0);
        var secrets=new SignupSecrets(key(),random);String code=secrets.code();
        assertThat(code.length()).isEqualTo(6);assertThat(code.codePoints().allMatch(c->c=='0')).isTrue();
        var real=new SignupSecrets(key());String proof=real.proof();
        assertThat(proof.length()).isEqualTo(43);assertThat(proof.matches("[A-Za-z0-9_-]{43}")).isTrue();
        assertThat(Base64.getUrlDecoder().decode(proof).length).isEqualTo(32);
    }
    @Test void hashesUseUtf8LabelsEmailBindingAndTheConfiguredKey() throws Exception {
        var properties=key();var secrets=new SignupSecrets(properties);
        String email=UUID.randomUUID()+"@"+UUID.randomUUID()+".test",code=secrets.code(),proof=secrets.proof();
        var mac=Mac.getInstance("HmacSHA256");mac.init(new SecretKeySpec(properties.getHashKey().getBytes(StandardCharsets.UTF_8),"HmacSHA256"));
        byte[] expected=mac.doFinal(("code:"+email+":"+code).getBytes(StandardCharsets.UTF_8));
        assertThat(MessageDigest.isEqual(expected,secrets.codeHash(email,code))).isTrue();
        assertThat(MessageDigest.isEqual(mac.doFinal(("proof:"+proof).getBytes(StandardCharsets.UTF_8)),secrets.proofHash(proof))).isTrue();
        assertThat(MessageDigest.isEqual(secrets.codeHash(email,code),secrets.codeHash(UUID.randomUUID()+email,code))).isFalse();
        assertThat(MessageDigest.isEqual(secrets.proofHash(proof),new SignupSecrets(key()).proofHash(proof))).isFalse();
        assertThat(secrets.codeHash(email,code).length).isEqualTo(32);
    }
    @Test void concurrentHashesDoNotShareMutableMacState() throws Exception {
        var secrets=new SignupSecrets(key());String value=secrets.proof();byte[] expected=secrets.proofHash(value);
        try(var executor=Executors.newFixedThreadPool(4)) {
            var jobs=new ArrayList<Future<Boolean>>();
            for(int i=0;i<40;i++) jobs.add(executor.submit(()->MessageDigest.isEqual(expected,secrets.proofHash(value))));
            for(var job:jobs) assertThat(job.get(3,TimeUnit.SECONDS)).isTrue();
        }
    }
}
