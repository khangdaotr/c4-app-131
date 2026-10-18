"use client"

import { useId, useState } from "react"
import { Plus } from "lucide-react"

import { ADVISOR_FEATURES } from "@/lib/config"
import { cn } from "@/lib/utils"

import { SectionHeading } from "./landing-bits"

const FAQS = [
  ["CareerV có mất phí không?", "Không. Sinh viên dùng miễn phí. Mỗi vị trí có 3 buổi phỏng vấn thử mỗi tuần để giữ chất lượng chấm điểm."],
  [
    "AI có tự thêm kỹ năng vào CV của tôi không?",
    "Không. Khi JD yêu cầu điều bạn chưa có, CareerV hỏi bạn có kinh nghiệm hay không và chỉ ghi những gì bạn xác nhận. Kỹ năng đang học được ghi rõ là đang học.",
  ],
  ["CV cần định dạng gì?", "PDF hoặc DOCX, tối đa 10 MB. File PDF dạng ảnh chụp chưa đọc được chữ, bạn nên xuất PDF trực tiếp từ Word hoặc Google Docs."],
  [
    "Ai xem được CV và báo cáo phỏng vấn của tôi?",
    ADVISOR_FEATURES
      ? "Chỉ bạn. Cố vấn chỉ xem được những mục bạn bật chia sẻ, và bạn tắt lại bất cứ lúc nào."
      : "Chỉ bạn. CareerV không chia sẻ CV hay báo cáo của bạn cho người khác.",
  ],
  [
    "Điểm phỏng vấn được chấm thế nào?",
    "Mỗi câu trả lời được chấm theo 4 tiêu chí Bối cảnh, Nhiệm vụ, Hành động, Kết quả trên thang 5. Điểm chỉ so giữa các buổi cùng vị trí; cố vấn có thể thêm nhận xét nhưng không sửa điểm.",
  ],
  ["Tôi có xoá được dữ liệu của mình không?", "Có. Trong Cài đặt, bạn tải về hoặc xoá toàn bộ dữ liệu của mình."],
]

/** Mọi câu đóng sẵn; mở một câu thì câu đang mở tự đóng. */
export function LandingFaq() {
  const [open, setOpen] = useState<number | null>(null)
  const baseId = useId()
  return (
    <section id="hoi-dap" className="mx-auto grid max-w-[1200px] scroll-mt-20 gap-6 px-4 pb-20 md:px-10 md:pb-[120px] lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)] lg:gap-16">
      <SectionHeading title="Hỏi đáp" description="Những câu sinh viên hay hỏi." />
      <div className="border-t border-line">
        {FAQS.map(([q, a], i) => {
          const expanded = open === i
          const panelId = `${baseId}-${i}`
          return (
            <div key={q} className="border-b border-line">
              <h3>
                <button
                  type="button"
                  aria-expanded={expanded}
                  aria-controls={panelId}
                  onClick={() => setOpen(expanded ? null : i)}
                  className="flex w-full items-center gap-4 py-[18px] text-left text-base font-semibold text-ink md:py-[22px] md:text-lg"
                >
                  <span className="flex-1">{q}</span>
                  <span
                    className={cn(
                      "grid size-8 shrink-0 place-items-center rounded-full transition-[rotate,background-color,color] duration-300 ease-[cubic-bezier(0.34,1.4,0.64,1)]",
                      expanded ? "rotate-45 bg-ink text-white" : "bg-surface text-ink",
                    )}
                  >
                    <Plus className="size-[18px]" strokeWidth={2} aria-hidden />
                  </span>
                </button>
              </h3>
              <div
                id={panelId}
                role="region"
                aria-label={q}
                hidden={!expanded}
                className="pr-2 pb-6 text-[15px] leading-[26px] text-ink-2 md:pr-14 md:text-base"
              >
                {a}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
