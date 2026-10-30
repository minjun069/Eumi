// 로그인 화면 '이메일 저장'.
// 서버를 거치지 않고 브라우저(localStorage)에만 저장하므로 API 기록에는 남지 않는다.
// 탭이나 브라우저를 닫아도 남고, 새로고침해도 지워지지 않는다.

const STORAGE_KEY = "ieumi-v2.savedEmail"

export function getSavedEmail(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function saveEmail(email: string) {
  try {
    localStorage.setItem(STORAGE_KEY, email)
  } catch {
    // 저장소를 쓸 수 없는 환경에서는 저장하지 않는다
  }
}

export function clearSavedEmail() {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // 저장소를 쓸 수 없는 환경
  }
}
