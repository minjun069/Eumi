pipeline {
    agent any

    stages {
        stage('Check Repository') {
            steps {
                echo 'GitLab 저장소 연결에 성공했습니다.'
                sh 'git log -1 --oneline'
            }
        }
    }
}