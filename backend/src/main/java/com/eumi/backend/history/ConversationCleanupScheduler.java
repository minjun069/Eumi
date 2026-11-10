package com.eumi.backend.history;

import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;

@Configuration(proxyBeanMethods=false)
@EnableScheduling
public class ConversationCleanupScheduler {
    private final ConversationCleanupJob job;
    public ConversationCleanupScheduler(ConversationCleanupJob job) { this.job=job; }

    @Scheduled(cron="${eumi.batch.conversation-cleanup-cron:0 10 4 * * *}",zone="Asia/Seoul")
    public void execute() { job.run(); }
}
