// ==========================================================================
// Eumi 배포 파이프라인 (Jenkins 잡: eumi-deploy)
//
// 트리거: GitLab master 브랜치 push (= develop → master MR 병합)
// 실행:   서버에 직접 설치된 Jenkins(jenkins 계정, docker 그룹)가 같은 서버에서 실행한다. ssh를 쓰지 않는다.
// 단계:   Plan → Sync → Build → Migrate → Deploy → Cleanup
//
// 사람이 손으로 배포 · 롤백할 때도 같은 스크립트(infra/scripts/*.sh)를 쓴다 (04 · 06 문서).
// 운영 비밀값은 서버 /srv/eumi/.env.config 에만 있다. 이 파일과 Jenkins에는 비밀값이 없다.
// Nginx 설정은 서버에 쓰지 않는다. 저장소와 다르면 빌드를 UNSTABLE(노란색)로 표시만 한다.
// ==========================================================================

pipeline {
    agent any

    options {
        disableConcurrentBuilds()          // 배포 중에 다른 배포를 시작하지 않는다
        timestamps()
        timeout(time: 40, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        APP_DIR = '/srv/eumi'
    }

    stages {

        // ---------- 1. 무엇을 배포할지 결정 ----------
        stage('Plan') {
            steps {
                script {
                    def sha = sh(returnStdout: true, script: 'git rev-parse --short=7 HEAD').trim()
                    env.TAG = "master-${sha}"

                    // 배포 순서: 의존받는 쪽 먼저 (ai · pipeline이 생기면 backend 앞에 추가)
                    def order = ['backend', 'web']
                    def dirs  = [backend: 'backend/', web: 'frontend/']
                    def services = order
                    def base = env.GIT_PREVIOUS_SUCCESSFUL_COMMIT

                    if (base && sh(returnStatus: true, script: "git cat-file -e ${base}^{commit}") == 0) {
                        def files = sh(returnStdout: true, script: "git diff --name-only ${base} HEAD").trim().readLines()
                        if (files.any { it.startsWith('infra/deploy/docker-compose.prod.yml') }) {
                            echo '운영 compose가 바뀌었다 — 모든 서비스를 다시 배포'
                        } else {
                            services = order.findAll { s -> files.any { f -> f.startsWith(dirs[s]) } }
                        }
                        echo "비교 기준: ${base}"
                    } else {
                        echo '비교 기준 없음(첫 빌드) — 전체 배포'
                    }

                    env.SERVICES = services.join(' ')
                    currentBuild.description = "${env.TAG} → [${env.SERVICES ?: '앱 변경 없음'}]"
                    echo "배포 계획: 태그 ${env.TAG}, 서비스 [${env.SERVICES}]"
                }
            }
        }

        // ---------- 2. 운영 파일을 /srv/eumi로 (비밀값 · 태그 · 백업은 건드리지 않음) ----------
        stage('Sync') {
            steps {
                sh 'bash infra/scripts/sync.sh "$WORKSPACE"'
                script {
                    def same = sh(returnStatus: true,
                                  script: 'cmp -s infra/deploy/nginx/eumi.conf /etc/nginx/sites-available/eumi') == 0
                    if (!same) {
                        unstable('Nginx 설정이 저장소(infra/deploy/nginx/eumi.conf)와 다릅니다. 인프라 담당이 서버에 직접 반영하세요 (06 문서 런북).')
                    }
                }
            }
        }

        // ---------- 3. 바뀐 서비스만 이미지 빌드 (서버 Docker에 저장 = 롤백 지점) ----------
        stage('Build') {
            when { expression { return env.SERVICES?.trim() ? true : false } }
            steps {
                script {
                    def ctx = [backend: 'backend', web: 'frontend']
                    env.SERVICES.tokenize(' ').each { s ->
                        sh "docker build -t eumi-${s}:${env.TAG} ${ctx[s]}"
                    }
                }
            }
        }

        // ---------- 4. 백업 + Flyway (매번 실행해도 안전, 실패하면 여기서 멈춤) ----------
        stage('Migrate') {
            steps {
                sh '"$APP_DIR/scripts/migrate.sh"'
            }
        }

        // ---------- 5. 서비스 교체 + 헬스체크 (실패하면 deploy.sh가 이전 태그로 되돌림) ----------
        stage('Deploy') {
            when { expression { return env.SERVICES?.trim() ? true : false } }
            steps {
                script {
                    env.SERVICES.tokenize(' ').each { s ->
                        sh "\"\$APP_DIR/scripts/deploy.sh\" ${s} ${env.TAG}"
                    }
                }
            }
        }

        // ---------- 6. 오래된 이미지 정리 (실패해도 배포 결과에는 영향 없음) ----------
        stage('Cleanup') {
            steps {
                catchError(buildResult: 'SUCCESS', stageResult: 'FAILURE') {
                    sh '"$APP_DIR/scripts/cleanup-images.sh"'
                }
            }
        }
    }

    post {
        success {
            echo "배포 완료: ${env.TAG} [${env.SERVICES}]"
        }
        unstable {
            echo "배포는 끝났지만 확인할 것이 있습니다 (노란색 단계의 메시지): ${env.TAG} [${env.SERVICES}]"
        }
        failure {
            echo '배포 실패: Migrate에서 멈췄다면 서비스는 바뀌지 않았고, Deploy에서 실패한 서비스는 이전 태그로 되돌아갔습니다. [migrate] · [deploy] 줄을 확인하세요.'
        }
    }
}
