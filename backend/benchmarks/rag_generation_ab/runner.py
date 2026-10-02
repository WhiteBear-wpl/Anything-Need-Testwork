import argparse, asyncio, json
from pathlib import Path
from app.database import SessionLocal
from app.models.evaluation import EvalResult
from app.models.generation import GenerationTask
from benchmarks.rag_generation_ab.orchestrator import execute_pair
from benchmarks.rag_generation_ab.report import render_ab_report, render_interview_report, validate_pair


def write_reports(output: Path, left: dict, right: dict) -> None:
    errors = validate_pair(left, right)
    if errors:
        raise RuntimeError(f"A/B 配对校验失败：{'; '.join(errors)}")
    output.mkdir(parents=True, exist_ok=True)
    (output/'raw-runs.json').write_text(json.dumps({"baseline":left,"treatment":right},ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'report.md').write_text(render_ab_report(left,right),encoding='utf-8')
    retrieval_path = output.parent / 'rag-retrieval-benchmark-20260824' / 'raw-results.json'
    retrieval = json.loads(retrieval_path.read_text(encoding='utf-8')) if retrieval_path.exists() else None
    (output/'interview-report.md').write_text(render_interview_report(left,right,retrieval),encoding='utf-8')

async def main(output: Path):
    db = SessionLocal()
    try:
        a, b = await execute_pair(db); db.refresh(a); db.refresh(b)
        def payload(run):
            results = db.query(EvalResult).filter(EvalResult.run_id == run.id).all()
            task_ids = [result.task_id for result in results if result.task_id is not None]
            tasks = db.query(GenerationTask).filter(GenerationTask.id.in_(task_ids)).all() if task_ids else []
            return {
                "run_id": run.id,
                "status": run.status,
                "error_message": run.error_message,
                "sample_fingerprint": run.sample_set_fingerprint,
                "config": json.loads(run.config_snapshot),
                "metrics": json.loads(run.metrics or "{}"),
                "sample_results": {
                    str(result.sample_id): {
                        "status": result.status,
                        "task_id": result.task_id,
                        "metrics": json.loads(result.metrics or "{}"),
                        "error_summary": result.error_summary,
                    }
                    for result in results
                },
                "knowledge_refs": {
                    str(task.id): json.loads(task.knowledge_refs)
                    for task in tasks
                    if task.knowledge_refs
                },
            }
        write_reports(output, payload(a), payload(b))
    finally: db.close()

if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--output-dir',type=Path,required=True); p.add_argument('--report-only',action='store_true'); args=p.parse_args()
    if args.report_only:
        raw = json.loads((args.output_dir/'raw-runs.json').read_text(encoding='utf-8'))
        write_reports(args.output_dir, raw['baseline'], raw['treatment'])
    else:
        asyncio.run(main(args.output_dir))
