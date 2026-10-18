import type { ReactNode } from "react"
import { Check, FileText, Info, LockKeyhole, ShieldCheck, Sparkles, Trash2, UserRound, type LucideIcon } from "lucide-react"

import { BrandMark } from "@/components/brand/logo"
import { ADVISOR_FEATURES } from "@/lib/config"
import { cn } from "@/lib/utils"

import { SectionHeading } from "./landing-bits"
import styles from "./landing.module.css"

const COMMITMENTS: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: ShieldCheck, title: "Không bịa kinh nghiệm", text: "Kỹ năng chưa có không được thêm vào CV. Chỗ cần số liệu để trống cho bạn tự điền." },
  {
    icon: LockKeyhole,
    title: "Mặc định là riêng tư",
    text: ADVISOR_FEATURES
      ? "Bạn bật chia sẻ riêng từng CV, từng buổi phỏng vấn và tắt lại bất cứ lúc nào."
      : "CV, câu trả lời và báo cáo của bạn chỉ mình bạn xem được.",
  },
  { icon: Trash2, title: "Bạn giữ quyền xoá", text: "Tải về hoặc xoá toàn bộ dữ liệu của mình ngay trong Cài đặt." },
  { icon: Info, title: "Nói rõ giới hạn", text: "Điểm số giúp bạn biết nên luyện gì, không đảm bảo kết quả tuyển dụng." },
]

const nodeBox = "flex items-center gap-3 rounded-card bg-white/5 px-4 py-3.5 shadow-[inset_0_0_0_1px_rgb(255_255_255/0.09)] backdrop-blur-[6px]"

function NightIcon({ icon: Icon }: { icon: LucideIcon }) {
  return (
    <span className="grid size-[38px] shrink-0 place-items-center rounded-xl bg-white/8 text-white">
      <Icon className="size-[18px]" strokeWidth={1.75} aria-hidden />
    </span>
  )
}

function Node({ icon, title, sub, className, style, children }: { icon?: LucideIcon; title: string; sub: string; className?: string; style?: React.CSSProperties; children?: ReactNode }) {
  return (
    <div className={cn(nodeBox, className)} style={style}>
      {icon && <NightIcon icon={icon} />}
      <span className="min-w-0 flex-1">
        <b className="block text-[15px] font-semibold text-white">{title}</b>
        <span className="block text-[13px] text-night-mute">{sub}</span>
      </span>
      {children}
    </div>
  )
}

const LINE = "rgb(255 255 255 / 0.12)"
// Nhánh dưới (công tắc chia sẻ → Cố vấn) chỉ có khi bật tính năng cố vấn (lib/config.ts)
const PATHS = ["M180 190 H270", "M510 190 H560 V96 H610", ...(ADVISOR_FEATURES ? ["M560 190 V284 H610"] : []), "M830 96 H866"]

