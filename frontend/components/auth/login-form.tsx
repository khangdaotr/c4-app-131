"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useRef, useState, type FormEvent } from "react"
import { Loader2 } from "lucide-react"

import { AuthCard, AuthHeading, OrDivider } from "@/components/auth/auth-shell"
import { FormAlert, PasswordField, TextField, isEmail, type FieldHint } from "@/components/auth/auth-fields"
import { DemoRoleDialog } from "@/components/auth/demo-role-dialog"
import { Button } from "@/components/ui/button"
import { api, ApiError } from "@/lib/api"
import { DEMO_TRY } from "@/lib/config"
import { landingOf, setAuthMode, type AuthMode } from "@/lib/session"

export function LoginForm({ expired = false }: { expired?: boolean }) {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [submitted, setSubmitted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<{ message: string; wrongPassword: boolean } | null>(null)
  const [demoOpen, setDemoOpen] = useState(false)
  const submitRef = useRef<HTMLButtonElement>(null)

  // Tài khoản demo: điền sẵn rồi đưa focus về nút Đăng nhập để chỉ cần bấm Enter
  function fillDemo(demoEmail: string, demoPassword: string) {
    setEmail(demoEmail)
    setPassword(demoPassword)
    setError(null)
    setSubmitted(false)
    setTimeout(() => submitRef.current?.focus(), 0)
  }

  const emailHint: FieldHint =
    submitted && !email.trim() ? { tone: "error", text: "Hãy nhập email." } : submitted && !isEmail(email) ? { tone: "error", text: "Email chưa đúng định dạng." } : null
  const passwordHint: FieldHint = submitted && !password ? { tone: "error", text: "Hãy nhập mật khẩu." } : null

  async function submit(e: FormEvent) {
    e.preventDefault()
    setSubmitted(true)
    if (!isEmail(email) || !password) return
    setBusy(true)
    setError(null)
    try {
      const { role, must_change_password } = await api.login({ email: email.trim(), password })
      const mode: AuthMode = must_change_password ? { role, mustChangePassword: true } : { role }
      setAuthMode(mode)
      router.push(landingOf(mode))
    } catch (err) {
      const apiErr = err instanceof ApiError ? err : null
      setError({
        message: apiErr?.message ?? "Chưa đăng nhập được. Hãy thử lại.",
        wrongPassword: apiErr?.code === "invalid_credentials",
      })
      setBusy(false)
    }
  }

  return (
    <AuthCard>
      <AuthHeading title="Đăng nhập" description="Chào mừng bạn quay lại CareerV." />
      <form onSubmit={submit} noValidate className="grid gap-5">
        {error ? (
          <FormAlert>{error.message}</FormAlert>
        ) : (
          expired && (
            <p role="status" className="rounded-xl bg-panel px-3.5 py-3 text-sm leading-[21px] text-ink-2">
              Phiên đăng nhập đã hết. Hãy đăng nhập lại để tiếp tục.
            </p>
          )
        )}
        <TextField
          label="Email"
          type="email"
          autoComplete="email"
          inputMode="email"
          value={email}
          onChange={(v) => {
            setEmail(v)
            setError(null)
          }}
          hint={emailHint}
          disabled={busy}
          autoFocus
        />
        <PasswordField
          label="Mật khẩu"
          autoComplete="current-password"
          value={password}
          onChange={(v) => {
            setPassword(v)
            setError(null)
          }}
          hint={passwordHint}
          aria-invalid={error?.wrongPassword || passwordHint ? true : undefined}
          disabled={busy}
          aside={
            <Link href="/forgot-password" className="text-sm font-semibold">
              Quên mật khẩu?
            </Link>
          }
        />
        <Button ref={submitRef} type="submit" variant="dark" size="brand" className="h-12 w-full" disabled={busy}>
          {busy && <Loader2 className="animate-spin" aria-hidden />}
          {busy ? "Đang đăng nhập…" : "Đăng nhập"}
        </Button>
      </form>
      {/* "Dùng thử bản demo" đang tạm ẩn (lib/config.ts) */}
      {DEMO_TRY && (
        <>
          <OrDivider />
          <Button variant="outline" size="brand" className="h-12 w-full border-line-strong bg-card text-ink hover:bg-panel" onClick={() => setDemoOpen(true)}>
            Dùng thử bản demo
          </Button>
        </>
      )}
      <p className="text-center text-sm text-ink-2">
        Chưa có tài khoản?{" "}
        <Link href="/register" className="font-semibold">
          Tạo tài khoản
        </Link>
      </p>
      {DEMO_TRY && <DemoRoleDialog open={demoOpen} onOpenChange={setDemoOpen} onPick={fillDemo} />}
    </AuthCard>
  )
}
