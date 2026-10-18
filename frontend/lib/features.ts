// Feature flag cho chức năng chưa làm xong. Mặc định tắt; bật bằng NEXT_PUBLIC_FEATURE_<TÊN>=true khi cần.

function flag(value: string | undefined): boolean {
  return value === "true"
}

export const features = {
  /** Dòng "hoặc nhập từ Google Drive" khi tải CV (chưa có chức năng nhập thật). */
  driveImport: flag(process.env.NEXT_PUBLIC_FEATURE_DRIVE_IMPORT),
  /**
   * Vai trò cố vấn và mọi tính năng liên quan (chia sẻ tài liệu, nhắn tin, nhận xét, phân công). Đang tạm ẩn; bật lại
   * cần thêm ADVISOR_FEATURES=true ở backend để tài khoản cố vấn đăng nhập được.
   */
  advisor: flag(process.env.NEXT_PUBLIC_FEATURE_ADVISOR),
  /** Nút "Dùng thử bản demo" ở trang Đăng nhập (điền sẵn tài khoản demo). Đang tạm ẩn. */
  demoTry: flag(process.env.NEXT_PUBLIC_FEATURE_DEMO_TRY),
} as const

export type FeatureName = keyof typeof features
