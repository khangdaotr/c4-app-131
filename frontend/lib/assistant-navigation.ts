import { ADVISOR_FEATURES } from "@/lib/config"
import type { UIAction, UserRole } from "@/types/assistant"
import routeData from "@/resources/routes.json"
import uiData from "@/resources/ui_registry.json"

interface RegistryRoute {
  path_template: string
  roles: string[]
  aliases: string[]
  params: string[]
}
const routes: Record<string, RegistryRoute> = routeData
const elements: Record<string, { route_id: string; roles: string[] }> = uiData
const identifier = /^[\w-]{1,64}$/
const reserved = new Set(["new", "start", "compare"])

export function resolveUIRoute(action: Extract<UIAction, { type: "navigate" }>, role: UserRole): string | null {
  if (!Object.prototype.hasOwnProperty.call(routes, action.route_id)) return null
  const entry = routes[action.route_id]
  if (!entry.roles.includes(role) || !action.params || typeof action.params !== "object" || Array.isArray(action.params)) return null
  if (Object.keys(action.params).length !== entry.params.length) return null
  let path = entry.path_template
  for (const key of entry.params) {
    const value = action.params[key]
    if (typeof value !== "string" || !identifier.test(value) || reserved.has(value)) return null
    path = path.replace("{" + key + "}", value)
  }
  // Tính năng cố vấn đang tạm ẩn (lib/config.ts): trợ lý không mở trang chia sẻ hay trang của cố vấn
  if (!ADVISOR_FEATURES && (path === "/student/share" || path.startsWith("/advisor"))) return null
  return path
}

export function resolveUIElement(elementId: string, role: UserRole): { selector: string; route: string } | null {
  if (!Object.prototype.hasOwnProperty.call(elements, elementId)) return null
  const entry = elements[elementId]
  if (!entry.roles.includes(role) || !identifier.test(elementId)) return null
  const route = resolveUIRoute({ type: "navigate", route_id: entry.route_id, params: {} }, role)
  return route ? { selector: '[data-assistant-id="' + elementId + '"]', route } : null
}

/** The compatibility path guard and v2 dispatcher share the server registry. */
export function resolveAssistantRoute(route: unknown, role: UserRole): string | null {
  if (typeof route !== "string") return null
  for (const [route_id, entry] of Object.entries(routes)) {
    if (!entry.roles.includes(role)) continue
    if (entry.aliases.includes(route)) return entry.path_template
    const pattern = entry.path_template.replace(/\{\w+\}/g, "([\\w-]{1,64})")
    const match = new RegExp("^" + pattern + "$").exec(route)
    if (match) {
      const params = Object.fromEntries(entry.params.map((key, i) => [key, match[i + 1]]))
      const resolved = resolveUIRoute({ type: "navigate", route_id, params }, role)
      if (resolved) return resolved
    }
  }
  return null
}
