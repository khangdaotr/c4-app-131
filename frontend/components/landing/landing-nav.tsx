"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { Menu } from "lucide-react"

import { Logo } from "@/components/brand/logo"
import { ThemeToggleButton } from "@/components/shell/theme-switch"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { ADVISOR_FEATURES } from "@/lib/config"
import { cn } from "@/lib/utils"

export const LANDING_LINKS = [
  { href: "#cach-dung", label: "Cách hoạt động" },
  { href: "#cam-ket", label: "Cam kết" },
  ...(ADVISOR_FEATURES ? [{ href: "#co-van", label: "Cho cố vấn" }] : []),
  { href: "#hoi-dap", label: "Hỏi đáp" },
]

/** Thanh trên dính khi cuộn: trong suốt ở đầu trang, nền trắng mờ + đường kẻ khi đã cuộn. */
export function LandingNav() {
  const [scrolled, setScrolled] = useState(false)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    onScroll()
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [])

  return (
    <header
      className={cn(
        "sticky top-0 z-40 transition-[background-color,box-shadow] duration-200",
        scrolled ? "bg-background/85 shadow-[0_1px_0_var(--line)] backdrop-blur-md" : "bg-transparent",
      )}
    >
      <div className="mx-auto flex h-16 max-w-[1200px] items-center gap-7 px-4 md:h-[72px] md:px-10">
        <Logo />
        <nav aria-label="Mục trên trang" className="hidden gap-7 text-[15px] font-medium lg:flex">
          {LANDING_LINKS.map((l) => (
            <a key={l.href} href={l.href} className="text-ink-2 hover:text-ink">
              {l.label}
            </a>
          ))}
        </nav>
        <span className="flex-1" />
        <ThemeToggleButton className="-mr-3 max-sm:-mr-4" />
        <Button variant="soft" size="brand" className="min-h-10 px-[18px] max-sm:min-h-9 max-sm:px-3.5 max-sm:text-sm" nativeButton={false} render={<Link href="/login" />}>
          Đăng nhập
        </Button>
        <Button variant="dark" size="brand" className="min-h-10 px-[18px] max-sm:hidden" nativeButton={false} render={<Link href="/register" />}>
          Tạo tài khoản
        </Button>
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger render={<Button variant="ghost" size="icon" className="-mr-2 size-10 rounded-full lg:hidden" aria-label="Mở menu" />}>
            <Menu className="size-[22px]" strokeWidth={1.75} />
          </SheetTrigger>
          <SheetContent side="bottom" className="rounded-t-[22px] px-3 pt-3 pb-6">
            <SheetTitle className="px-3 pb-1 text-lg font-semibold">CareerV</SheetTitle>
            <nav aria-label="Mục trên trang" className="grid">
              {LANDING_LINKS.map((l) => (
                <a key={l.href} href={l.href} onClick={() => setOpen(false)} className="rounded-[10px] px-3 py-3 text-[15px] font-medium text-ink-2 hover:bg-surface">
                  {l.label}
                </a>
              ))}
            </nav>
            <div className="grid gap-2.5 px-3 pt-2">
              <Button variant="dark" size="brand" className="h-12" nativeButton={false} render={<Link href="/register" />}>
                Tạo tài khoản miễn phí
              </Button>
              <Button variant="soft" size="brand" className="h-12" nativeButton={false} render={<Link href="/login" />}>
                Đăng nhập
              </Button>
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </header>
  )
}
