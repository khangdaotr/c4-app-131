"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useCallback, useEffect, useState } from "react"
import { ChevronRight, LogOut, Search } from "lucide-react"

import { AssistantLauncher } from "@/components/assistant/assistant-launcher"
import { ChatLauncher } from "@/components/chat/chat-launcher"
import { useSignOut } from "@/components/shell/account-actions"
import { CommandPalette, useCommandShortcut } from "@/components/shell/command-palette"
import { getBreadcrumb, shellOf } from "@/components/shell/nav-config"
import { floatingSurface, NotificationMenu } from "@/components/shell/notification-menu"
import { useProfile } from "@/components/shell/profile-context"
import { ThemeToggleButton } from "@/components/shell/theme-switch"
import { UserAvatar } from "@/components/shell/user-avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { ADVISOR_FEATURES } from "@/lib/config"
import type { Role } from "@/lib/types"
import { cn } from "@/lib/utils"

const menuItem =
  "h-10 gap-2.5 rounded-xl px-3 text-sm font-medium text-ink-2 focus:bg-panel focus:text-ink [&_svg]:text-ink-3"

/** Ở đầu trang header trong suốt để thấy dải pastel; cuộn xuống thì có nền mờ và đường kẻ. */
function useScrolled(threshold = 4) {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > threshold)
    onScroll()
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [threshold])
  return scrolled
}

/** Header chuẩn, giống nhau trên mọi trang (DESIGN.md 5.3). Điện thoại: tiêu đề trang thay cho ô tìm kiếm. */
export function AppTopbar({ role }: { role: Role }) {
  const pathname = usePathname()
  const config = shellOf(role)
  const profile = useProfile()
  const signOut = useSignOut()
  const crumbs = getBreadcrumb(config, pathname)
  const pageTitle = crumbs[crumbs.length - 1]?.label
  const scrolled = useScrolled()
  const [searchOpen, setSearchOpen] = useState(false)
  const openSearch = useCallback(() => setSearchOpen(true), [])
  useCommandShortcut(openSearch)

  return (
    <header
      className={cn(
        "sticky top-0 z-30 flex h-16 items-center gap-2.5 border-b px-4 transition-[background-color,border-color] duration-200 sm:px-6 lg:h-[72px] lg:px-10 xl:px-12",
        scrolled ? "border-line bg-background/85 backdrop-blur-md" : "border-transparent",
      )}
    >
      <button
        type="button"
        onClick={openSearch}
        className="glass hidden h-10 max-w-[520px] flex-1 items-center gap-2.5 rounded-[10px] px-3.5 text-sm text-ink-3 shadow-xs transition-colors hover:text-ink-2 lg:flex"
      >
        <Search className="size-4" strokeWidth={1.75} aria-hidden />
        Tìm vị trí, thao tác…
        <kbd className="ml-auto rounded-md bg-surface px-1.5 py-px font-sans text-xs text-ink-2">Ctrl K</kbd>
      </button>
      <div className="min-w-0 flex-1 truncate font-heading text-2xl font-semibold tracking-[-0.02em] lg:hidden">
        {pageTitle}
      </div>
      <div className="hidden flex-1 lg:block" />

      <div className="flex shrink-0 items-center gap-0.5">
        <button
          type="button"
          onClick={openSearch}
          aria-label="Tìm kiếm"
          className="grid size-10 place-items-center rounded-full text-ink-2 transition-colors hover:bg-surface hover:text-ink lg:hidden"
        >
          <Search className="size-[19px]" strokeWidth={1.75} aria-hidden />
        </button>
        {role !== "admin" && <AssistantLauncher />}
        {role !== "admin" && ADVISOR_FEATURES && <ChatLauncher />}
        <NotificationMenu role={role} />
        <ThemeToggleButton />
        <DropdownMenu>
          <DropdownMenuTrigger render={<button type="button" className="ml-1 rounded-full" aria-label="Tài khoản" />}>
            <UserAvatar name={profile?.full_name} src={profile?.avatar_url} className="size-[34px]" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" sideOffset={10} className={cn("w-72 p-2", floatingSurface)}>
            <DropdownMenuGroup>
              <DropdownMenuLabel className="flex items-center gap-3 px-3 pt-2.5 pb-3">
                <UserAvatar name={profile?.full_name} src={profile?.avatar_url} className="size-10" />
                <span className="grid min-w-0">
                  <span className="truncate text-[15px] font-semibold text-ink">{profile?.full_name ?? "…"}</span>
                  <span className="truncate text-[13px] font-normal text-ink-3">{profile?.subtitle}</span>
                </span>
              </DropdownMenuLabel>
            </DropdownMenuGroup>
            <DropdownMenuSeparator className="mx-1 my-1 bg-line" />
            <DropdownMenuItem onClick={signOut} className={menuItem}>
              <LogOut className="size-4" strokeWidth={1.75} aria-hidden />
              Đăng xuất
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <CommandPalette role={role} open={searchOpen} onOpenChange={setSearchOpen} />
    </header>
  )
}

/** Breadcrumb ở dòng riêng dưới header, chỉ hiện ở trang con (có ít nhất một bước cha). */
export function PageCrumbs({ role }: { role: Role }) {
  const pathname = usePathname()
  const config = shellOf(role)
  const crumbs = getBreadcrumb(config, pathname)
  if (crumbs.length < 2) return null

  return (
    <nav aria-label="Breadcrumb" className="relative z-10 pt-1">
      <ol className="flex min-w-0 flex-wrap items-center gap-1 text-sm">
        {crumbs.map((crumb, index) => (
          <li
            key={crumb.label}
            className={cn("flex min-w-0 items-center gap-1", crumb.href && index < crumbs.length - 2 && "hidden sm:flex")}
          >
            {index > 0 && <ChevronRight className="size-3.5 shrink-0 text-ink-3" aria-hidden />}
            {crumb.href ? (
              <Link href={crumb.href} className="truncate text-ink-3 transition-colors hover:text-ink">
                {crumb.label}
              </Link>
            ) : (
              <span className="truncate font-semibold text-ink" aria-current="page">
                {crumb.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  )
}
