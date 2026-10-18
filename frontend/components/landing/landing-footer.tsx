"use client"

import Link from "next/link"
import { useState } from "react"

import { DataPolicyDialog } from "@/components/auth/data-policy-dialog"
import { Logo } from "@/components/brand/logo"
import { Button } from "@/components/ui/button"
import { ADVISOR_FEATURES } from "@/lib/config"

/** Lời mời cuối trang trên nền pastel. */
export function LandingCta() {
  return (
    <section className="mx-auto max-w-[1200px] px-4 pb-16 md:px-10 md:pb-24">
      <div className="relative overflow-hidden rounded-[24px] bg-panel px-6 py-10 text-center md:rounded-[28px] md:px-16 md:py-20">
        <div className="aurora-band h-full! opacity-55 [mask-image:none]!" aria-hidden />
        <div className="relative">
          <h2 className="font-heading text-[26px] leading-8 font-semibold tracking-[-0.025em] text-ink md:text-[44px] md:leading-[50px]">Bắt đầu với CV của bạn.</h2>
          <p className="mt-3 text-base text-ink-2 md:text-lg">Tải CV lên và xem ngay vị trí nào hợp với bạn.</p>
          <div className="mt-7 grid justify-center gap-3 sm:flex md:mt-[30px]">
            <Button variant="dark" size="brand" className="h-[50px] px-6 text-base" nativeButton={false} render={<Link href="/register" />}>
              Tạo tài khoản miễn phí
            </Button>
            <Button variant="ghost" size="brand" className="glass h-[50px] px-6 text-base text-ink shadow-xs hover:bg-card" nativeButton={false} render={<Link href="/login" />}>
              Đăng nhập
            </Button>
          </div>
        </div>
      </div>
    </section>
  )
}

const COLUMNS: { title: string; links: { label: string; href?: string; policy?: boolean }[] }[] = [
  {
    title: "Sản phẩm",
    links: [
      { label: "Phân tích CV", href: "#cach-dung" },
      { label: "Tối ưu CV", href: "#cach-dung" },
      { label: "Luyện phỏng vấn", href: "#cach-dung" },
      { label: "Theo dõi tiến bộ", href: "#cach-dung" },
    ],
  },
  {
    title: "Dành cho",
    links: [
      { label: "Sinh viên", href: "/register" },
      ...(ADVISOR_FEATURES ? [{ label: "Cố vấn hướng nghiệp", href: "/login" }] : []),
    ],
  },
  {
    title: "Hỗ trợ",
    links: [
      { label: "Hỏi đáp", href: "#hoi-dap" },
      { label: "Cam kết dữ liệu", href: "#cam-ket" },
      { label: "Chính sách dữ liệu", policy: true },
    ],
  },
]

export function LandingFooter() {
  const [policyOpen, setPolicyOpen] = useState(false)
  const linkClass = "text-sm text-ink-2 hover:text-ink"
  return (
    <footer className="border-t border-line">
      <div className="mx-auto grid max-w-[1200px] grid-cols-2 gap-8 px-4 pt-10 pb-10 md:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,1fr))] md:gap-10 md:px-10 md:pt-16 md:pb-14">
        <div className="col-span-2 md:col-span-1">
          <Logo />
          <p className="mt-4 max-w-[300px] text-sm leading-[22px] text-ink-2">Trợ lý hướng nghiệp giúp sinh viên viết CV đúng vị trí và luyện phỏng vấn tự tin hơn.</p>
        </div>
        {COLUMNS.map((col) => (
          <nav key={col.title} aria-label={col.title}>
            <h2 className="mb-3.5 text-sm font-semibold text-ink">{col.title}</h2>
            <ul className="grid gap-2.5">
              {col.links.map((l) => (
                <li key={l.label}>
                  {l.policy ? (
                    <button type="button" onClick={() => setPolicyOpen(true)} className={linkClass}>
                      {l.label}
                    </button>
                  ) : l.href!.startsWith("#") ? (
                    <a href={l.href} className={linkClass}>
                      {l.label}
                    </a>
                  ) : (
                    <Link href={l.href!} className={linkClass}>
                      {l.label}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-x-6 gap-y-1.5 border-t border-line px-4 pt-5 pb-8 text-[13px] text-ink-3 md:px-10">
        <span>© 2026 CareerV</span>
        <span>Thực hiện bởi nhóm T131 · Model Citizens</span>
      </div>
      <DataPolicyDialog open={policyOpen} onOpenChange={setPolicyOpen} />
    </footer>
  )
}
