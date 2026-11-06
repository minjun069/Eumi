#Requires -Version 7.0
param([string]$BaseUrl = 'http://localhost:8080/api')

$ErrorActionPreference = 'Stop'
$taskBaseUri = [Uri]$BaseUrl
if (-not $taskBaseUri.IsLoopback) { throw '이 검사는 로컬 서버를 대상으로 실행합니다.' }
$taskHandler = [System.Net.Http.HttpClientHandler]::new()
$taskHandler.UseProxy = $false
$taskHandler.CookieContainer = [System.Net.CookieContainer]::new()
$taskClient = [System.Net.Http.HttpClient]::new($taskHandler)
$taskClient.Timeout = [TimeSpan]::FromSeconds(5)

function Invoke-FoundationRequest([string]$Method, [string]$Path, [hashtable]$Headers = @{}) {
    $taskRequest = [System.Net.Http.HttpRequestMessage]::new(
        [System.Net.Http.HttpMethod]::new($Method), "$($BaseUrl.TrimEnd('/'))$Path")
    foreach ($taskName in $Headers.Keys) {
        [void]$taskRequest.Headers.TryAddWithoutValidation($taskName, [string]$Headers[$taskName])
    }
    $taskResponse = $taskClient.SendAsync($taskRequest).GetAwaiter().GetResult()
    [pscustomobject]@{
        Status = [int]$taskResponse.StatusCode
        Body = $taskResponse.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        Response = $taskResponse
    }
}

function Assert-FoundationError($Result, [int]$Status, [string]$Code) {
    if ($Result.Status -ne $Status) { throw "오류 상태 불일치: expected=$Status actual=$($Result.Status)" }
    $taskJson = $Result.Body | ConvertFrom-Json
    if ($taskJson.success -ne $false -or $taskJson.error.code -ne $Code) { throw '공통 오류 계약 불일치' }
    $taskId = [Guid]::Empty
    if (-not [Guid]::TryParse($taskJson.meta.requestId, [ref]$taskId)) { throw 'requestId UUID 형식 불일치' }
    if (@($Result.Response.Headers.GetValues('X-Request-Id'))[0] -ne $taskJson.meta.requestId) {
        throw 'requestId 헤더와 본문 불일치'
    }
    if (-not $Result.Response.Headers.CacheControl.NoStore) { throw 'no-store 누락' }
}

try {
    # 쿠키가 없는 최초 요청으로 발급을 확인한다. 유효 쿠키가 있는 재호출은 Set-Cookie를 생략할 수 있다.
    $taskPrepared = Invoke-FoundationRequest GET '/auth/csrf'
    if ($taskPrepared.Status -ne 204 -or $taskPrepared.Body.Length -ne 0) { throw 'CSRF 준비 204 계약 불일치' }
    $taskCookie = $taskHandler.CookieContainer.GetCookies($taskBaseUri)['XSRF-TOKEN']
    if ($null -eq $taskCookie -or $taskCookie.HttpOnly -or $taskCookie.Path -ne '/') { throw 'CSRF 쿠키 속성 불일치' }
    $taskSetCookie = @($taskPrepared.Response.Headers.GetValues('Set-Cookie')) |
        Where-Object { $_.StartsWith('XSRF-TOKEN=') } | Select-Object -First 1
    $taskAttributes = $taskSetCookie.Substring($taskSetCookie.IndexOf(';') + 1)
    if ($taskAttributes -notmatch 'SameSite=Lax' -or $taskAttributes -match 'Domain=') { throw 'CSRF 쿠키 범위 불일치' }
    Write-Output 'PASS HTTP-01 CSRF 204, empty body, readable root cookie'

    $taskHealth = Invoke-FoundationRequest GET '/health'
    $taskHealthJson = $taskHealth.Body | ConvertFrom-Json
    if ($taskHealth.Status -ne 200 -or $taskHealthJson.status -ne 'UP' -or
        $taskHealthJson.PSObject.Properties.Name -contains 'success') { throw 'Health 원문 계약 불일치' }
    Write-Output 'PASS HTTP-02 Health 200 with original body'

    $taskUnauthorized = Invoke-FoundationRequest GET '/auth/me'
    Assert-FoundationError $taskUnauthorized 401 'UNAUTHENTICATED'
    if ($null -ne $taskUnauthorized.Response.Headers.Location) { throw '401 리다이렉트 발생' }
    Write-Output 'PASS HTTP-03 protected request 401 JSON with matching requestId'

    Assert-FoundationError (Invoke-FoundationRequest POST '/auth/login') 403 'CSRF_INVALID'
    Assert-FoundationError (Invoke-FoundationRequest POST '/auth/login' @{'X-XSRF-TOKEN'='invalid-fixture-token'}) 403 'CSRF_INVALID'
    Write-Output 'PASS HTTP-04 missing and invalid CSRF headers rejected'

    $taskPassed = Invoke-FoundationRequest POST '/auth/login' @{'X-XSRF-TOKEN'=$taskCookie.Value}
    if ($taskPassed.Status -notin @(400,404)) { throw "CSRF 통과 이후 예상하지 않은 상태: $($taskPassed.Status)" }
    Write-Output 'PASS HTTP-05 raw CSRF header accepted; business login is outside this check'
} finally {
    $taskClient.Dispose()
    $taskHandler.Dispose()
}
