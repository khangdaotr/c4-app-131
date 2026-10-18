"use client"

import Link from "next/link"
import { useId, useState, type FormEvent, type ReactNode } from "react"
import { Check, Download, Eye, EyeOff, Loader2, TriangleAlert } from "lucide-react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/common/confirm-dialog"
import { Zone } from "@/components/common/zone"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { ADVISOR_FEATURES } from "@/lib/config"
import { api, ApiError } from "@/lib/api"
import { formatBytes, formatDate, formatTime } from "@/lib/format"
import { isStrongPassword } from "@/lib/password"
import { PasswordRuleList } from "@/components/common/password-rules"
import { DataPolicyDialog } from "@/components/auth/data-policy-dialog"
import { dobToIso, formatDob, normalizePhone } from "@/components/auth/auth-fields"
import { useReloadProfile } from "@/components/shell/profile-context"
import type { StudentSettings } from "@/lib/types"
import { cn } from "@/lib/utils"

// ---------- Khung chung ----------

export const SETTINGS_SECTIONS = [
  { id: "account", label: "Tài khoản" },
  { id: "privacy", label: "Quyền riêng tư" },
  { id: "notifications", label: "Thông báo" },
  { id: "data", label: "Dữ liệu" },
] as const satisfies readonly { id: string; label: string }[]

export type SettingsSectionId = (typeof SETTINGS_SECTIONS)[number]["id"]

/** "20/09" */
const shortDate = (iso: string) => formatDate(iso).slice(0, 5)
/** "2003-05-14" → "14/05/2003", không qua Date để tránh lệch múi giờ. */
const dayMonthYear = (ymd: string) => ymd.split("-").reverse().join("/")

/** Nút viền dạng pill nhỏ của bản vẽ ("Đổi mật khẩu", "Tải xuống"). */
const pillLine = "h-9 rounded-full border-line-strong bg-card px-4 font-semibold text-ink shadow-xs"

/**
 * Một dòng cài đặt (bản vẽ CaiDat): nhãn + giải thích ngắn bên trái, điều khiển bên phải.
 * Điện thoại: xếp dọc; riêng dòng có công tắc (`inline`) giữ công tắc bên phải vì nó nhỏ.
 */
function SettingRow({
  label,
  hint,
  htmlFor,
  inline = false,
  children,
}: {
  label: ReactNode
  hint?: ReactNode
  htmlFor?: string
  inline?: boolean
  children: ReactNode
}) {
  const Label = htmlFor ? "label" : "p"
  return (
    <div
      className={cn(
        "grid items-center gap-x-10 gap-y-3 border-b border-line py-5",
        inline
          ? "grid-cols-[minmax(0,1fr)_auto] sm:grid-cols-[minmax(200px,1fr)_minmax(0,1.4fr)]"
          : "sm:grid-cols-[minmax(200px,1fr)_minmax(0,1.4fr)]",
      )}
    >
      <div className="min-w-0">
        <Label htmlFor={htmlFor} className={cn("block font-medium text-ink", htmlFor && "cursor-pointer")}>
          {label}
        </Label>
        {hint && <div className="text-sm text-ink-3">{hint}</div>}
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-3 sm:justify-end">{children}</div>
    </div>
  )
}

function SettingsZone({ id, title, children }: { id: SettingsSectionId; title: string; children: ReactNode }) {
  return (
    <div id={id} className="scroll-mt-24">
      {/* Dòng đầu nằm sát đường kẻ tiêu đề như bản vẽ. */}
      <Zone id={`${id}-title`} title={title} className="[&>div:last-child]:pt-0">
        {children}
      </Zone>
    </div>
  )
}

// ---------- Mục lục neo ----------

export function SettingsNav({ active, onSelect }: { active: SettingsSectionId; onSelect: (id: SettingsSectionId) => void }) {
  return (
    <nav aria-label="Mục cài đặt" className="flex flex-col gap-0.5">
      {SETTINGS_SECTIONS.map((s) => {
        const isActive = s.id === active
        return (
          <a
            key={s.id}
            href={`#${s.id}`}
            aria-current={isActive ? "true" : undefined}
            onClick={(e) => {
              e.preventDefault()
              onSelect(s.id)
            }}
            className={cn(
              "block px-3.5 py-2 text-sm transition-colors",
              isActive
                ? "rounded-r-lg font-semibold text-ink shadow-[inset_2px_0_0_var(--ink)]"
                : "rounded-lg font-medium text-ink-2 hover:bg-surface hover:text-ink",
            )}
          >
            {s.label}
          </a>
        )
      })}
    </nav>
  )
}

