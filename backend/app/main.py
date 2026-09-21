from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import cases, execute, reports, rca

app = FastAPI(title='AI 智能测试一体化平台', version='0.1.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(cases.router, prefix='/api/v1', tags=['cases'])
app.include_router(execute.router, prefix='/api/v1', tags=['execute'])
app.include_router(reports.router, prefix='/api/v1', tags=['reports'])
app.include_router(rca.router, prefix='/api/v1', tags=['rca'])


@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok'}
