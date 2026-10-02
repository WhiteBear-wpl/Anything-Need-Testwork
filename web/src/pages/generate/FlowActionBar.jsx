/** 生成流程吸底操作栏：始终露出上一步、已选数量与主操作 */
export default function FlowActionBar({ meta, children }) {
  return (
    <div className="flow-action-bar">
      <div className="flow-action-meta">{meta}</div>
      <div className="flow-action-buttons">{children}</div>
    </div>
  );
}
