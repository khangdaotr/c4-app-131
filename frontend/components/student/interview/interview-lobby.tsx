"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useCallback, useState, type ReactNode } from "react"
import { AlertCircle, ChevronRight, EyeOff, Loader2, LogOut, Pause, ShieldCheck, Timer, type LucideIcon } from "lucide-react"
import { toast } from "sonner"

import { EmptyState } from "@/components/common/empty-state"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { api, ApiError } from "@/lib/api"
import { formatDate } from "@/lib/format"
import { MIN_ANSWER_CHARS, PAUSE_MAX_SECONDS, QUESTION_COUNT, SECONDS_PER_QUESTION } from "@/lib/interview"
import { SetFocusTitle } from "@/components/shell/focus-title"
import { useApi } from "@/lib/use-api"
import { preparePhoWhisper, usePhoWhisperPreparation } from "@/lib/speech/phowhisper"
import { SpeechPreparation } from "./speech-preparation"

const MINUTES = (QUESTION_COUNT * SECONDS_PER_QUESTION) / 60

/** Nút viền mảnh dạng pill (nút phụ trong chế độ tập trung). */
export const outlinePill =
  "bg-card text-ink shadow-[inset_0_0_0_1px_var(--line-strong)] hover:bg-panel hover:text-ink"

const RULES: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: Timer,
    title: "Mỗi câu có đồng hồ riêng",
    text: `${SECONDS_PER_QUESTION / 60} phút mỗi câu, câu 1 chỉ bắt đầu tính giờ khi bạn bấm Sẵn sàng. Hết giờ, phần đang gõ được tự nộp; dưới ${MIN_ANSWER_CHARS} ký tự được 0 điểm.`,
  },
  {
    icon: Pause,
    title: "Được tạm dừng 1 lần",
    text: `Dùng khi cần nghỉ giữa chừng, tối đa ${PAUSE_MAX_SECONDS} giây; đồng hồ sẽ dừng theo.`,
  },
  {
    icon: EyeOff,
    title: "Không hiện điểm trong lúc phỏng vấn",
    text: `Điểm STAR và nhận xét có trong báo cáo sau khi bạn trả lời đủ ${QUESTION_COUNT} câu.`,
  },
  {
    icon: LogOut,
    title: "Rời phòng giữa chừng thì không lưu",
    text: "Kết thúc sớm hoặc rời phòng thì buổi không được lưu và không tính lượt.",
  },
  {
    icon: ShieldCheck,
    title: "Trả lời bằng trải nghiệm thật",
    text: "Nội dung không liên quan đến buổi phỏng vấn sẽ không được tính.",
  },
]

/**
 * Phòng chờ (bản vẽ "Phòng chờ", WIREFRAMES A12): chế độ tập trung, luật buổi phỏng vấn ở giữa màn hình.
 * Buổi phỏng vấn chỉ được tạo khi SV bấm "Sẵn sàng", vì đồng hồ câu 1 bắt đầu chạy ngay lúc tạo buổi
 * (create_session ở src/services/interview.py); "Đổi CV và vị trí" về trang Thiết lập, giữ nguyên lựa chọn.
 */
