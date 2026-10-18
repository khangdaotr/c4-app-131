import { ADVISOR_FEATURES } from "@/lib/config"

import { Commitments } from "./commitments"
import { ForAdvisors } from "./for-advisors"
import { HowItWorks } from "./how-it-works"
import { LandingFaq } from "./landing-faq"
import { LandingCta, LandingFooter } from "./landing-footer"
import { LandingHero } from "./landing-hero"
import { LandingNav } from "./landing-nav"
import { PainPoints } from "./pain-points"

/**
 * Trang giới thiệu (DESIGN.md 7): hero kiểu Family → 3 khó khăn của sinh viên → 4 bước hiện dần khi cuộn →
 * dải tối Cam kết → Cho cố vấn → Hỏi đáp → lời mời → chân trang. Viết cho sinh viên; không nêu tên người cụ thể.
 */
export function LandingPage() {
  return (
    <div className="relative min-h-screen overflow-x-clip bg-background text-ink">
      <LandingNav />
      <main>
        <LandingHero />
        <PainPoints />
        <HowItWorks />
        <Commitments />
        {/* Tính năng cố vấn đang tạm ẩn (lib/config.ts) */}
        {ADVISOR_FEATURES && <ForAdvisors />}
        <LandingFaq />
        <LandingCta />
      </main>
      <LandingFooter />
    </div>
  )
}
