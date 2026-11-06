package com.eumi.backend.mypage;

import java.util.*;
import com.eumi.backend.common.error.*;
import com.eumi.backend.resources.ResourceDtos;
import tools.jackson.databind.JsonNode;

public final class MyDtos {
    private MyDtos() { }
    public record MyInfo(String name,String email,String orgName,String jurisdictionName,String title,String phone) { }
    public record MyResources(long totalCount,List<ResourceDtos.ListItem> items) { }

    /** 값의 null 여부와 필드의 존재 여부를 따로 보관해 생략한 필드를 덮어쓰지 않는다. */
    public record Patch(boolean titlePresent,String title,boolean phonePresent,String phone) {
        public static Patch parse(JsonNode body) {
            if(body==null || !body.isObject()) throw new ApiException(ErrorCode.INVALID_JSON);
            if(body.properties().stream().anyMatch(p->!Set.of("title","phone").contains(p.getKey()))) {
                throw new ApiException(ErrorCode.INVALID_JSON);
            }
            if(body.isEmpty()) throw new ApiException(ErrorCode.VALIDATION_ERROR);
            String title=text(body,"title"),phone=text(body,"phone");
            if(title!=null) { title=title.trim();if(title.isEmpty())title=null; }
            if(phone!=null) phone=phone.trim();
            var fields=new ArrayList<ApiErrorResponse.FieldError>();
            if(title!=null && title.codePointCount(0,title.length())>100) fields.add(field("title"));
            if(phone!=null && !phone.matches("01[016789]-[0-9]{3,4}-[0-9]{4}")) fields.add(field("phone"));
            if(!fields.isEmpty()) throw new ApiException(ErrorCode.VALIDATION_ERROR,fields);
            return new Patch(body.has("title"),title,body.has("phone"),phone);
        }
        private static String text(JsonNode body,String key) {
            var value=body.get(key);if(value==null || value.isNull())return null;
            if(!value.isString())throw new ApiException(ErrorCode.INVALID_JSON);
            return value.asText();
        }
        private static ApiErrorResponse.FieldError field(String name) {
            return new ApiErrorResponse.FieldError(name,"입력값을 확인해 주세요.");
        }
        @Override public String toString() {return "MyInfoPatch[redacted]";}
    }
}
