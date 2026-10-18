import {
  FileText,
  LayoutGrid,
  Library,
  MessagesSquare,
  ScanText,
  SlidersHorizontal,
  TrendingUp,
  UserRoundCheck,
  Users,
  type LucideIcon,
} from "lucide-react"

import { ADVISOR_FEATURES } from "@/lib/config"
import type { Role } from "@/lib/types"

export interface NavItem {
  href: string
  label: string
  icon: LucideIcon
  /** Tiền tố URL để đánh dấu mục đang chọn; mặc định = href (khớp chính xác). */
  match?: string
  /** Tiêu đề nhóm trên sidebar; mục liền sau cùng nhóm thì không lặp lại tiêu đề. */
  group?: string
  /** Nhãn ngắn trên thanh tab điện thoại; không có thì mục nằm trong sheet "Tôi". */
  tab?: string
}

export interface Crumb {
  label: string
  /** null cho trang hiện tại. */
  href: string | null
}

/** Trang không nằm trong menu (trang chi tiết, bước con trong một luồng...). */
interface ExtraPage {
  pattern: RegExp
  title: string
  /** Các bước cha trong breadcrumb, dựng từ kết quả khớp của pattern. */
  parents?: (match: RegExpMatchArray) => Crumb[]
}

export interface ShellConfig {
  role: Role
  nav: NavItem[]
  extraPages: ExtraPage[]
}

const analysisRoot: Crumb = { label: "Phân tích CV & JD", href: "/student/analysis/new" }
const analysisResult = (id: string): Crumb => ({ label: "Kết quả phân tích", href: `/student/analysis/${id}` })

// Menu sinh viên chia nhóm (DESIGN.md 5.2). "Trình tối ưu CV" và "Xuất CV" không có mục riêng mà đi theo luồng
// Phân tích CV & JD → Trình tối ưu CV → Xuất CV (/student/analysis/[id]/optimize, /export).
export const studentShell: ShellConfig = {
  role: "student",
  nav: [
    { href: "/student", label: "Tổng quan", icon: LayoutGrid, tab: "Tổng quan" },
    { href: "/student/cv", label: "CV của tôi", icon: FileText, match: "/student/cv", group: "Hồ sơ" },
    { href: "/student/library", label: "Thư viện JD", icon: Library, match: "/student/library", group: "Hồ sơ", tab: "Thư viện" },
    { href: "/student/analysis/new", label: "Phân tích CV & JD", icon: ScanText, match: "/student/analysis", group: "Luyện tập", tab: "Phân tích" },
    { href: "/student/interview/new", label: "Luyện phỏng vấn", icon: MessagesSquare, match: "/student/interview", group: "Luyện tập", tab: "Phỏng vấn" },
    { href: "/student/history", label: "Tiến bộ", icon: TrendingUp, group: "Luyện tập" },
    // Tính năng cố vấn đang tạm ẩn (lib/config.ts)
    ...(ADVISOR_FEATURES ? [{ href: "/student/share", label: "Chia sẻ với cố vấn", icon: Users, group: "Tài khoản" }] : []),
    { href: "/student/settings", label: "Cài đặt", icon: SlidersHorizontal, group: "Tài khoản" },
  ],
  extraPages: [
    {
      pattern: /^\/student\/analysis\/([^/]+)\/optimize$/,
      title: "Trình tối ưu CV",
      parents: (m) => [analysisRoot, analysisResult(m[1])],
    },
    {
      pattern: /^\/student\/analysis\/([^/]+)\/export$/,
      title: "Xuất CV",
      parents: (m) => [
        analysisRoot,
        analysisResult(m[1]),
        { label: "Trình tối ưu CV", href: `/student/analysis/${m[1]}/optimize` },
      ],
    },
    {
      pattern: /^\/student\/analysis\/compare$/,
      title: "So sánh",
      parents: () => [analysisRoot],
    },
    {
      // Lượt so sánh đã lưu, mở từ Dòng thời gian
      pattern: /^\/student\/analysis\/compare\/[^/]+$/,
      title: "So sánh",
      parents: () => [{ label: "Lịch sử & tiến bộ", href: "/student/history" }],
    },
    {
      pattern: /^\/student\/analysis\/(?!new$|compare$)[^/]+$/,
      title: "Kết quả phân tích",
      parents: () => [analysisRoot],
    },
    {
      pattern: /^\/student\/interview\/[^/]+\/report$/,
      title: "Báo cáo phỏng vấn",
      parents: () => [{ label: "Luyện phỏng vấn", href: "/student/interview/new" }],
    },
    {
      pattern: /^\/student\/library\/[^/]+$/,
      title: "Chi tiết vị trí",
      parents: () => [{ label: "Thư viện JD", href: "/student/library" }],
    },
    {
      pattern: /^\/student\/cv\/[^/]+$/,
      title: "Chi tiết CV",
      parents: () => [{ label: "CV của tôi", href: "/student/cv" }],
    },
    { pattern: /^\/student\/settings$/, title: "Cài đặt" },
  ],
}

