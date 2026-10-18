import type { ReactNode } from "react"

import { AssistantProvider } from "@/components/assistant/assistant-provider"
import { OnePanelAtATime } from "@/components/assistant/assistant-launcher"
import { ChatPanel as AssistantPanel } from "@/components/assistant/chat-panel"
import { ChatProvider } from "@/components/chat/chat-context"
import { ChatPanel } from "@/components/chat/chat-panel"
import { AppTopbar, PageCrumbs } from "@/components/shell/app-topbar"
import { MobileTabBar } from "@/components/shell/mobile-tab-bar"
import { ProfileProvider } from "@/components/shell/profile-context"
import { SidebarNav } from "@/components/shell/sidebar-nav"
import { ADVISOR_FEATURES } from "@/lib/config"
import type { Role } from "@/lib/types"

/**
 * Khung giao diện chính (DESIGN.md mục 5): sidebar 252px cố định từ 1024px trở lên (thu gọn còn 72px bằng nút cạnh logo
 * hoặc Ctrl B, xem lib/sidebar.ts), dưới 1024px thay bằng thanh tab
 * dưới đáy. Nội dung trải hết chiều rộng còn lại (chỉ có lề), header dính trên cùng khi cuộn.
 * Dải pastel nằm ở đầu vùng nội dung, phía sau header và phần đầu trang.
 * --tabbar-h để các thanh dính đáy (BottomActionBar) nằm trên thanh tab điện thoại.
 * Trợ lý AI hướng dẫn chỉ có ở khu sinh viên và cố vấn; phòng phỏng vấn dùng FocusShell nên không có.
 */
export function AppShell({ role, children }: { role: Role; children: ReactNode }) {
  if (role === "admin") return <Shell role={role}>{children}</Shell>
  return (
    <AssistantProvider>
      <Shell role={role} assistant>
        {children}
      </Shell>
    </AssistantProvider>
  )
}

function Shell({ role, assistant = false, children }: { role: Role; assistant?: boolean; children: ReactNode }) {
  // Quản trị viên không có tin nhắn (chỉ SV và cố vấn phụ trách nhắn cho nhau); tính năng cố vấn tạm ẩn thì không ai có
  const messaging = role !== "admin" && ADVISOR_FEATURES
  return (
    <ProfileProvider role={role}>
      <ChatProvider role={role} enabled={messaging}>
        <div className="min-h-screen bg-background [--tabbar-h:68px] lg:[--tabbar-h:0px]">
          <aside className="fixed inset-y-0 left-0 z-40 hidden w-[252px] overflow-x-hidden overflow-y-auto border-r border-line bg-card transition-[width] duration-200 ease-out lg:block sidebar-collapsed:w-[72px] sidebar-collapsed:overflow-visible">
            <SidebarNav role={role} />
          </aside>
          <div className="flex min-h-screen flex-col overflow-x-clip pb-[var(--tabbar-h)] transition-[padding] duration-200 ease-out lg:pl-[252px] lg:sidebar-collapsed:pl-[72px]">
            <div className="relative flex flex-1 flex-col">
              <div className="aurora-band" aria-hidden />
              <AppTopbar role={role} />
              <div className="relative flex w-full flex-1 flex-col px-4 sm:px-6 lg:px-10 xl:px-12">
                <PageCrumbs role={role} />
                <main className="relative z-[1] flex-1 pt-4 pb-10">{children}</main>
              </div>
            </div>
          </div>
          <MobileTabBar role={role} />
          {assistant && (
            <>
              <OnePanelAtATime />
              <AssistantPanel />
            </>
          )}
        </div>
        {messaging && <ChatPanel />}
      </ChatProvider>
    </ProfileProvider>
  )
}
