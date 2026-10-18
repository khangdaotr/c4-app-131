"use client"

import { useRouter } from "next/navigation"
import { useEffect, useState, type ReactNode } from "react"

import { api, ApiError } from "@/lib/api"
import { ADVISOR_FEATURES, isLive } from "@/lib/config"
import { clearAuthMode, getAuthMode, homeOf } from "@/lib/session"
import type { Role } from "@/lib/types"

/**
 * Chỉ hiện khung ứng dụng khi đã đăng nhập đúng vai trò (kể cả tài khoản demo), để không gọi API khi chưa có phiên:
 * - Chưa đăng nhập → trang Đăng nhập.
 * - Mở khu vực của vai trò khác → về trang chủ của vai trò mình.
 * - Còn mật khẩu tạm (cố vấn do quản trị viên tạo tài khoản) → trang Đặt mật khẩu của bạn.
 * - Đã nối API tài khoản thật mà phiên hết hạn → Đăng nhập kèm thông báo.
 */
export function AuthGuard({ role, children }: { role: Role; children: ReactNode }) {
  const router = useRouter()
  const [ready, setReady] = useState(false)
  useEffect(() => {
    const mode = getAuthMode()
    if (!mode) {
      router.replace("/login")
      return
    }
    if (mode.role === "advisor" && !ADVISOR_FEATURES) {
      // Vai trò cố vấn đang tạm ẩn (lib/config.ts): phiên cố vấn còn lưu thì đăng xuất
      clearAuthMode()
      router.replace("/login")
      return
    }
    if (mode.mustChangePassword) {
      router.replace("/change-password")
      return
    }
    if (mode.role !== role) {
      router.replace(homeOf(mode.role))
      return
    }
    // localStorage chỉ đọc được ở trình duyệt nên phải xét sau khi gắn vào trang
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setReady(true)
    if (!isLive("auth")) return
    api.getMe(role).catch((err) => {
      if (err instanceof ApiError && err.status === 401) {
        clearAuthMode()
        router.replace("/login?expired=1")
      }
    })
  }, [role, router])
  return ready ? children : null
}
