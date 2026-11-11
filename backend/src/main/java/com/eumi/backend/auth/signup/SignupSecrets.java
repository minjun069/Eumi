package com.eumi.backend.auth.signup;

import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import com.eumi.backend.config.AuthHashProperties;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

@Component
public class SignupSecrets {
    private final byte[] key;
    private final SecureRandom random;
    @Autowired public SignupSecrets(AuthHashProperties properties) {this(properties,new SecureRandom());}
    SignupSecrets(AuthHashProperties properties,SecureRandom random) {
        key=properties.getHashKey().getBytes(StandardCharsets.UTF_8);this.random=random;
    }
    public String code() {return String.format(Locale.ROOT,"%06d",random.nextInt(1_000_000));}
    public String proof() {byte[] bytes=new byte[32];random.nextBytes(bytes);return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);}
    public byte[] codeHash(String normalizedEmail,String code) {return hmac("code:"+normalizedEmail+":"+code);}
    public byte[] proofHash(String proof) {return hmac("proof:"+proof);}
    private byte[] hmac(String input) {
        try {
            Mac mac=Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key,"HmacSHA256"));
            return mac.doFinal(input.getBytes(StandardCharsets.UTF_8));
        } catch(GeneralSecurityException ex) {throw new IllegalStateException("Signup hash initialization failed");}
    }
    @Override public String toString() {return "SignupSecrets[redacted]";}
}
