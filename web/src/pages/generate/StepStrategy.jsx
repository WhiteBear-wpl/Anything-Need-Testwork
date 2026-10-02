import { Button, Card, Checkbox, Divider, Progress, Switch, Tag } from 'antd';
import { Link } from 'react-router-dom';
import FlowActionBar from './FlowActionBar';

export default function StepStrategy({
  document,
  strategies,
  selectedPreset,
  onApplyPreset,
  specialistOptions,
  specialistSkills,
  onToggleSpecialistSkill,
  moduleGroups,
  estimate,
  useKnowledge,
  onToggleKnowledge,
  knowledgeReadyCount,
  projectId,
  loading,
  onBack,
  onOpenGenerateConfirm,
}) {
  return (
    <>
    <Card className="surface-card" title="选择生成策略">
      {document?.status !== 'confirmed' && (
        <div style={{ marginBottom: 16, padding: 12, background: '#fff7ed', borderRadius: 8, color: '#c2410c' }}>
          功能点已修改，请返回「确认功能点」步骤重新确认后再生成。
        </div>
      )}

      <div className="strategy-section-label">用例策略</div>
      <div className="strategy-grid strategy-grid-two">
        {strategies.map((s) => (
          <div
            key={s.key}
            className={`strategy-card${selectedPreset === s.key ? ' selected' : ''}`}
            onClick={() => onApplyPreset(s.key)}
            role="button"
            tabIndex={0}
          >
            <div className="strategy-card-icon">{s.icon}</div>
            <div className="strategy-card-title">
              {s.title}
              {s.recommended && <Tag color="blue" style={{ marginLeft: 8 }}>推荐</Tag>}
            </div>
            <div className="strategy-card-desc">{s.desc}</div>
            <div className="strategy-card-tags">
              <Tag>每功能点 {s.minCasesPerFeature}～{s.maxCasesPerFeature} 条</Tag>
            </div>
          </div>
        ))}
      </div>

      <Divider />

      <div className="strategy-section-label">专项 Skill（可选，团队分工）</div>
      <div className="specialist-skills-list">
        {specialistOptions.map(({ key, label, desc }) => (
          <div key={key} className="specialist-skill-row">
            <Checkbox
              checked={specialistSkills.includes(key)}
              onChange={(e) => onToggleSpecialistSkill(key, e.target.checked)}
            >
              <span className="specialist-skill-label">{label}</span>
            </Checkbox>
            <span className="specialist-skill-desc">{desc}</span>
          </div>
        ))}
      </div>

      <Divider />

      <div className="strategy-section-label">知识库检索（RAG）</div>
      <div className="specialist-skill-row" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Switch
          checked={useKnowledge}
          disabled={knowledgeReadyCount === 0}
          onChange={onToggleKnowledge}
        />
        {knowledgeReadyCount > 0 ? (
          <span className="specialist-skill-desc">
            生成前检索项目知识库（{knowledgeReadyCount} 篇已入库），把相关业务规则注入提示词，减少幻觉
          </span>
        ) : (
          <span className="specialist-skill-desc">
            项目知识库为空，可先到
            <Link to={`/projects/${projectId}/knowledge`}> 知识库 </Link>
            上传业务规则、接口文档等资料
          </span>
        )}
      </div>

      <Divider />

      <div className="strategy-section-label">待生成功能点</div>
      <div className="module-skills-list">
        {Object.entries(moduleGroups).map(([mod, items]) => (
          <div key={mod} className="module-skill-row module-skill-row-readonly">
            <div className="module-skill-info">
              <div className="module-skill-name">{mod}</div>
              <div className="module-skill-meta">{items.length} 个功能点</div>
            </div>
            <div className="module-skill-meta">
              {items.map(i => i.feature).join('、')}
            </div>
          </div>
        ))}
      </div>

      <Card size="small" className="strategy-estimate" style={{ marginTop: 20 }}>
        <div className="strategy-estimate-grid">
          <div><strong>{estimate.featureCount}</strong><span>功能点</span></div>
          <div><strong>{estimate.moduleCount}</strong><span>模块</span></div>
          <div><strong>{estimate.skillCalls}</strong><span>Skill 调用</span></div>
          <div><strong>{estimate.minCases}～{estimate.maxCases}</strong><span>预估用例</span></div>
        </div>
      </Card>

      {loading && (
        <div style={{ textAlign: 'center', marginTop: 24 }}>
          <Progress type="circle" percent={30} size={48} status="active" />
          <div style={{ marginTop: 8, color: '#64748b' }}>正在启动生成任务...</div>
        </div>
      )}
    </Card>
    <FlowActionBar
      meta={(
        <span>
          <strong>{estimate.featureCount}</strong> 个功能点 ·
          预估 <strong>{estimate.minCases}～{estimate.maxCases}</strong> 条用例
        </span>
      )}
    >
      <Button onClick={onBack}>上一步</Button>
      <Button
        type="primary"
        loading={loading}
        disabled={document?.status !== 'confirmed'}
        onClick={onOpenGenerateConfirm}
      >
        确认并开始生成
      </Button>
    </FlowActionBar>
    </>
  );
}
