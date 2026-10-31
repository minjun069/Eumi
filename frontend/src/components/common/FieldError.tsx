/** 입력칸 아래 오류 문구 (필수값 누락, 형식 오류, API 실패 사유) */
export function FieldError({ message }: { message?: string | null }) {
  if (!message) return null
  return (
    <p className="field-error" role="alert">
      {message}
    </p>
  )
}
