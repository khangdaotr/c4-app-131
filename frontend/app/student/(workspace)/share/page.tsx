import type { Metadata } from "next"
import { notFound } from "next/navigation"

import { ShareWithAdvisor } from "@/components/student/share/share-with-advisor"
import { ADVISOR_FEATURES } from "@/lib/config"

export const metadata: Metadata = { title: "Chia sẻ với cố vấn" }

export default function Page() {
  // Tính năng cố vấn đang tạm ẩn (lib/config.ts)
  if (!ADVISOR_FEATURES) notFound()
  return <ShareWithAdvisor />
}