// ---------- Tài khoản ----------

type ProfileFieldName = "full_name" | "date_of_birth" | "phone"

/** Kiểm tra trước khi gửi; trả về [giá trị gửi lên backend, lỗi]. */
function prepareProfileValue(field: ProfileFieldName, raw: string): [string, string | null] {
  if (field === "full_name") {
    const name = raw.trim().split(/\s+/).join(" ")
    return [name, name.length < 2 ? "Hãy nhập họ và tên." : null]
  }
  if (field === "phone") {
    const phone = normalizePhone(raw)
    return [phone ?? "", phone ? null : "Cần đủ 10 chữ số, bắt đầu bằng 0."]
  }
  const iso = dobToIso(raw)
  return [iso ?? "", iso ? null : "Ngày sinh cần có dạng dd/mm/yyyy."]
}

/** Một dòng hồ sơ sửa được tại chỗ: giá trị + "Sửa" → ô nhập + Lưu / Huỷ. */
function ProfileRow({
  field,
  label,
  display,
  initial,
  onSave,
}: {
  field: ProfileFieldName
  label: string
  display: string | null
  initial: string
  onSave: (field: ProfileFieldName, value: string) => Promise<void>
}) {
  const id = useId()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(initial)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  async function save(e: FormEvent) {
    e.preventDefault()
    const [prepared, invalid] = prepareProfileValue(field, value)
    if (invalid) {
      setError(invalid)
      return
    }
    setSaving(true)
    try {
      await onSave(field, prepared)
      setEditing(false)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Chưa lưu được. Hãy thử lại.")
    } finally {
      setSaving(false)
    }
  }

  if (!editing) {
    return (
      <SettingRow label={label} inline>
        <span className="flex min-w-0 items-center justify-end gap-3 sm:justify-start">
          <span className={cn("wrap-anywhere tabular-nums", display ? "text-ink-2" : "text-ink-3")}>{display ?? "Chưa cập nhật"}</span>
          <Button
            variant="ghost"
            className="h-8 shrink-0 rounded-full px-3 text-sm font-semibold text-blue hover:bg-blue-soft hover:text-accent-strong"
            onClick={() => {
              setValue(initial)
              setError(null)
              setEditing(true)
            }}
          >
            Sửa
          </Button>
        </span>
      </SettingRow>
    )
  }
  return (
    <SettingRow label={label} htmlFor={id}>
      <form onSubmit={save} noValidate className="grid gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Input
            id={id}
            value={value}
            onChange={(e) => setValue(field === "date_of_birth" ? formatDob(e.target.value) : e.target.value)}
            inputMode={field === "full_name" ? undefined : field === "phone" ? "tel" : "numeric"}
            autoComplete={field === "full_name" ? "name" : field === "phone" ? "tel" : "bday"}
            aria-invalid={error ? true : undefined}
            disabled={saving}
            autoFocus
            className="h-10 min-w-0 flex-[1_1_200px] rounded-[10px] border-line-strong bg-card tabular-nums"
          />
          <Button type="submit" disabled={saving} className="h-9 rounded-full bg-ink px-4 font-semibold text-on-ink hover:bg-ink/85">
            {saving && <Loader2 className="animate-spin" aria-hidden />}
            Lưu
          </Button>
          <Button type="button" variant="ghost" disabled={saving} className="h-9 rounded-full px-3 text-ink-2" onClick={() => setEditing(false)}>
            Huỷ
          </Button>
        </div>
        {error && <p className="text-xs text-bad">{error}</p>}
      </form>
    </SettingRow>
  )
}

export function AccountSection({
  settings,
  onSettingsChange,
  onPasswordChanged,
}: {
  settings: StudentSettings
  onSettingsChange: (settings: StudentSettings) => void
  onPasswordChanged: (updatedAt: string) => void
}) {
  const [changing, setChanging] = useState(false)
  const reloadProfile = useReloadProfile()
  const updatedAt = settings.password_updated_at

  async function saveProfile(field: ProfileFieldName, value: string) {
    const next = await api.updateProfile({ [field]: value })
    onSettingsChange(next)
    if (field === "full_name") reloadProfile()
    toast.success("Đã lưu")
  }

  return (
    <SettingsZone id="account" title="Tài khoản">
      <ProfileRow field="full_name" label="Họ tên" display={settings.full_name || null} initial={settings.full_name} onSave={saveProfile} />
      <ProfileRow
        field="date_of_birth"
        label="Ngày sinh"
        display={settings.date_of_birth ? dayMonthYear(settings.date_of_birth) : null}
        initial={settings.date_of_birth ? dayMonthYear(settings.date_of_birth) : ""}
        onSave={saveProfile}
      />
      <ProfileRow field="phone" label="Số điện thoại" display={settings.phone} initial={settings.phone ?? ""} onSave={saveProfile} />
      <SettingRow label="Email" hint="Dùng để đăng nhập, không đổi được">
        <span className="wrap-anywhere text-ink-2">{settings.email}</span>
      </SettingRow>
      <SettingRow
        label="Mật khẩu"
        hint={updatedAt ? `Đổi lần cuối ${formatDate(updatedAt)}` : "Chưa đổi kể từ khi tạo tài khoản"}
      >
        <Button variant="outline" className={pillLine} onClick={() => setChanging(true)}>
          Đổi mật khẩu
        </Button>
      </SettingRow>
      <PasswordDialog
        open={changing}
        onOpenChange={setChanging}
        onChanged={(at) => {
          onPasswordChanged(at)
          setChanging(false)
        }}
      />
    </SettingsZone>
  )
}

