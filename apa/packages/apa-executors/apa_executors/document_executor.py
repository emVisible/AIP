"""apa-executors: DocumentExecutor（设计文档 §5.1 文档域）。

PDF/Word/Excel/扫描件。POC 感知策略：文本层提取（pdfplumber 可选，
无依赖时退回纯文本读取）+ 确定性字段正则。OCR/LLM 提取为后续阶段。
动作：doc.extract_text / doc.extract_fields / doc.classify。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Tuple

from apa_sdk import AIPExecutor, ExecutorPreconditionError

# 发票/单据常用字段（POC 内置；可由 schema.yaml 扩展）
FIELD_PATTERNS: Dict[str, list] = {
    "invoice_no": [r"发票号\s*[:：]?\s*([A-Za-z0-9\-]+)",
                   r"Invoice\s*(?:No\.?|Number)\s*[:：]?\s*([A-Za-z0-9\-]+)"],
    "date": [r"日期\s*[:：]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
             r"Date\s*[:：]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})"],
    "total": [r"(?:价税合计|合计金额|总额|Total(?:\s*Amount)?)\s*[:：]?\s*[¥￥$]?\s*([\d,]+(?:\.\d+)?)"],
    "vendor": [r"(?:供应商|销售方|Vendor|Seller)\s*[:：]\s*(\S+)"],
}


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(str(path)) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except ImportError:
            raise ExecutorPreconditionError(
                "pdfplumber_missing", "pip install pdfplumber to read PDF text")
    # txt / csv / md 等：直接读
    return path.read_text(encoding="utf-8", errors="replace")


class DocumentExecutor(AIPExecutor):
    def start_observation(self) -> None:
        """文档执行器被动触发（事件由外部注入，如文件监听器）。"""

    def _execute_action(self, name: str, params: dict) -> Tuple[bool, dict]:
        match name:
            case "doc.extract_text":
                path = Path(params["document_ref"])
                if not path.exists():
                    return False, {"code": "document_not_found"}
                text = _extract_text(path)
                ref = params.get("output_context") or \
                    self.context_store.make_ref(self.peer.session_id, "doc_text")
                self.context_store.put(ref, {"text": text,
                                             "chars": len(text),
                                             "path": str(path)})
                return True, {"output_context": ref, "chars": len(text)}

            case "doc.extract_fields":
                path = Path(params["document_ref"])
                if not path.exists():
                    return False, {"code": "document_not_found"}
                text = _extract_text(path)
                fields = self._lift_fields(text)
                ref = params.get("output_context") or \
                    self.context_store.make_ref(self.peer.session_id, "doc_fields")
                self.context_store.put(ref, fields)
                return True, {"output_context": ref, **fields}

            case "doc.classify":
                path = Path(params["document_ref"])
                if not path.exists():
                    return False, {"code": "document_not_found"}
                text = _extract_text(path).lower()
                doc_type = self._classify(text)
                return True, {"doc_type": doc_type}

            case _:
                return False, {"code": "action_not_supported_by_executor"}

    @staticmethod
    def _lift_fields(text: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for field, patterns in FIELD_PATTERNS.items():
            for pat in patterns:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    out[field] = m.group(1).strip()
                    break
        # 金额数值化（供 schema number 校验与规则比较）
        if "total" in out:
            try:
                out["total_num"] = float(out["total"].replace(",", ""))
            except ValueError:
                pass
        return out

    @staticmethod
    def _classify(text: str) -> str:
        if "发票" in text or "invoice" in text:
            return "invoice"
        if "订单" in text or "order" in text:
            return "order"
        if "合同" in text or "contract" in text:
            return "contract"
        return "unknown"