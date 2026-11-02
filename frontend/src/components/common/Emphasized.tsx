import { splitEmphasis } from "@/utils/emphasis"

/** 문장 안의 **…**를 굵게 (AI 답변·인사이트·보고서 공통) */
export function Emphasized({ text }: { text: string }) {
  return (
    <>
      {splitEmphasis(text).map((part, index) => (part.strong ? <strong key={index}>{part.text}</strong> : part.text))}
    </>
  )
}