export const advisorShell: ShellConfig = {
  role: "advisor",
  nav: [
    { href: "/advisor", label: "Tổng quan", icon: LayoutGrid, tab: "Tổng quan" },
    { href: "/advisor/students", label: "Sinh viên phụ trách", icon: Users, match: "/advisor/students", group: "Sinh viên", tab: "Sinh viên" },
  ],
  extraPages: [
    {
      pattern: /^\/advisor\/students\/[^/]+$/,
      title: "Hồ sơ sinh viên",
      parents: () => [{ label: "Sinh viên phụ trách", href: "/advisor/students" }],
    },
  ],
}

// Quản trị (bản vẽ QuanTriTongQuan, QuanTriCoVan, QuanTriSinhVien): ba trang riêng, không gộp
export const adminShell: ShellConfig = {
  role: "admin",
  nav: [
    { href: "/admin", label: "Tổng quan", icon: LayoutGrid, tab: "Tổng quan" },
    ...(ADVISOR_FEATURES
      ? [{ href: "/admin/advisors", label: "Cố vấn", icon: UserRoundCheck, match: "/admin/advisors", group: "Quản lý", tab: "Cố vấn" }]
      : []),
    { href: "/admin/students", label: "Sinh viên", icon: Users, match: "/admin/students", group: "Quản lý", tab: "Sinh viên" },
    { href: "/admin/jds", label: "Thư viện JD", icon: Library, match: "/admin/jds", group: "Quản lý", tab: "JD" },
  ],
  extraPages: [
    { pattern: /^\/admin\/feedback$/, title: "Nhận xét", parents: () => [{ label: "Tổng quan", href: "/admin" }] },
    { pattern: /^\/admin\/jds\/new$/, title: "Thêm JD", parents: () => [{ label: "Thư viện JD", href: "/admin/jds" }] },
    { pattern: /^\/admin\/jds\/[^/]+$/, title: "Sửa JD", parents: () => [{ label: "Thư viện JD", href: "/admin/jds" }] },
  ],
}

export function shellOf(role: Role): ShellConfig {
  return role === "admin" ? adminShell : role === "advisor" ? advisorShell : studentShell
}

export function isNavActive(item: NavItem, pathname: string): boolean {
  const prefix = item.match ?? item.href
  return item.match ? pathname === prefix || pathname.startsWith(`${prefix}/`) : pathname === item.href
}

/** Breadcrumb trên topbar: các bước cha (có link) và trang hiện tại (href null). */
export function getBreadcrumb(config: ShellConfig, pathname: string): Crumb[] {
  for (const page of config.extraPages) {
    const match = pathname.match(page.pattern)
    if (match) return [...(page.parents?.(match) ?? []), { label: page.title, href: null }]
  }
  const item = config.nav.find((nav) => isNavActive(nav, pathname)) ?? config.nav[0]
  return [{ label: item.label, href: null }]
}
