from fastapi import APIRouter

from app.models.schemas import ReportSummary

router = APIRouter()


@router.get('/reports/summary', response_model=ReportSummary)
def get_report_summary() -> ReportSummary:
    return ReportSummary(
        pass_rate=96.8,
        fail_rate=3.2,
        coverage=87.0,
        avg_time='2.4 min',
        trend=[58, 70, 66, 82, 88, 93, 96],
    )
