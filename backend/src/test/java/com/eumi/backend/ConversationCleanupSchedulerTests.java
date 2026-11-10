package com.eumi.backend;

import java.time.*;
import com.eumi.backend.history.*;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.scheduling.annotation.ScheduledAnnotationBeanPostProcessor;
import org.springframework.scheduling.config.CronTask;
import org.springframework.scheduling.support.SimpleTriggerContext;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.mock;

class ConversationCleanupSchedulerTests {
    private final ApplicationContextRunner runner=new ApplicationContextRunner()
            .withUserConfiguration(ConversationCleanupScheduler.class)
            .withBean(ConversationCleanupJob.class,()->mock(ConversationCleanupJob.class));

    @Test void defaultCronRunsAt0410Seoul() {
        runner.run(context->{
            assertThat(context).hasNotFailed();
            var tasks=context.getBean(ScheduledAnnotationBeanPostProcessor.class).getScheduledTasks();assertThat(tasks).hasSize(1);
            var task=(CronTask)tasks.iterator().next().getTask();
            var clock=Clock.fixed(Instant.parse("2026-11-10T15:30:00Z"),ZoneOffset.UTC);
            assertThat(task.getTrigger().nextExecution(new SimpleTriggerContext(clock))).isEqualTo(Instant.parse("2026-11-10T19:10:00Z"));
        });
    }
    @Test void dashDisablesRegistration() {
        runner.withPropertyValues("eumi.batch.conversation-cleanup-cron=-").run(context->{
            assertThat(context).hasNotFailed();
            assertThat(context.getBean(ScheduledAnnotationBeanPostProcessor.class).getScheduledTasks()).isEmpty();
        });
    }
}
