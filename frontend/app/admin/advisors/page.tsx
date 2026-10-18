import type { Metadata } from "next"
import { notFound } from "next/navigation"

import { AdvisorList } from "@/components/admin/advisor-list"
import { ADVISOR_FEATURES } from "@/lib/config"

export const metadata: Metadata = { title: "Cố vấn" }

export default async function Page({ searchParams }: PageProps<"/admin/advisors">) {
  // Tính năng cố vấn đang tạm ẩn (lib/config.ts)
  if (!ADVISOR_FEATURES) notFound()
  const { q, new: create } = await searchParams
  const initialQuery = typeof q === "string" ? q : ""
  return <AdvisorList key={`${initialQuery}:${create}`} initialQuery={initialQuery} openCreate={create === "1"} />
}
