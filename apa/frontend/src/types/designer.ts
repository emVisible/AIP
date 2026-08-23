/** 设计器共享类型 —— 所有设计器相关组件统一引用此文件。 */

export interface DStep {
  id: string;
  type: string;
  action: string;
  target: string;
  params_json: string;
  condition: string;
  output_as: string;
  on_failure_goto: string;
}

export interface ProcessMeta {
  id: string;
  trigger_name: string;
  max_actions: number;
}
