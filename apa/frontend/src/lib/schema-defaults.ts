/**
 * 从 JSON Schema 自动生成默认参数值。
 *
 * 规则（影刀同款体验：添加步骤即可运行，参数后调）：
 *   required 字段 → 填合理占位值
 *   有 default → 用 default
 *   enum → 取第一项
 *   可选字段 → 跳过（不填，保持表单干净）
 */

interface SchemaProp {
  type?: string;
  default?: unknown;
  enum?: unknown[];
  description?: string;
}

interface ParamSchema {
  type?: string;
  properties?: Record<string, SchemaProp>;
  required?: string[];
}

/** 按字段名推断智能占位值（比空串更有引导性）。 */
const SMART_PLACEHOLDERS: Record<string, unknown> = {
  url: "https://",
  target: "",
  path: "",
  text: "",
  message: "",
  title: "",
  subject: "(无标题)",
  cmd: "echo hello",
  sql: "SELECT 1",
  pattern: "",
};

export function generateDefaults(schema: ParamSchema | null): Record<string,
  unknown> {
  if (!schema?.properties) return {};

  const out: Record<string, unknown> = {};
  const required = new Set(schema.required ?? []);

  for (const [key, prop] of Object.entries(schema.properties)) {
    // 只填 required 或有显式 default 的字段
    const isRequired = required.has(key);
    const hasDefault = prop.default !== undefined;

    if (!isRequired && !hasDefault) continue;

    if (hasDefault) {
      out[key] = prop.default;
      continue;
    }

    // 智能占位
    if (SMART_PLACEHOLDERS[key] !== undefined) {
      out[key] = SMART_PLACEHOLDERS[key];
      continue;
    }

    if (prop.enum && prop.enum.length > 0) {
      out[key] = prop.enum[0];
      continue;
    }

    switch (prop.type) {
      case "number":
      case "integer":
        out[key] = 0;
        break;
      case "boolean":
        out[key] = false;
        break;
      case "array":
        out[key] = [];
        break;
      case "object":
        out[key] = {};
        break;
      default:
        out[key] = "";
    }
  }

  return out;
}