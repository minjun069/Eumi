import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Map;

import org.springframework.security.crypto.password.DelegatingPasswordEncoder;
import org.springframework.security.crypto.password.Pbkdf2PasswordEncoder;

/** java --class-path <spring-security-crypto.jar> scripts/GeneratePasswordHash.java */
class GeneratePasswordHash {
    public static void main(String[] args) throws Exception {
        char[] password;
        if (args.length == 1 && args[0].equals("--stdin")) {
            password = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))
                    .readLine().toCharArray();
        } else {
            if (System.console() == null) {
                throw new IllegalStateException("Run in a terminal for hidden password input, or pipe with --stdin.");
            }
            password = System.console().readPassword("Password (hidden): ");
        }
        try {
            int length = Character.codePointCount(password, 0, password.length);
            if (length < 8 || length > 128) throw new IllegalArgumentException("Password must be 8-128 code points.");
            var encoder = new DelegatingPasswordEncoder("pbkdf2",
                    Map.of("pbkdf2", Pbkdf2PasswordEncoder.defaultsForSpringSecurity_v5_8()));
            System.out.println(encoder.encode(new String(password)));
        } finally {
            Arrays.fill(password, '\0');
        }
    }
}