export function InterviewLobby({
  jdId,
  cvId,
  initialMode = null,
}: {
  jdId: string | null
  cvId: string | null
  /** "jd_only" (?mode=jd_only): phỏng vấn chỉ theo vị trí, không cần CV. */
  initialMode?: string | null
}) {
  const jdOnly = initialMode === "jd_only" || !cvId
  const router = useRouter()
  const { data: jds, error: jdsError, reload: reloadJds } = useApi(api.listInterviewJds)
  const { data: cvs, error: cvsError, reload: reloadCvs } = useApi(api.listCvVersions)
  const jdKey = jdId ?? ""
  const fetchQuota = useCallback(() => api.getQuota(jdKey), [jdKey])
  const { data: quota } = useApi(fetchQuota)
  const [starting, setStarting] = useState(false)
  const speech = usePhoWhisperPreparation(Boolean(jds && cvs && jdId))

  const params = new URLSearchParams()
  if (jdId) params.set("jd", jdId)
  if (cvId) params.set("cv", cvId)
  if (jdOnly) params.set("mode", "jd_only")
  const setupHref = `/student/interview/new${params.size > 0 ? `?${params}` : ""}`

  if (jdsError || cvsError) {
    return (
      <Centered>
        <EmptyState
          icon={AlertCircle}
          title="Không mở được phòng chờ"
          description={(jdsError ?? cvsError)?.message}
          action={
            <Button
              size="brand"
              onClick={() => {
                reloadJds()
                reloadCvs()
              }}
            >
              Thử lại
            </Button>
          }
        />
      </Centered>
    )
  }

  if (!jds || !cvs) {
    return (
      <Centered>
        <div className="grid gap-4" aria-busy="true" aria-label="Đang chuẩn bị phòng chờ">
          <div className="flex items-center gap-3.5">
            <Skeleton className="size-[52px] rounded-2xl" />
            <Skeleton className="h-10 w-56 rounded-lg" />
          </div>
          <Skeleton className="mt-6 h-11 w-72 max-w-full rounded-lg" />
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16 rounded-xl" />
          ))}
        </div>
      </Centered>
    )
  }

  const jd = jds.find((j) => j.id === jdId)
  const cv = jdOnly ? null : cvs.find((c) => c.id === cvId)
  if (!jd || cv === undefined) {
    return (
      <Centered>
        <EmptyState
          icon={AlertCircle}
          title={jdOnly ? "Chưa chọn vị trí cho buổi phỏng vấn" : "Chưa chọn vị trí hoặc CV cho buổi phỏng vấn"}
          description={`Hãy chọn vị trí ứng tuyển${jdOnly ? "" : " và CV"} ở trang Thiết lập rồi vào lại phòng chờ.`}
          action={
            <Button size="brand" nativeButton={false} render={<Link href={setupHref} />}>
              Về trang Thiết lập
            </Button>
          }
        />
      </Centered>
    )
  }

  const exhausted = quota !== undefined && quota.remaining === 0

  async function ready() {
    if (!jd || cv === undefined || starting || exhausted || !quota || (!speech.typingOnly && speech.phase !== "ready")) return
    setStarting(true)
    try {
      if (!speech.typingOnly) await preparePhoWhisper()
      const session = await api.createInterview({
        jd_id: jd.id,
        cv_version_id: cv?.id ?? null,
        interview_mode: cv ? "with_cv" : "jd_only",
      })
      // replace: bấm Back trong phòng không quay lại phòng chờ (sẽ tạo thêm buổi mới)
      router.replace(`/student/interview/${encodeURIComponent(session.id)}`)
    } catch (err) {
      toast.error(err instanceof ApiError || err instanceof Error ? err.message : "Không bắt đầu được phỏng vấn.")
      setStarting(false)
    }
  }

  return (
    <Centered>
      <SetFocusTitle title={`Phòng chờ · ${jd.title}`} />
      <div className="flex items-center gap-3.5">
        <span
          className="grid size-[52px] shrink-0 place-items-center rounded-2xl bg-ink text-[15px] font-semibold tracking-[0.02em] text-on-ink"
          aria-hidden
        >
          AI
        </span>
        <div className="min-w-0">
          <p className="font-semibold text-ink">AI Career Coach</p>
          <p className="text-sm text-ink-3">
            Người phỏng vấn · {QUESTION_COUNT} câu · khoảng {MINUTES} phút
          </p>
        </div>
      </div>

      <h1 className="mt-8 text-[30px] leading-9 font-semibold tracking-[-0.025em] text-ink md:mt-9 md:text-[40px] md:leading-[46px]">
        Trước khi bắt đầu
      </h1>
      <dl className="mt-3 grid grid-cols-[48px_minmax(0,1fr)] gap-x-3 gap-y-1 text-base leading-[26px]">
        <dt className="text-ink-3">Vị trí</dt>
        <dd className="break-words text-ink">
          <span className="font-medium">{jd.title}</span>
          {jd.company && <span className="text-ink-2"> · {jd.company}</span>}
        </dd>
        <dt className="text-ink-3">CV</dt>
        <dd className="break-words text-ink">
          {cv ? cv.file_name : <span className="text-ink-2">Không dùng CV · câu hỏi dựa trên yêu cầu của vị trí</span>}
        </dd>
      </dl>

      <ul className="mt-6 border-t border-line">
        {RULES.map(({ icon: Icon, title, text }) => (
          <li key={title} className="flex gap-3.5 border-b border-line py-[18px]">
            <span className="grid size-9 shrink-0 place-items-center rounded-[10px] bg-surface text-ink">
              <Icon className="size-[18px]" strokeWidth={1.75} aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="font-semibold text-ink">{title}</p>
              <p className="text-sm leading-[22px] text-ink-2">{text}</p>
            </div>
          </li>
        ))}
      </ul>

      <div className="mt-6"><SpeechPreparation state={speech} lobby /></div>

      {exhausted ? (
        <p className="mt-6 flex items-start gap-1.5 text-sm text-warn" role="alert">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          Bạn đã dùng hết lượt cho vị trí này trong tuần (làm mới ngày {formatDate(quota.resets_at)}). Hãy đổi sang vị trí
          khác.
        </p>
      ) : (
        quota && (
          <p className="mt-6 text-sm text-ink-3">
            Còn {quota.remaining} / {quota.limit} buổi cho vị trí này trong tuần.
          </p>
        )
      )}

      <div className="mt-6 flex flex-wrap items-center gap-2.5 md:mt-8">
        <Button size="brand" onClick={() => void ready()} disabled={starting || exhausted || !quota || (!speech.typingOnly && speech.phase !== "ready")}>
          {starting && <Loader2 className="animate-spin" aria-hidden />}
          {starting ? "Đang mở phòng…" : "Sẵn sàng"}
          {!starting && <ChevronRight aria-hidden />}
        </Button>
        <Button
          variant="ghost"
          size="brand"
          className={outlinePill}
          nativeButton={false}
          render={<Link href={setupHref} aria-disabled={starting} />}
        >
          Đổi CV và vị trí
        </Button>
      </div>

    </Centered>
  )
}

/** Khối một cột ở giữa màn hình, rộng tối đa 640px (DESIGN.md 5.5). */
function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-[calc(100dvh-10rem)] place-items-center">
      <div className="w-full max-w-[640px] py-4 sm:py-10">{children}</div>
    </div>
  )
}
