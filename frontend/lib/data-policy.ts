// Nội dung Chính sách dữ liệu, dùng ở popup trang Đăng ký và link ở chân trang giới thiệu.
// Hai cam kết "không bán dữ liệu" và "rút đồng ý thì tạm dừng tính năng AI" cần nhóm duyệt trước khi công bố.

import { ADVISOR_FEATURES } from "@/lib/config"

export const DATA_POLICY_UPDATED_AT = "11/10/2026"

export const DATA_POLICY_SUMMARY = [
  "Chỉ dùng dữ liệu để đưa gợi ý cho bạn",
  "Mặc định không ai khác xem được",
  "AI không tự thêm kinh nghiệm vào CV",
  "Tải về hoặc xoá dữ liệu bất cứ lúc nào",
]

export const DATA_POLICY_SECTIONS: { title: string; items: string[] }[] = [
  {
    title: "Chúng tôi thu thập gì",
    items: [
      "Thông tin tài khoản: họ tên, ngày sinh, số điện thoại, email và mật khẩu (lưu dạng đã mã hoá).",
      "CV bạn tải lên và các phiên bản bạn tạo trong Trình tối ưu.",
      "JD bạn dán vào để phân tích.",
      "Câu trả lời phỏng vấn dạng chữ, điểm và báo cáo của từng buổi.",
      "Đánh giá và góp ý bạn gửi cho CareerV.",
    ],
  },
  {
    title: "Dùng để làm gì",
    items: [
      "Phân tích CV với vị trí, gợi ý vị trí phù hợp, gợi ý sửa CV và chấm phỏng vấn theo STAR.",
      "Hiển thị tiến bộ của bạn qua từng phiên bản CV và từng buổi phỏng vấn.",
      "Gửi thông báo theo đúng cài đặt bạn chọn.",
      "Chỉ khi bạn bật \"Đóng góp dữ liệu ẩn danh\" trong Cài đặt: dùng dữ liệu đã bỏ thông tin cá nhân để cải thiện chất lượng gợi ý.",
    ],
  },
  {
    title: "Xử lý bằng AI",
    items: [
      "Nội dung CV, JD và câu trả lời được gửi tới mô hình ngôn ngữ để phân tích và chấm điểm.",
      "AI không tự thêm kinh nghiệm hay kỹ năng vào CV; mọi thay đổi chỉ được áp dụng khi bạn duyệt.",
      "Điểm số giúp bạn biết nên luyện gì, không đảm bảo kết quả tuyển dụng.",
    ],
  },
  {
    title: "Ai xem được dữ liệu của bạn",
    items: [
      "Mặc định chỉ bạn xem được CV, câu trả lời và báo cáo của mình.",
      // Tính năng cố vấn đang tạm ẩn (lib/config.ts)
      ...(ADVISOR_FEATURES
        ? [
            "Cố vấn phụ trách chỉ xem nội dung những mục bạn bật chia sẻ, và mất quyền xem ngay khi bạn tắt.",
            "Cố vấn luôn thấy số liệu tổng hợp: điểm từng buổi, mức thay đổi và ngày hoạt động gần nhất.",
          ]
        : []),
      "CareerV không bán dữ liệu và không chia sẻ cho nhà tuyển dụng.",
    ],
  },
  {
    title: "Quyền của bạn",
    items: [
      "Tải về toàn bộ dữ liệu hoặc xoá tài khoản cùng toàn bộ dữ liệu trong Cài đặt.",
      "Rút lại sự đồng ý bất cứ lúc nào; khi đó các tính năng cần AI sẽ tạm dừng.",
      "Bật hoặc tắt chia sẻ với cố vấn cho từng CV, từng buổi phỏng vấn.",
    ],
  },
]
