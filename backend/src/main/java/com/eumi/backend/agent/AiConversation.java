package com.eumi.backend.agent;

import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.Immutable;

/** 보관 일시는 DB 기본값·트리거가 관리한다. BE는 이 매핑을 통해 갱신하지 않는다. */
@Entity
@Immutable
@Table(name = "ai_conversation")
public class AiConversation {
    @Id @Column(name = "conversation_id") private UUID id;
    @Column(name = "member_id", nullable = false) private long memberId;
    @Column(name = "created_at", insertable = false, updatable = false) private Instant createdAt;
    @Column(name = "last_message_at", insertable = false, updatable = false) private Instant lastMessageAt;
    @Column(name = "delete_scheduled_at", insertable = false, updatable = false) private LocalDate deleteScheduledAt;
    protected AiConversation() { }
    public UUID getId() { return id; }
    public Instant getLastMessageAt() { return lastMessageAt; }
    public LocalDate getDeleteScheduledAt() { return deleteScheduledAt; }
}
