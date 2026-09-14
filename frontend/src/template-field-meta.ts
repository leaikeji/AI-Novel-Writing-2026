export interface TemplateFieldMeta {
  label: string;
  placeholder: string;
}


const TEMPLATE_FIELD_META: Readonly<Record<string, TemplateFieldMeta>> = {
  protagonist_identity: { label: "主角身份", placeholder: "请输入主角身份" },
  background_setting: { label: "背景设定", placeholder: "请输入背景设定" },
  core_conflict: { label: "核心冲突", placeholder: "请输入核心冲突" },
  emotional_mainline: { label: "情感主线", placeholder: "请输入情感主线" },
  style_features: { label: "风格特点", placeholder: "请输入风格特点" },
  male_name: { label: "男主名字", placeholder: "请输入男主名字" },
  female_name: { label: "女主名字", placeholder: "请输入女主名字" },
  lead_name: { label: "主角名字", placeholder: "请输入主角名字" },
  core_hook: { label: "核心脑洞", placeholder: "一句话写清故事最重要的设定与冲突" },
  male_identity: { label: "男主身份", placeholder: "身份、处境、欲望与限制" },
  female_identity: { label: "女主身份", placeholder: "身份、处境、欲望与限制" },
  lead_identity: { label: "主角身份", placeholder: "身份、处境、欲望与限制" },
  romance_line: { label: "情感线", placeholder: "两人关系如何建立、误解、变化与确认" },
  growth_line: { label: "成长线", placeholder: "主角如何付出代价并完成改变" },
  mystery_line: { label: "谜团线", placeholder: "谜面、调查、反转和真相" },
  world_rule: { label: "世界规则", placeholder: "能力、技术或时代规则及其代价" },
};


export function templateFieldMeta(key: string): TemplateFieldMeta {
  const known = TEMPLATE_FIELD_META[key];
  if (known) return known;
  const visibleKey = key.length > 0 ? key : "空键";
  return {
    label: `自定义字段（${visibleKey}）`,
    placeholder: "请填写该自定义字段",
  };
}
