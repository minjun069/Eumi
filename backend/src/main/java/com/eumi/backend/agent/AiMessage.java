package com.eumi.backend.agent;

import java.time.Instant;
import java.util.UUID;
import jakarta.persistence.*;
import org.hibernate.annotations.Immutable;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/** 추가 전용 테이블. SQL 저장과 함께 Hibernate validate로 물리 타입을 검증한다. */
@Entity
@Immutable
@Table(name = "ai_message")
public class AiMessage {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) @Column(name = "message_id") private Long id;
    @Column(name = "conversation_id", nullable = false) private UUID conversationId;
    @Column(name = "question_id") private Long questionId;
    @Column(name = "role", length = 10, nullable = false) private String role;
    @Column(name = "status", length = 10, nullable = false) private String status;
    @Column(name = "content", columnDefinition = "text") private String content;
    @Column(name = "details", columnDefinition = "text") private String details;
    @JdbcTypeCode(SqlTypes.JSON) @Column(name = "artifacts", columnDefinition = "jsonb") private String artifacts;
    @Column(name = "created_at", insertable = false, updatable = false) private Instant createdAt;
    protected AiMessage() { }
    public Long getId() { return id; }
    public String getStatus() { return status; }
    public String getContent() { return content; }
    public String getArtifacts() { return artifacts; }
}
