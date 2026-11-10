package com.eumi.backend;

import java.util.*;
import com.eumi.backend.auth.signup.SignupDtos.*;
import jakarta.validation.*;
import org.junit.jupiter.api.*;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.*;

class SignupRequestTests {
    private static ValidatorFactory factory;
    private final JsonMapper json=JsonMapper.builder().build();
    private final String email=UUID.randomUUID()+"@"+UUID.randomUUID()+".test";
    private final String proof=UUID.randomUUID().toString(),password=UUID.randomUUID()+"Aa1!";
    @BeforeAll static void setup() {factory=Validation.buildDefaultValidatorFactory();}
    @AfterAll static void close() {factory.close();}
    private SignupRequest request(String name,String rawPassword,String title,String phone) {return new SignupRequest(proof,1L,email,name,rawPassword,title,phone);}
    @Test void emailAndNameNormalizeButPasswordAndPhoneDoNot() {
        var input=new SignupRequest(proof,1L,"  "+email.toUpperCase(Locale.ROOT)+"  ","  Synthetic  "," "+password+" ","  ",null);
        assertThat(input.email().equals(email)).isTrue();assertThat(input.name()).isEqualTo("Synthetic");
        assertThat(input.password().equals(" "+password+" ")).isTrue();assertThat(input.title()).isNull();
        assertThat(factory.getValidator().validate(input)).isEmpty();
        assertThat(factory.getValidator().validate(request("Synthetic",password,null,""))).isNotEmpty();
    }
    @Test void unicodeLimitsAndPasswordRulesMatchTheContract() {
        assertThat(factory.getValidator().validate(request("😀".repeat(100),password,"😀".repeat(100),null))).isEmpty();
        assertThat(factory.getValidator().validate(request("😀".repeat(101),password,"😀".repeat(101),null)).size()).isEqualTo(2);
        for(String invalid:List.of("a".repeat(8),"1".repeat(8),UUID.randomUUID().toString().replace("-",""),"A1!".repeat(43))) {
            assertThat(factory.getValidator().validate(request("Synthetic",invalid,null,null)).isEmpty()).isFalse();
        }
    }
    @Test void allSensitiveRequestStringsAndProofResponsesAreRedacted() {
        String code=String.format(Locale.ROOT,"%06d",new java.security.SecureRandom().nextInt(1_000_000));
        assertThat(new SendVerificationRequest(1L,email).toString().contains(email)).isFalse();
        assertThat(new VerifyCodeRequest(email,code).toString().contains(code)).isFalse();
        var input=request("Synthetic",password,null,null);
        assertThat(input.toString().contains(email)||input.toString().contains(password)||input.toString().contains(proof)).isFalse();
        assertThat(new VerificationTokenData(proof).toString().contains(proof)).isFalse();
    }
    @Test void jsonScalarsCannotBeCoercedAndUnknownFieldsAreRejected() {
        for(Object value:List.of(123,true,List.of("Synthetic"),Map.of("name","Synthetic"))) {
            var input=new HashMap<String,Object>();input.put("orgId",1);input.put("email",value);
            boolean rejected=false;try {json.readValue(json.writeValueAsString(input),SendVerificationRequest.class);} catch(RuntimeException ex) {rejected=true;}
            assertThat(rejected).isTrue();
        }
        var extra=Map.of("orgId",1,"email",email,"unknown",true);
        boolean rejected=false;try {json.readValue(json.writeValueAsString(extra),SendVerificationRequest.class);} catch(RuntimeException ex) {rejected=true;}
        assertThat(rejected).isTrue();
        var id=Map.of("orgId","1","email",email);
        rejected=false;try {json.readValue(json.writeValueAsString(id),SendVerificationRequest.class);} catch(RuntimeException ex) {rejected=true;}
        assertThat(rejected).isTrue();
    }
}
