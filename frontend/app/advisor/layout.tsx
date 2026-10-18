import { notFound } from "next/navigation"

import { AppShell } from "@/components/shell/app-shell"
import { AuthGuard } from "@/components/shell/auth-guard"
import { ADVISOR_FEATURES } from "@/lib/config"

export default function AdvisorLayout({ children }: LayoutProps<"/advisor">) {
  // Tính năng cố vấn đang tạm ẩn (lib/config.ts)
  if (!ADVISOR_FEATURES) notFound()
  return (
    <AuthGuard role="advisor">
      <AppShell role="advisor">{children}</AppShell>
    </AuthGuard>
  )
}
