import { create } from "zustand";
export const useDesignerStore = create()((set, get) => ({
    processId: "",
    triggerName: "",
    maxActions: 50,
    steps: [],
    selectedIdx: null,
    setMeta: (patch) => set(patch),
    addStep: (type) => {
        const s = get().steps;
        set({
            steps: [...s, {
                    id: type === "ai_decision"
                        ? `decide_${s.length + 1}`
                        : `step_${s.length + 1}`,
                    type,
                    action: "", target: "", params_json: "{}",
                    condition: "", output_as: "", on_failure_goto: "",
                }],
            selectedIdx: s.length,
        });
    },
    removeStep: (i) => {
        const s = [...get().steps];
        s.splice(i, 1);
        set({ steps: s, selectedIdx: null });
    },
    moveStep: (from, dir) => {
        const s = [...get().steps];
        const to = from + dir;
        if (to < 0 || to >= s.length)
            return;
        const tmp = s[from];
        s[from] = s[to];
        s[to] = tmp;
        set({ steps: s });
    },
    updateStep: (i, patch) => {
        const s = [...get().steps];
        s[i] = { ...s[i], ...patch };
        set({ steps: s });
    },
    selectStep: (idx) => set({ selectedIdx: idx }),
    loadSteps: (steps, meta) => set({ steps, ...(meta ?? {}) }),
    toForm: () => {
        const st = get();
        return {
            id: st.processId,
            trigger_name: st.triggerName,
            max_actions: st.maxActions,
            steps: st.steps,
            error_handlers: [],
        };
    },
}));
