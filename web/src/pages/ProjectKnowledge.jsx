import { useParams } from 'react-router-dom';
import KnowledgePanel from '../components/KnowledgePanel';
import PageHeader from '../components/PageHeader';

/** 项目内知识库：保持项目侧栏上下文 */
export default function ProjectKnowledge() {
  const { projectId } = useParams();

  return (
    <div>
      <PageHeader
        title="知识库"
        description="沉淀本项目的业务规则、接口文档、缺陷记录。开启「知识库检索」后，AI 生成用例前会检索相关知识注入提示词。"
      />
      <KnowledgePanel key={projectId} projectId={Number(projectId)} />
    </div>
  );
}
