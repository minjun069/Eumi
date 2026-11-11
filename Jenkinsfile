// ==========================================================================
// Eumi 배포 파이프라인 (Jenkins 잡: eumi-deploy)
//
// 트리거: GitLab master 브랜치 push (= develop → master MR 병합)
// 실행:   서버에 직접 설치된 Jenkins(jenkins 계정, docker 그룹)가 같은 서버에서 실행한다. ssh를 쓰지 않는다.
// 단계:   Plan → Sync → Build → Migrate → Deploy → Pipeline → Monitoring → Cleanup
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
        timeout(time: 60, unit: 'MINUTES')   // pipeline 이미지를 처음 빌드할 때(Spark · Airflow 내려받기) 10~20분이 더 든다
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

                    // 앱 서비스 배포 순서: 의존받는 쪽 먼저. 데이터 파이프라인은 아래에서 따로 정한다 (앱 배포를 막지 않게 맨 뒤에)
                    def order = ['ai', 'backend', 'web']
                    def dirs  = [ai: 'ai/', backend: 'backend/', web: 'frontend/']
                    def services = order
                    def base = env.GIT_PREVIOUS_SUCCESSFUL_COMMIT
                    def files = null            // null = 비교 기준 없음(전체 배포)
                    def composeChanged = false

                    // ai/ 바로 아래 .md와 ai/docs/는 설명 문서라 ai를 다시 빌드하지 않는다
                    // (ai/src/instructions/*.md는 실행 중에 읽는 파일이라 바뀌면 빌드한다)
                    def isDoc = { String f -> f.matches('ai/[^/]+\\.md') || f.startsWith('ai/docs/') }

                    if (base && sh(returnStatus: true, script: "git cat-file -e ${base}^{commit}") == 0) {
                        files = sh(returnStdout: true, script: "git diff --name-only ${base} HEAD").trim().readLines()
                        composeChanged = files.any { it.startsWith('infra/deploy/docker-compose.prod.yml') }
                        if (composeChanged) {
                            echo '운영 compose가 바뀌었다 — 모든 서비스를 다시 배포'
                        } else {
                            services = order.findAll { s -> files.any { f -> f.startsWith(dirs[s]) && !isDoc(f) } }
                        }
                        echo "비교 기준: ${base}"
                    } else {
                        echo '비교 기준 없음(첫 빌드) — 전체 배포'
                    }

                    // ai는 이미지 정의(ai/Dockerfile)와 서버 코드(ai/api.py)가 둘 다 있을 때만 배포한다
                    if (!(fileExists('ai/Dockerfile') && fileExists('ai/api.py'))) {
                        if (services.contains('ai')) {
                            echo 'ai: ai/Dockerfile 또는 ai/api.py가 없어 이번에는 배포하지 않음'
                        }
                        services = services.findAll { it != 'ai' }
                    }

                    env.SERVICES = services.join(' ')

                    // 데이터 파이프라인 (minio · kafka · Airflow). data/(스크립트 · DAG)는 Sync가 복사해 마운트하므로 이미지를 다시 만들지 않는다
                    //   build   : infra/pipeline/(이미지 정의)이 바뀌었거나 아직 한 번도 배포하지 않았다 → 새 태그로 빌드 · 배포
                    //   reapply : compose만 바뀌었다 → 빌드 없이 지금 태그로 다시 적용 (바뀐 컨테이너만 다시 만들어진다)
                    def pipeTag = sh(returnStdout: true, script: 'grep -E "^PIPELINE_TAG=" "$APP_DIR/.env.tags" 2>/dev/null | cut -d= -f2- || true').trim()
                    def pipeDeployed = pipeTag.matches('(master|manual)-.+')
                    def pipeChanged = files == null || files.any { it.startsWith('infra/pipeline/') }
                    env.PIPELINE_CURRENT = pipeTag
                    env.PIPELINE = (!pipeDeployed || pipeChanged) ? 'build' : (composeChanged ? 'reapply' : '')

                    // Grafana 설정 파일이 바뀌었으면 다시 띄워야 알림 설정이 반영된다
                    env.GRAFANA_RESTART = (files != null && files.any { it.startsWith('infra/grafana/') }) ? 'yes' : ''

                    currentBuild.description = "${env.TAG} → [${env.SERVICES ?: '앱 변경 없음'}]" + (env.PIPELINE ? " + pipeline(${env.PIPELINE})" : '')
                    echo "배포 계획: 태그 ${env.TAG}, 서비스 [${env.SERVICES}], pipeline [${env.PIPELINE ?: '변경 없음'}]"
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
            when { expression { return (env.SERVICES?.trim() || env.PIPELINE == 'build') ? true : false } }
            steps {
                script {
                    def ctx = [ai: 'ai', backend: 'backend', web: 'frontend']
                    (env.SERVICES ?: '').tokenize(' ').each { s ->
                        sh "docker build -t eumi-${s}:${env.TAG} ${ctx[s]}"
                    }
                    // pipeline 이미지 빌드가 실패해도(내려받기 실패 등) 앱 배포는 계속한다. 빌드를 노란색으로 표시하고 이번에는 pipeline을 건너뛴다
                    if (env.PIPELINE == 'build') {
                        def built = false
                        catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE', message: 'pipeline 이미지 빌드 실패 — 이번 배포에서 pipeline을 건너뜁니다') {
                            sh "docker build -t eumi-pipeline:${env.TAG} infra/pipeline"
                            built = true
                        }
                        if (!built) { env.PIPELINE = '' }
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
                        if (s == 'ai') {
                            // ai가 실패하면 deploy.sh가 이전 ai로 되돌린다. backend · web 배포는 계속하고 빌드를 노란색으로 표시한다
                            catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {
                                sh "\"\$APP_DIR/scripts/deploy.sh\" ai ${env.TAG}"
                            }
                        } else {
                            sh "\"\$APP_DIR/scripts/deploy.sh\" ${s} ${env.TAG}"
                        }
                    }
                }
            }
        }

        // ---------- 6. 데이터 파이프라인 (실패하면 deploy.sh가 이전 태그로 되돌리고 빌드를 노란색으로 표시. 앱은 이미 배포됐다) ----------
        stage('Pipeline') {
            when { expression { return env.PIPELINE?.trim() ? true : false } }
            steps {
                script {
                    def tag = (env.PIPELINE == 'build') ? env.TAG : env.PIPELINE_CURRENT
                    catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE', message: 'pipeline 배포 실패 — [deploy] 줄을 확인하세요') {
                        sh "\"\$APP_DIR/scripts/deploy.sh\" pipeline ${tag}"
                    }
                }
            }
        }

        // ---------- 7. Grafana (공식 이미지라 태그가 없다. 비밀값 · DB 계정이 아직 없으면 건너뛴다. 바뀐 게 없으면 그대로 둔다) ----------
        stage('Monitoring') {
            steps {
                script {
                    def opt = env.GRAFANA_RESTART ? ' --restart' : ''
                    catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE', message: 'Grafana가 정상으로 뜨지 않았습니다 — [grafana] 줄을 확인하세요') {
                        sh "\"\$APP_DIR/scripts/grafana.sh\" --skip-if-unconfigured${opt}"
                    }
                }
            }
        }

        // ---------- 8. 오래된 이미지 정리 (실패해도 배포 결과에는 영향 없음) ----------
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
