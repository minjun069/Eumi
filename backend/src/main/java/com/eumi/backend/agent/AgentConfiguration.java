package com.eumi.backend.agent;

import java.time.Clock;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(AgentProperties.class)
public class AgentConfiguration {
    @Bean
    Clock agentClock() { return Clock.systemUTC(); }

    @Bean(destroyMethod = "shutdownNow")
    ScheduledExecutorService agentScheduler() {
        return Executors.newScheduledThreadPool(4, Thread.ofPlatform().daemon(true).name("agent-", 0).factory());
    }
}