/** Sơ đồ luồng dữ liệu (desktop): đường chạy liên tục, công tắc chia sẻ tự bật/tắt và nhánh tới Cố vấn sáng theo. */
function FlowDiagram() {
  return (
    <div className="relative mx-auto mt-16 hidden h-[380px] w-[1080px] max-w-full lg:block" aria-hidden>
      <svg width="1080" height="380" viewBox="0 0 1080 380" fill="none" className="absolute inset-0">
        <defs>
          <linearGradient id="night-line" x1="0" x2="1">
            <stop offset="0" stopColor="#9ED4FF" />
            <stop offset=".5" stopColor="#B8A4FF" />
            <stop offset="1" stopColor="#FF9FCB" />
          </linearGradient>
        </defs>
        {PATHS.map((d) => (
          <g key={d}>
            <path d={d} stroke={LINE} strokeWidth="2" />
            <path className={styles.flow} d={d} stroke="url(#night-line)" strokeWidth="2" />
          </g>
        ))}
        {ADVISOR_FEATURES && (
          <>
            <path d="M830 284 H866" stroke={LINE} strokeWidth="2" strokeDasharray="4 6" />
            <path className={cn(styles.flow, styles.shareLine)} d="M830 284 H866" stroke="#B8A4FF" strokeWidth="2" />
          </>
        )}
      </svg>
      <Node icon={FileText} title="CV của bạn" sub="PDF hoặc DOCX" className="absolute top-[156px] left-0 w-[180px]" />
      <div
        className="absolute top-[136px] left-[270px] grid w-[240px] gap-2.5 rounded-card p-5 shadow-[inset_0_0_0_1px_rgb(255_255_255/0.16),0_30px_60px_-30px_rgb(139_124_246/0.6)]"
        style={{ background: "linear-gradient(160deg, rgb(158 212 255 / 0.16), rgb(255 159 203 / 0.12))" }}
      >
        <span className="flex items-center gap-2.5">
          <BrandMark onDark className="h-[22px]" />
          <b className="text-[17px] font-semibold text-white">
            Career<span className="text-gold">V</span>
          </b>
        </span>
        <span className="text-[13px] text-night-mute">Đọc CV · So khớp JD · Gợi ý · Chấm STAR</span>
      </div>
      <Node icon={Check} title="Bạn duyệt từng gợi ý" sub="Áp dụng · Sửa · Bỏ qua" className="absolute top-[62px] left-[610px] w-[220px]" />
      <Node icon={FileText} title="CV phiên bản mới" sub="Tải về khi sẵn sàng" className="absolute top-[62px] left-[866px] w-[214px]" />
      {ADVISOR_FEATURES && (
        <>
          <Node title="Công tắc chia sẻ" sub="Mặc định tắt" className="absolute top-[250px] left-[610px] w-[220px]">
            <span className={styles.nightSwitch} />
          </Node>
          <Node icon={UserRound} title="Cố vấn" sub="Chỉ xem mục bạn bật" className={cn(styles.shareNode, "absolute top-[250px] left-[866px] w-[214px]")} />
        </>
      )}
    </div>
  )
}

/** Bản dọc của sơ đồ cho điện thoại và máy tính bảng. */
function FlowList() {
  return (
    <div className="relative mt-8 grid gap-5 lg:hidden" aria-hidden>
      <span className="absolute top-8 bottom-8 left-[34px] w-0.5 bg-[linear-gradient(#9ED4FF,#B8A4FF,#FF9FCB)] opacity-60" />
      <Node icon={FileText} title="CV của bạn" sub="PDF hoặc DOCX" className="relative" />
      <Node icon={Sparkles} title="CareerV" sub="Đọc CV · So khớp · Gợi ý · Chấm STAR" className="relative" />
      <Node icon={Check} title="Bạn duyệt từng gợi ý" sub="Áp dụng · Sửa · Bỏ qua" className="relative" />
      {ADVISOR_FEATURES ? (
        <Node icon={UserRound} title="Cố vấn" sub="Chỉ xem mục bạn bật" className="relative">
          <span className={styles.nightSwitch} />
        </Node>
      ) : (
        <Node icon={FileText} title="CV phiên bản mới" sub="Tải về khi sẵn sàng" className="relative" />
      )}
    </div>
  )
}

/** Dải tối duy nhất của trang, làm "điểm dừng" giữa các phần nền trắng (DESIGN.md 4.1). */
export function Commitments() {
  return (
    <section id="cam-ket" className="relative scroll-mt-16 overflow-hidden bg-night text-white">
      <span aria-hidden className="pointer-events-none absolute -top-64 -left-48 size-[520px] rounded-full bg-[#5B5BD6] opacity-[0.32] blur-[60px]" />
      <span aria-hidden className="pointer-events-none absolute -right-36 -bottom-56 size-[460px] rounded-full bg-[#FF8FB8] opacity-[0.28] blur-[60px]" />
      <div className="relative mx-auto max-w-[1200px] px-4 py-16 md:px-10 md:pt-[120px] md:pb-[112px]">
        <SectionHeading
          dark
          eyebrow="Cam kết"
          title="Dữ liệu của bạn, quyền của bạn."
          description="CareerV chỉ trình bày lại kinh nghiệm có thật trong CV. Mọi thay đổi đi qua tay bạn, và không ai khác thấy dữ liệu khi bạn chưa cho phép."
        />
        <FlowDiagram />
        <FlowList />
        <ul className="mt-12 grid gap-7 border-t border-white/9 pt-10 sm:grid-cols-2 md:mt-[72px] lg:grid-cols-4 lg:gap-8">
          {COMMITMENTS.map(({ icon, title, text }) => (
            <li key={title}>
              <NightIcon icon={icon} />
              <h3 className="mt-4 text-[17px] leading-[25px] font-semibold text-white">{title}</h3>
              <p className="mt-1.5 text-[15px] text-night-mute">{text}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
