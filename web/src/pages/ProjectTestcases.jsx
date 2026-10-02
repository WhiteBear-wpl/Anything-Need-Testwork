import { useParams } from 'react-router-dom';
import TestCaseLibrary from './TestCaseLibrary';

/** 项目内用例库：保持项目侧栏上下文，仅展示当前项目的用例 */
export default function ProjectTestcases() {
  const { projectId } = useParams();
  return <TestCaseLibrary key={projectId} scopeProjectId={Number(projectId)} />;
}
