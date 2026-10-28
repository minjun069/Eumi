import { useState, type InputHTMLAttributes } from "react"

type PasswordInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type">

/** 비밀번호 입력칸 + 오른쪽 끝 눈 모양 '비밀번호 보기' 버튼 (로그인, 회원가입, 비밀번호 변경에서 공통 사용) */
export function PasswordInput({ className = "", ...inputProps }: PasswordInputProps) {
  const [visible, setVisible] = useState(false)

  return (
    <div className="password-input">
      <input {...inputProps} className={`input ${className}`} type={visible ? "text" : "password"} />
      <button
        type="button"
        className="password-toggle"
        aria-label={visible ? "비밀번호 숨기기" : "비밀번호 보기"}
        aria-pressed={visible}
        title={visible ? "비밀번호 숨기기" : "비밀번호 보기"}
        onClick={() => setVisible((value) => !value)}
      >
        <svg
          viewBox="0 0 24 24"
          width="20"
          height="20"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" />
          <circle cx="12" cy="12" r="3" />
          {/* 비밀번호가 보이는 상태에서는 '숨기기'를 뜻하는 사선을 그린다 */}
          {visible && <path d="M4 4l16 16" />}
        </svg>
      </button>
    </div>
  )
}
