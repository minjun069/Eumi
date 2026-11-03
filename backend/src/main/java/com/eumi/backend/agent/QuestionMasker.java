package com.eumi.backend.agent;

import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;

/** 회원·사례자 식별 항목의 명시 형식만 가린다. 질문 본문은 로그하지 않는다. */
@Component
public class QuestionMasker {
    private static final Pattern EMAIL = Pattern.compile("[\\w.%+\\-]+@[\\w.\\-]+\\.[A-Za-z]{2,}");
    private static final Pattern MOBILE = Pattern.compile("(?<!\\d)01[016789]-\\d{3,4}-\\d{4}(?!\\d)");
    private static final Pattern FIELD = Pattern.compile("(?<![\\p{L}\\p{N}_])"
            + "(이름|성명|성함|사례자명|회원명|생년월일)(\\h*[:：=]\\h*)([^;\\r\\n]+)");

    public String mask(String question) {
        String masked = FIELD.matcher(question).replaceAll(match -> {
            String value = match.group(3);
            if (value.isBlank()) return Matcher.quoteReplacement(match.group());
            String replacement = match.group(1).equals("생년월일") ? "[생년월일]" : "[이름]";
            String trailingSpace = value.substring(value.stripTrailing().length());
            return Matcher.quoteReplacement(match.group(1) + match.group(2) + replacement + trailingSpace);
        });
        masked = EMAIL.matcher(masked).replaceAll("[이메일]");
        return MOBILE.matcher(masked).replaceAll("[전화번호]");
    }
}
