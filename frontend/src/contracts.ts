export const APP_ID = "ai-novel-world-2026";
export const APP_ROUTE_ID = `${APP_ID}.workbench`;
export const APP_PATH = `/apps/${APP_ID}`;
// QwenPaw host.fetch prefixes /api; callers must pass an API-relative path.
export const HEALTH_PATH = `/${APP_ID}/health`;
export const CHAT_PATH = "/chat";
export const CREATIVE_CENTER_CHAT_PATH = `${CHAT_PATH}?novel_center=1`;
export const WORKBENCH_CHAT_PATH = `${CHAT_PATH}?novel_workbench=1`;
export const CORE_CHAT_ROUTE_ID = "core.chat";
