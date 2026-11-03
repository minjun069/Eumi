package com.eumi.backend.reference;

public final class ReferenceDataDtos {
    private ReferenceDataDtos() { }

    public record SidoItem(String sidoCode, String sidoName) { }
    public record SigunguItem(String sigunguCode, String sigunguName) { }
    public record DongItem(String dongCode, String dongName) { }
    public record MemberOption(long memberId, String name, String title) { }
}
