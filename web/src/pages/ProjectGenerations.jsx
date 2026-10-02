import { Card } from 'antd';
import { useParams } from 'react-router-dom';
import GenerationHistory from '../components/GenerationHistory';
import PageHeader from '../components/PageHeader';

/** 项目内生成记录：每次 AI 生成任务的策略、采纳率与覆盖率 */
export default function ProjectGenerations() {
  const { projectId } = useParams();
  return (
    <div>
      <PageHeader
        title="生成记录"
        description="本项目每次 AI 生成任务的策略、用例数、采纳率与覆盖率，未评审完的任务可从这里继续"
      />
      <Card className="surface-card">
        <GenerationHistory key={projectId} projectId={projectId} />
      </Card>
    </div>
  );
}
