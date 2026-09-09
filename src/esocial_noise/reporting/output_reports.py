from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..contracts import EmployeeResult, REPORT_COLUMNS
from ..runtime.execution import ExecutionContext
from ..utils import utc_now


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def write_reports(rows: list[EmployeeResult], execution: ExecutionContext, root: Path, started: str, ai_cost_usd: float) -> None:
    execution.output_dir.mkdir(parents=True, exist_ok=True)
    data = pd.DataFrame([row.as_dict() for row in rows], columns=REPORT_COLUMNS)
    csv_path, xlsx_path, markdown_path = execution.output_dir / "diagnostico.csv", execution.output_dir / "diagnostico.xlsx", execution.output_dir / "report.md"
    data.to_csv(csv_path, index=False, encoding="utf-8-sig")
    data.to_excel(xlsx_path, index=False)
    counts = data["status_consulta"].value_counts().to_dict() if not data.empty else {}
    template = (root / "reports" / "report-template.md").read_text(encoding="utf-8")
    values = {"execution_id": execution.execution_id, "started_at": started, "finished_at": utc_now(), "company": execution.company,
              "status": "completed_with_review" if any(row.revisao_humana == "sim" for row in rows) else "completed", "processed": len(rows), "successes": counts.get("completed", 0), "not_found": counts.get("not_found", 0), "inconclusive": counts.get("inconclusive", 0), "errors": counts.get("error", 0) + counts.get("human_review_required", 0), "human_review": sum(row.revisao_humana == "sim" for row in rows),
              "checkpoints": "\n".join(f"- {item['checkpoint']}: {item['status']}" for item in execution.checkpoints) or "- nenhum", "healing": f"- Tentativas: {execution.recovery_attempts}\n- Chamadas IA: {execution.ai_calls}\n- Custo IA: USD {ai_cost_usd:.6f}",
              "employee_rows": "\n".join(
                  f"- {row.cpf}: {row.status_consulta}; agente 02.01.001: {row.ruido_encontrado}; "
                  f"data: {row.data_esocial or 'não lida'} / {row.data_planilha} ({row.data_confere or 'pendente'}); "
                  f"intensidade: {row.intensidade_esocial or 'não lida'} / {row.intensidade_planilha} ({row.intensidade_confere or 'pendente'}); "
                  f"revisão: {row.revisao_humana}"
                  for row in rows
              ), "evidence": "\n".join(f"- {_display_path(item, root)}" for item in sorted(execution.artifact_dir.glob("*")))}
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", str(value))
    markdown_path.write_text(template, encoding="utf-8")
    execution.current_step = "final_report_generated"
    report_files = [_display_path(path, root) for path in (csv_path, xlsx_path, markdown_path)]
    execution.checkpoint("final_report_generated", "ok", {"files": 3}, {"files": report_files}, report_files[:2])
