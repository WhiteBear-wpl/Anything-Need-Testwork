import PageHeader from '../components/PageHeader';
import EvalPanel from '../components/EvalPanel';

export default function Evaluation() {
  return (
    <div>
      <PageHeader
        title="AI 评测"
        description="用固定的评测样本回归验证 AI 生成能力：调整 Prompt、更换模型或接入 RAG 后，跑同一批样本对比可用率、召回率等指标变化"
      />
      <EvalPanel />
    </div>
  );
}