// ---------- Đổi mật khẩu (dialog) ----------

interface PasswordFieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  autoComplete: "current-password" | "new-password"
  error?: string | null
  describedBy?: string
}

function PasswordField({ label, value, onChange, autoComplete, error, describedBy }: PasswordFieldProps) {
  const id = useId()
  const errorId = `${id}-error`
  const [visible, setVisible] = useState(false)
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-ink">
        {label}
      </label>
      <div className="relative">
        <Input
          id={id}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          aria-invalid={error ? true : undefined}
          aria-describedby={[error ? errorId : null, describedBy].filter(Boolean).join(" ") || undefined}
          className="h-[42px] rounded-[10px] border-line-strong bg-card pr-10"
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
          aria-pressed={visible}
          className="absolute top-1/2 right-2 grid size-7 -translate-y-1/2 place-items-center rounded-md text-ink-3 hover:bg-surface hover:text-ink"
        >
          {visible ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
        </button>
      </div>
      {error && (
        <p id={errorId} className="text-xs text-bad">
          {error}
        </p>
      )}
    </div>
  )
}

type PasswordFieldName = "current" | "next" | "confirm"

function PasswordDialog({
  open,
  onOpenChange,
  onChanged,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onChanged: (updatedAt: string) => void
}) {
  const rulesId = useId()
  const [current, setCurrent] = useState("")
  const [next, setNext] = useState("")
  const [confirm, setConfirm] = useState("")
  const [submitted, setSubmitted] = useState(false)
  const [serverError, setServerError] = useState<{ field: PasswordFieldName; message: string } | null>(null)
  const [saving, setSaving] = useState(false)

  const errors: Record<PasswordFieldName, string | null> = {
    current: !current ? "Hãy nhập mật khẩu hiện tại." : null,
    next: !isStrongPassword(next)
      ? "Mật khẩu mới chưa đạt các điều kiện bên dưới."
      : next === current
        ? "Mật khẩu mới phải khác mật khẩu hiện tại."
        : null,
    confirm: confirm !== next ? "Mật khẩu nhập lại không khớp." : null,
  }
  const valid = !errors.current && !errors.next && !errors.confirm

  // Lỗi hiển thị sau lần bấm cập nhật đầu tiên; riêng ô nhập lại báo ngay khi đã gõ.
  const fieldError = (field: PasswordFieldName) =>
    (serverError?.field === field ? serverError.message : null) ??
    (submitted || (field === "confirm" && confirm.length > 0) ? errors[field] : null)

  function reset() {
    setCurrent("")
    setNext("")
    setConfirm("")
    setSubmitted(false)
    setServerError(null)
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setSubmitted(true)
    setServerError(null)
    if (!valid) return
    setSaving(true)
    try {
      const res = await api.changePassword({ current_password: current, new_password: next })
      onChanged(res.password_updated_at)
      reset()
      toast.success("Đã đổi mật khẩu.")
    } catch (err) {
      if (err instanceof ApiError && err.code === "wrong_password") setServerError({ field: "current", message: err.message })
      else if (err instanceof ApiError && err.code === "same_password") setServerError({ field: "next", message: err.message })
      else toast.error(err instanceof Error ? err.message : "Không đổi được mật khẩu.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (saving) return
        if (!value) reset()
        onOpenChange(value)
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Đổi mật khẩu</DialogTitle>
          <DialogDescription>Sau khi đổi, các thiết bị khác cần đăng nhập lại bằng mật khẩu mới.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} noValidate className="grid gap-4">
          <PasswordField
            label="Mật khẩu hiện tại"
            value={current}
            onChange={(v) => {
              setCurrent(v)
              if (serverError?.field === "current") setServerError(null)
            }}
            autoComplete="current-password"
            error={fieldError("current")}
          />
          <PasswordField
            label="Mật khẩu mới"
            value={next}
            onChange={(v) => {
              setNext(v)
              if (serverError?.field === "next") setServerError(null)
            }}
            autoComplete="new-password"
            error={fieldError("next")}
            describedBy={rulesId}
          />
          <PasswordRuleList id={rulesId} password={next} />
          <PasswordField
            label="Nhập lại mật khẩu mới"
            value={confirm}
            onChange={setConfirm}
            autoComplete="new-password"
            error={fieldError("confirm")}
          />
          <DialogFooter>
            <Button type="button" variant="soft" onClick={() => onOpenChange(false)} disabled={saving}>
              Huỷ
            </Button>
            <Button type="submit" disabled={saving}>
              {saving && <Loader2 className="animate-spin" aria-hidden />}
              {saving ? "Đang cập nhật…" : "Cập nhật mật khẩu"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---------- Quyền riêng tư ----------

// Nội dung pháp lý của phần đồng ý: giữ nguyên văn.

type SettingsPatch = { privacy?: Partial<StudentSettings["privacy"]>; notifications?: Partial<StudentSettings["notifications"]> }

const linkButton = "text-sm font-semibold text-blue hover:text-accent-strong disabled:pointer-events-none disabled:opacity-50"

export function PrivacySection({
  settings,
  advisorName,
  onChange,
  onWithdraw,
}: {
  settings: StudentSettings
  advisorName: string | null
  onChange: (patch: SettingsPatch) => void
  onWithdraw: () => Promise<void>
}) {
  const [viewing, setViewing] = useState(false)
  const [withdrawing, setWithdrawing] = useState(false)
  const consentAt = settings.consent_accepted_at

  return (
    <SettingsZone id="privacy" title="Quyền riêng tư">
      {ADVISOR_FEATURES && (
        <SettingRow
          label="Chia sẻ tài liệu với cố vấn"
          hint={advisorName ? `Cố vấn: ${advisorName}. Mặc định mọi tài liệu là riêng tư.` : "Mặc định mọi tài liệu là riêng tư."}
        >
          <Link href="/student/share" className={linkButton}>
            Chọn mục chia sẻ
          </Link>
        </SettingRow>
      )}
      <SettingRow
        inline
        htmlFor="anonymous-contribution"
        label="Đóng góp dữ liệu ẩn danh"
        hint="Giúp cải thiện gợi ý vị trí. Không gồm tên và liên hệ."
      >
        <Switch
          id="anonymous-contribution"
          size="lg"
          checked={settings.privacy.anonymous_contribution}
          onCheckedChange={(v) => onChange({ privacy: { anonymous_contribution: v } })}
        />
      </SettingRow>
      <SettingRow
        label="Đồng ý xử lý dữ liệu và cam kết liêm chính"
        hint={
          consentAt ? (
            `Xác nhận lúc ${formatTime(consentAt)} ngày ${formatDate(consentAt)}`
          ) : (
            <span className="text-warn">Phân tích CV và phỏng vấn thử tạm khoá cho tới khi bạn đồng ý lại.</span>
          )
        }
      >
        {consentAt ? (
          <span className="inline-flex items-center gap-1.5 text-sm font-medium text-good">
            <Check className="size-4" aria-hidden />
            Đã đồng ý {shortDate(consentAt)}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-sm font-medium text-warn">
            <TriangleAlert className="size-4" aria-hidden />
            Đã rút lại
          </span>
        )}
        <button type="button" className={linkButton} onClick={() => setViewing(true)}>
          Xem điều khoản
        </button>
        {consentAt && (
          <>
            <button type="button" className={linkButton} onClick={() => setWithdrawing(true)}>
              Rút lại
            </button>
          </>
        )}
      </SettingRow>

      {/* Cùng nội dung với phần chính sách ở trang Đăng ký (lib/data-policy.ts) */}
      <DataPolicyDialog open={viewing} onOpenChange={setViewing} />

      <ConfirmDialog
        open={withdrawing}
        onOpenChange={setWithdrawing}
        title="Rút lại sự đồng ý xử lý dữ liệu?"
        description="Các chức năng phân tích CV, tối ưu CV và phỏng vấn thử sẽ bị khoá ngay. Dữ liệu hiện có vẫn được giữ cho tới khi bạn yêu cầu xoá."
        confirmLabel="Rút lại sự đồng ý"
        destructive
        onConfirm={onWithdraw}
      />
    </SettingsZone>
  )
}

// ---------- Thông báo ----------

export function NotificationsSection({
  settings,
  onChange,
}: {
  settings: StudentSettings
  onChange: (patch: SettingsPatch) => void
}) {
  const n = settings.notifications
  const rows: { key: keyof StudentSettings["notifications"]; label: string; hint?: string }[] = [
    ...(ADVISOR_FEATURES ? [{ key: "advisor_comment" as const, label: "Cố vấn để lại nhận xét mới" }] : []),
    { key: "report_ready", label: "Báo cáo phân tích hoặc phỏng vấn đã sẵn sàng" },
    { key: "weekly_reminder", label: "Nhắc luyện tập hằng tuần", hint: "Khi 7 ngày chưa luyện và còn lượt trong tuần" },
    { key: "email", label: "Gửi thêm qua email", hint: `Bản sao các thông báo đang bật, gửi tới ${settings.email}` },
  ]
  return (
    <SettingsZone id="notifications" title="Thông báo">
      {rows.map((r) => (
        <SettingRow key={r.key} inline htmlFor={`notify-${r.key}`} label={r.label} hint={r.hint}>
          <Switch
            id={`notify-${r.key}`}
            size="lg"
            checked={n[r.key]}
            onCheckedChange={(v) => onChange({ notifications: { [r.key]: v } })}
          />
        </SettingRow>
      ))}
    </SettingsZone>
  )
}

// ---------- Dữ liệu: dung lượng, tải về, xoá ----------

export function DataSection({
  storage,
  onDeleteAll,
}: {
  storage: StudentSettings["storage"]
  onDeleteAll: () => Promise<void>
}) {
  const [exporting, setExporting] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const percent = Math.min(100, Math.round((storage.used_bytes / storage.limit_bytes) * 100))

  async function exportAll() {
    setExporting(true)
    try {
      const file = await api.downloadDataExport()
      if (file) {
        const href = URL.createObjectURL(file)
        const a = document.createElement("a")
        a.href = href
        a.download = "careerv-du-lieu-cua-toi.json"
        a.click()
        URL.revokeObjectURL(href)
      } else toast.success("Đã tạo gói dữ liệu. Bản demo không có file thật để tải.")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Không tạo được gói dữ liệu.")
    } finally {
      setExporting(false)
    }
  }

  return (
    <SettingsZone id="data" title="Dữ liệu">
      <SettingRow label="Dung lượng lưu trữ" hint={`Do ${storage.allocated_by} cấp`}>
        <span className="text-sm text-ink-2 tabular-nums">
          {formatBytes(storage.used_bytes)} / {formatBytes(storage.limit_bytes)}
        </span>
        <span
          className="block h-1.5 w-[120px] overflow-hidden rounded-full bg-surface"
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Dung lượng đã dùng"
        >
          <span className="block h-full rounded-full bg-blue" style={{ width: `${Math.max(percent, 2)}%` }} />
        </span>
      </SettingRow>
      <SettingRow label="Tải toàn bộ dữ liệu" hint="CV, kết quả phân tích và báo cáo phỏng vấn, dạng file JSON">
        <Button variant="outline" className={pillLine} disabled={exporting} onClick={exportAll}>
          {exporting ? <Loader2 className="animate-spin" aria-hidden /> : <Download aria-hidden />}
          Tải xuống
        </Button>
      </SettingRow>

      <div className="mt-6 flex flex-wrap items-center gap-4 rounded-[14px] border border-bad/20 bg-bad-soft px-5 py-[18px]">
        <div className="min-w-[220px] flex-1">
          <p className="flex items-center gap-2 font-semibold text-bad">
            Xoá toàn bộ dữ liệu
          </p>
          <p className="text-sm text-ink-2">Xoá vĩnh viễn mọi CV, báo cáo, điểm số và nhận xét. Không thể hoàn tác.</p>
        </div>
        <Button
          variant="outline"
          className="h-9 rounded-full border-bad/30 bg-card px-4 font-semibold text-bad hover:bg-card hover:text-bad"
          onClick={() => setConfirm(true)}
        >
          Xoá dữ liệu
        </Button>
      </div>

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Xoá toàn bộ dữ liệu?"
        description={`Mọi CV, báo cáo phân tích, báo cáo phỏng vấn${ADVISOR_FEATURES ? " và nhận xét của cố vấn" : ""} sẽ bị xoá vĩnh viễn. Hãy tải về bản sao trước nếu bạn cần lưu lại.`}
        confirmLabel="Xoá vĩnh viễn"
        destructive
        onConfirm={onDeleteAll}
      />
    </SettingsZone>
  )
}
