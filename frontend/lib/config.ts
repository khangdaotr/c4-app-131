import { features } from "@/lib/features"

const rawApiUrl = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "")

// Khi chạy trên browser tại môi trường đã deploy (không phải localhost), dùng relative path ""
// để request đi qua Next.js rewrites proxy. Điều này biến cookie thành First-Party Cookie,
// giúp Safari / iOS Messenger / Chrome không bao giờ chặn cookie phiên đăng nhập.
export const API_BASE_URL =
  typeof window !== "undefined" && rawApiUrl.startsWith("http") && !rawApiUrl.includes("localhost")
    ? ""
    : rawApiUrl

/**
 * Nhóm API trong lib/api.ts. Mỗi nhóm được chuyển từ mock sang backend thật độc lập,
 * để nối từng luồng một mà các trang còn lại vẫn chạy bằng mock.
 */
export type ApiGroup =
  | "me"
  | "notifications"
  | "overview"
  | "cv"
  | "gap"
  | "optimizer"
  | "interview"
  | "feedback"
  | "sharing"
  | "settings"
  | "advisor"
  | "messages"
  | "auth"
  | "admin"

// NEXT_PUBLIC_LIVE_APIS: danh sách nhóm gọi backend thật, cách nhau bởi dấu phẩy (ví dụ "me,cv"),
// hoặc "all" cho tất cả. Để trống = toàn bộ dùng mock.
const LIVE_APIS = new Set(
  (process.env.NEXT_PUBLIC_LIVE_APIS ?? "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean),
)

export const ALL_LIVE = LIVE_APIS.has("all")

export function isLive(group: ApiGroup): boolean {
  return ALL_LIVE || LIVE_APIS.has(group)
}

/**
 * Trình tối ưu CV mở được: khi còn mock toàn bộ, hoặc khi nhóm "optimizer" đã nối backend.
 * Phân tích thật mà trình tối ưu còn mock thì mock không mở được lượt phân tích thật → tạm khoá ("Sắp có").
 */
export const OPTIMIZER_AVAILABLE = isLive("optimizer") || !isLive("gap")

// Kịch bản dữ liệu mock: "empty" (mặc định, tài khoản demo sinh viên chưa có gì, giống tài khoản mới tạo)
// | "sample" (Minh Anh có sẵn CV, phân tích, phỏng vấn… để xem thiết kế). Cố vấn demo luôn có nhóm SV mẫu.
export const MOCK_SCENARIO = process.env.NEXT_PUBLIC_MOCK_SCENARIO ?? "empty"

/** Vai trò cố vấn và các tính năng liên quan (tạm ẩn, xem lib/features.ts). */
export const ADVISOR_FEATURES = features.advisor

/** Nút "Dùng thử bản demo" ở trang Đăng nhập (tạm ẩn, xem lib/features.ts). */
export const DEMO_TRY = features.demoTry
