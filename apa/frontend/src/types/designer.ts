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
  /** foreach 循环体子步骤（引擎 _exec_foreach 原生支持；UI C 工作流） */
  body_steps?: DStep[];
}

export interface ProcessMeta {
  id: string;
  trigger_name: string;
  max_actions: number;
}
