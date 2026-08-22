/** 设计器共享类型 —— 职责单一：仅类型，无逻辑。 */

export interface DesignerStep {
  id: string;
  type: string; // "" = action | "ai_decision"
  action: string;
  target?: string;
  params_json: string;
  condition: string;
  output_as: string;
  on_failure_goto: string;
}

export interface DesignerProcess {
  id: string;
  trigger_name: string;
  max_actions: number;
  steps: DesignerStep[];
}
