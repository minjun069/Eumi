// 로그인 화면 '이메일 저장' (FR-007).
// 서버를 거치지 않고 브라우저(localStorage)에 이메일만 저장한다. 비밀번호는 저장하지 않는다.
// 체크를 해제하고 로그인하면 지운다.

const STORAGE_KEY = "eumi.savedEmail"

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
