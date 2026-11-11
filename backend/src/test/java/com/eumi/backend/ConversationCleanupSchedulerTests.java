package com.eumi.backend;

import java.time.*;
import java.util.Map;
import com.eumi.backend.history.*;
import com.eumi.backend.support.CleanupSchedulingTestEnvironmentPostProcessor;
import org.junit.jupiter.api.Test;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.core.env.SystemEnvironmentPropertySource;
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
        runner.withInitializer(context->{
            // 기본값 검사는 이 프로세스에 전달된 운영용 cron과 독립적으로 한다.
            var sources=context.getEnvironment().getPropertySources();
            sources.remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
            sources.remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
        }).run(context->{
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
    @Test void testGuardOverridesAnEnabledEnvironmentCron() {
        runner.withInitializer(context->{
            var environment=context.getEnvironment();
            environment.getPropertySources().addFirst(new SystemEnvironmentPropertySource("enabledCleanupEnvironment",
                    Map.of("EUMI_BATCH_CONVERSATION_CLEANUP_CRON","* * * * * *")));
            assertThat(environment.getProperty("eumi.batch.conversation-cleanup-cron")).isEqualTo("* * * * * *");
            new CleanupSchedulingTestEnvironmentPostProcessor().postProcessEnvironment(environment,new SpringApplication());
        }).run(context->{
            assertThat(context).hasNotFailed();
            assertThat(context.getEnvironment().getProperty("eumi.batch.conversation-cleanup-cron")).isEqualTo("-");
            assertThat(context.getBean(ScheduledAnnotationBeanPostProcessor.class).getScheduledTasks()).isEmpty();
        });
    }
}
