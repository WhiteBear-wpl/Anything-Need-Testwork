import {
  AimOutlined,
  CheckCircleOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  FlagOutlined,
} from '@ant-design/icons';
import { useEffect, useMemo, useRef, useState } from 'react';
import { App, Form, Steps, Upload } from 'antd';
import { useParams, useSearchParams } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import {
  confirmRequirement, createGeneration, createRequirement, createRequirementItem,
  deleteRequirementItem, editDraft, exportFeatureList, exportGenerationDrafts, generateRequirementScope,
  getGeneration, getKnowledgeDocs, getProjectSkillPolicies, getRequirements, getSkills, importFeatureList,
  resumeGeneration, reviewDrafts, structureRequirement, updateRequirementItem, updateRequirementScope, uploadRequirementFile,
} from '../services/api';
import {
  calcGenerationEstimate, enabledSpecialistOptions, formToScopeJson, groupItemsByModule, mapStrategies,
  scopeToForm, stepsToText, textToSteps,
} from './generate/constants';
import StepImport from './generate/StepImport';
import StepConfirmItems from './generate/StepConfirmItems';
import StepStrategy from './generate/StepStrategy';
import StepReview from './generate/StepReview';
import StepDone from './generate/StepDone';
import { DraftEditModal, GenerateConfirmModal, ItemEditModal } from './generate/FlowModals';

export default function GenerateFlow() {
  const { message } = App.useApp();
  const { projectId } = useParams();
  const [step, setStep] = useState(0);
  const [maxStep, setMaxStep] = useState(0);
  const [form] = Form.useForm();
  const [itemForm] = Form.useForm();
  const [draftForm] = Form.useForm();
  const [document, setDocument] = useState(null);
  const [selectedItems, setSelectedItems] = useState([]);
  const [task, setTask] = useState(null);
  const [selectedDrafts, setSelectedDrafts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [importMode, setImportMode] = useState('text');
  const [selectedFile, setSelectedFile] = useState(null);
  const [itemModalOpen, setItemModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [draftModalOpen, setDraftModalOpen] = useState(false);
  const [editingDraft, setEditingDraft] = useState(null);
  const [selectedPreset, setSelectedPreset] = useState('full');
  const [specialistSkills, setSpecialistSkills] = useState([]);
  const [useKnowledge, setUseKnowledge] = useState(false);
  const [knowledgeReadyCount, setKnowledgeReadyCount] = useState(0);
  const [draftSuiteFilter, setDraftSuiteFilter] = useState('all');
  const [skillCatalog, setSkillCatalog] = useState(null);
  const [skillPolicy, setSkillPolicy] = useState(null);
  const [confirmModalOpen, setConfirmModalOpen] = useState(false);
  const [scopeForm, setScopeForm] = useState({ in_scope: '', out_scope: '', risks: '' });
  const [scopeLoading, setScopeLoading] = useState(false);
  const [scopeSaving, setScopeSaving] = useState(false);
  const [flExporting, setFlExporting] = useState(false);
  const [flImporting, setFlImporting] = useState(false);
  const [flImportFile, setFlImportFile] = useState(null);
  const [draftExporting, setDraftExporting] = useState(false);
  const pollTimerRef = useRef(null);

  const strategies = useMemo(() => mapStrategies(skillCatalog), [skillCatalog]);
  const specialistOptions = useMemo(
    () => enabledSpecialistOptions(skillCatalog, skillPolicy),
    [skillCatalog, skillPolicy],
  );

  const confirmedItems = useMemo(
    () => document?.items?.filter(i => i.confirmed) || [],
    [document?.items],
  );

  const moduleGroups = useMemo(() => groupItemsByModule(confirmedItems), [confirmedItems]);

  const estimate = useMemo(
    () => calcGenerationEstimate(confirmedItems, selectedPreset, specialistSkills, strategies),
    [confirmedItems, selectedPreset, specialistSkills, strategies],
  );

  useEffect(() => {
    getSkills().then(setSkillCatalog).catch(() => setSkillCatalog(null));
    getProjectSkillPolicies(projectId).then(setSkillPolicy).catch(() => setSkillPolicy(null));
  }, [projectId]);

  useEffect(() => {
    const enabledNames = new Set(specialistOptions.map(item => item.key));
    setSpecialistSkills(current => current.filter(name => enabledNames.has(name)));
  }, [specialistOptions]);

  useEffect(() => {
    getKnowledgeDocs(projectId)
      .then((docs) => {
        const ready = docs.filter(d => d.status === 'ready').length;
        setKnowledgeReadyCount(ready);
        setUseKnowledge(ready > 0);
      })
      .catch(() => setKnowledgeReadyCount(0));
  }, [projectId]);

  useEffect(() => {
    setScopeForm(scopeToForm(document?.test_scope));
  }, [document?.id, document?.test_scope]);

  const handleGenerateScope = async () => {
    if (!document) return;
    setScopeLoading(true);
    try {
      const updated = await generateRequirementScope(projectId, document.id);
      setDocument((prev) => ({ ...prev, test_scope: updated.test_scope }));
      setScopeForm(scopeToForm(updated.test_scope));
      message.success('已生成测试范围建议');
    } catch (err) {
      message.error(err.response?.data?.detail || '生成范围失败');
    } finally {
      setScopeLoading(false);
    }
  };

  const handleSaveScope = async () => {
    if (!document) return;
    setScopeSaving(true);
    try {
      const json = formToScopeJson(scopeForm);
      const updated = await updateRequirementScope(projectId, document.id, json);
      setDocument((prev) => ({ ...prev, test_scope: updated.test_scope }));
      message.success('测试范围已保存');
    } catch (err) {
      message.error(err.response?.data?.detail || '保存范围失败');
    } finally {
      setScopeSaving(false);
    }
  };

  const handleExportFeatureList = async (format = 'xlsx') => {
    if (!document) return;
    setFlExporting(true);
    try {
      const res = await exportFeatureList(projectId, document.id, format);
      const ext = format === 'md' ? 'md' : 'xlsx';
      const url = URL.createObjectURL(res.data);
      const a = window.document.createElement('a');
      a.href = url;
      a.download = `${document.title || 'featurelist'}-功能清单.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      message.error('导出失败');
    } finally {
      setFlExporting(false);
    }
  };

  const handleExportDrafts = async (format = 'xlsx') => {
    if (!task) return;
    const smokeOnly = draftSuiteFilter === 'smoke';
    setDraftExporting(true);
    try {
      const res = await exportGenerationDrafts(projectId, task.id, format, smokeOnly);
      const ext = format === 'md' ? 'md' : 'xlsx';
      const suffix = smokeOnly ? '冒烟' : '用例';
      const url = URL.createObjectURL(res.data);
      const a = window.document.createElement('a');
      a.href = url;
      a.download = `${document?.title || 'task'}-任务${task.id}-${suffix}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      message.error(err.response?.data?.detail || '导出失败');
    } finally {
      setDraftExporting(false);
    }
  };

  const handleImportFeatureList = async () => {
    if (!flImportFile) {
      message.warning('请先选择 FeatureList（.xlsx）文件');
      return;
    }
    setFlImporting(true);
    try {
      const doc = await importFeatureList(projectId, flImportFile, form.getFieldValue('title'));
      setDocument(doc);
      setSelectedItems(doc.items.map((i) => i.id));
      setScopeForm(scopeToForm(doc.test_scope));
      setFlImportFile(null);
      goToStep(1);
      message.success(`已导入 ${doc.items.length} 个功能点`);
    } catch (err) {
      message.error(err.response?.data?.detail || '导入失败，请检查文件格式');
    } finally {
      setFlImporting(false);
    }
  };

  const goToStep = (next) => {
    setStep(next);
    setMaxStep(prev => Math.max(prev, next));
  };

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [projectId]);

  // 支持 /generate?task=ID 直达评审步骤（从「生成记录」的继续评审进入），
  // 以及 /generate?doc=ID 恢复到确认功能点 / 选择策略步骤（从工作台「继续工作」进入）
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const taskId = searchParams.get('task');
    const docId = searchParams.get('doc');
    if (taskId) {
      getGeneration(projectId, Number(taskId))
        .then((t) => {
          setTask(t);
          goToStep(3);
          if (t.status === 'generating') pollTask(t.id);
        })
        .catch(() => message.error('生成任务不存在'))
        .finally(() => setSearchParams({}, { replace: true }));
      return;
    }
    if (docId) {
      getRequirements(projectId)
        .then((docs) => {
          const doc = docs.find((d) => d.id === Number(docId));
          if (!doc) {
            message.error('需求文档不存在');
            return;
          }
          setDocument(doc);
          setSelectedItems(
            doc.status === 'confirmed'
              ? doc.items.filter((i) => i.confirmed).map((i) => i.id)
              : doc.items.map((i) => i.id),
          );
          goToStep(doc.status === 'confirmed' ? 2 : 1);
        })
        .catch(() => message.error('加载需求文档失败'))
        .finally(() => setSearchParams({}, { replace: true }));
    }
  }, [projectId]);

  const syncDraftSelection = (drafts) => {
    if (!drafts?.length) return;
    setSelectedDrafts(prev => {
      const adoptedIds = drafts.filter(d => d.review_status === 'adopted').map(d => d.id);
      const userPending = prev.filter(id => {
        const d = drafts.find(x => x.id === id);
        return d && !['adopted', 'rejected'].includes(d.review_status);
      });
      return [...new Set([...adoptedIds, ...userPending])];
    });
  };

  useEffect(() => {
    if (task?.drafts) syncDraftSelection(task.drafts);
  }, [task?.id, task?.status]);

  const handleStepChange = (target) => {
    if (target === step) return;
    if (target > maxStep) return;
    if (target === 1 && !document) return;
    if (target === 2 && !document) return;
    if ((target === 3 || target === 4) && !task) return;
    setStep(target);
  };

  const handleUpload = async () => {
    setLoading(true);
    try {
      let doc;
      if (importMode === 'file') {
        if (!selectedFile) {
          message.warning('请先上传 Word 或 Markdown 文件');
          return;
        }
        doc = await uploadRequirementFile(projectId, selectedFile, form.getFieldValue('title'));
      } else {
        const values = await form.validateFields();
        doc = await createRequirement(projectId, values);
      }
      const structured = await structureRequirement(projectId, doc.id);
      setDocument(structured);
      setSelectedItems(structured.items.map(i => i.id));
      goToStep(1);
      message.success('需求已解析为功能点');
    } catch (err) {
      message.error(err.response?.data?.detail || '导入失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleFileSelect = (file) => {
    const allowed = ['.docx', '.md', '.markdown'];
    if (!allowed.some(ext => file.name.toLowerCase().endsWith(ext))) {
      message.error('仅支持 .docx、.md、.markdown 格式');
      return Upload.LIST_IGNORE;
    }
    setSelectedFile(file);
    if (!form.getFieldValue('title')) {
      form.setFieldValue('title', file.name.replace(/\.[^.]+$/, ''));
    }
    return false;
  };

  const handleConfirm = async () => {
    if (!selectedItems.length) {
      message.warning('请至少选择一个功能点');
      return;
    }
    setLoading(true);
    try {
      const confirmed = await confirmRequirement(projectId, document.id, selectedItems);
      setDocument(confirmed);
      setSelectedPreset('full');
      setSpecialistSkills([]);
      goToStep(2);
    } finally {
      setLoading(false);
    }
  };

  const applyPreset = (presetKey) => {
    setSelectedPreset(presetKey);
  };

  const toggleSpecialistSkill = (skillKey, checked) => {
    setSpecialistSkills(prev => (
      checked ? [...new Set([...prev, skillKey])] : prev.filter(s => s !== skillKey)
    ));
  };

  const openGenerateConfirm = () => {
    if (document?.status !== 'confirmed') {
      message.warning('功能点已变更，请返回上一步重新确认');
      return;
    }
    setConfirmModalOpen(true);
  };

  const handleGenerate = async () => {
    setConfirmModalOpen(false);
    setLoading(true);
    try {
      const payload = {
        document_id: document.id,
        strategy: selectedPreset,
        specialist_skills: specialistSkills,
        use_knowledge: useKnowledge && knowledgeReadyCount > 0,
      };
      const newTask = await createGeneration(projectId, payload);
      setTask(newTask);
      goToStep(3);
      pollTask(newTask.id);
    } catch (err) {
      message.error(err.response?.data?.detail || '启动生成失败');
    } finally {
      setLoading(false);
    }
  };

  const pollTask = (taskId) => {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    pollTimerRef.current = setInterval(async () => {
      const t = await getGeneration(projectId, taskId);
      setTask(t);
      syncDraftSelection(t.drafts || []);
      if (t.status === 'completed' || t.status === 'failed') {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
        if (t.status === 'completed') message.success('生成完成');
        else message.error(t.error_message || '生成失败');
      }
    }, 1500);
  };

  const handleResumeGeneration = async () => {
    if (!task?.id) return;
    setLoading(true);
    try {
      const resumed = await resumeGeneration(projectId, task.id);
      setTask(resumed);
      message.success('已从最近检查点继续生成');
      pollTask(task.id);
    } catch (err) {
      message.error(err.response?.data?.detail || '恢复任务失败');
    } finally {
      setLoading(false);
    }
  };

  const handleAdopt = async () => {
    const toAdopt = selectedDrafts.filter(id => {
      const d = task.drafts.find(x => x.id === id);
      return d && !['adopted', 'rejected'].includes(d.review_status);
    });
    if (!toAdopt.length) return message.warning('请选择未采纳的用例');
    await reviewDrafts(projectId, task.id, { draft_ids: toAdopt, action: 'adopt' });
    message.success(`已采纳 ${toAdopt.length} 条用例`);
    const t = await getGeneration(projectId, task.id);
    setTask(t);
    syncDraftSelection(t.drafts || []);
    if ((t.review_stats?.pending ?? 1) === 0) goToStep(4);
  };

  const handleReject = async (rejectReason = '') => {
    const toReject = selectedDrafts.filter(id => {
      const d = task.drafts.find(x => x.id === id);
      return d && !['adopted', 'rejected'].includes(d.review_status);
    });
    if (!toReject.length) return message.warning('请选择未处理的用例');
    await reviewDrafts(projectId, task.id, { draft_ids: toReject, action: 'reject', reject_reason: rejectReason });
    message.success(`已驳回 ${toReject.length} 条用例`);
    const t = await getGeneration(projectId, task.id);
    setTask(t);
    syncDraftSelection(t.drafts || []);
    if ((t.review_stats?.pending ?? 1) === 0) goToStep(4);
  };

  // 脑图详情抽屉里对单条草稿变更评审结果
  const handleReviewSingle = async (draftId, action, rejectReason = '') => {
    await reviewDrafts(projectId, task.id, { draft_ids: [draftId], action, reject_reason: rejectReason });
    const labels = { adopt: '已采纳', reject: '已驳回', to_confirm: '已标记为待确认' };
    message.success(labels[action] || '已更新');
    const t = await getGeneration(projectId, task.id);
    setTask(t);
    syncDraftSelection(t.drafts || []);
  };

  const handleMarkConfirm = async () => {
    const toMark = selectedDrafts.filter(id => {
      const d = task.drafts.find(x => x.id === id);
      return d && !['adopted', 'rejected'].includes(d.review_status);
    });
    if (!toMark.length) return message.warning('请选择未处理的用例');
    await reviewDrafts(projectId, task.id, { draft_ids: toMark, action: 'to_confirm' });
    message.success(`已标记 ${toMark.length} 条为待确认`);
    const t = await getGeneration(projectId, task.id);
    setTask(t);
    syncDraftSelection(t.drafts || []);
  };

  const handleSelectAllDrafts = () => {
    if (!task?.drafts?.length) return;
    const adoptedIds = task.drafts.filter(d => d.review_status === 'adopted').map(d => d.id);
    const selectableIds = task.drafts
      .filter(d => !['adopted', 'rejected'].includes(d.review_status))
      .map(d => d.id);
    setSelectedDrafts([...new Set([...adoptedIds, ...selectableIds])]);
  };

  const pendingDraftCount = task?.drafts
    ? task.drafts.filter(d => !['adopted', 'rejected'].includes(d.review_status)).length
    : 0;

  const openAddItem = () => {
    setEditingItem(null);
    itemForm.resetFields();
    itemForm.setFieldsValue({ priority: 'P1', module: '', description: '', acceptance_criteria: '', constraints: '' });
    setItemModalOpen(true);
  };

  const openEditItem = (item) => {
    setEditingItem(item);
    itemForm.setFieldsValue(item);
    setItemModalOpen(true);
  };

  const saveItem = async () => {
    const values = await itemForm.validateFields();
    setLoading(true);
    try {
      if (editingItem) {
        const updated = await updateRequirementItem(projectId, document.id, editingItem.id, values);
        setDocument(prev => ({
          ...prev,
          status: 'structured',
          items: prev.items.map(i => (i.id === updated.id ? updated : i)),
        }));
        message.success('功能点已更新');
      } else {
        const created = await createRequirementItem(projectId, document.id, values);      // TODO: add module id        · ·           
        setDocument(prev => ({
          ...prev,
          status: 'structured',
          items: [...prev.items, created],
        }));
        setSelectedItems(prev => [...prev, created.id]);
        message.success('功能点已新增');
      }
      setItemModalOpen(false);
    } catch (err) {
      message.error(err.response?.data?.detail || '保存失败');
    } finally {
      setLoading(false);
    }
  };

  const removeItem = async (itemId) => {
    await deleteRequirementItem(projectId, document.id, itemId);
    setDocument(prev => ({
      ...prev,
      status: 'structured',
      items: prev.items.filter(i => i.id !== itemId),
    }));
    setSelectedItems(prev => prev.filter(id => id !== itemId));
    message.success('已删除');
  };

  const openEditDraft = (draft) => {
    setEditingDraft(draft);
    draftForm.setFieldsValue({
      title: draft.title,
      priority: draft.priority,
      case_type: draft.case_type,
      precondition: draft.precondition,
      steps_text: stepsToText(draft.steps),
      expected_result: draft.expected_result,
    });
    setDraftModalOpen(true);
  };

  const saveDraft = async () => {
    const values = await draftForm.validateFields();
    setLoading(true);
    try {
      const payload = {
        title: values.title,
        priority: values.priority,
        case_type: values.case_type,
        precondition: values.precondition,
        steps: textToSteps(values.steps_text),
        expected_result: values.expected_result,
      };
      const updated = await editDraft(projectId, task.id, editingDraft.id, payload);
      setTask(prev => ({
        ...prev,
        drafts: prev.drafts.map(d => (d.id === updated.id ? updated : d)),
      }));
      message.success('用例已更新');
      setDraftModalOpen(false);
    } catch (err) {
      message.error(err.response?.data?.detail || '保存失败');
    } finally {
      setLoading(false);
    }
  };

  const handleNewTask = () => {
    setStep(0);
    setMaxStep(0);
    setTask(null);
    setDocument(null);
  };

  const stepItems = [
    { title: '导入需求', icon: <FileSearchOutlined /> },
    { title: '确认功能点', icon: <AimOutlined /> },
    { title: '选择策略', icon: <ExperimentOutlined /> },
    { title: '评审采纳', icon: <CheckCircleOutlined /> },
    { title: '完成', icon: <FlagOutlined /> },
  ];

  return (
    <div>
      <PageHeader
        title="AI 用例生成"
        description="四步完成：导入需求 → 确认功能点 → 选择策略 → 评审采纳入库（可点击步骤返回上一步）"
      />

      <div className="wizard-steps">
        <Steps current={step} onChange={handleStepChange} items={stepItems} />
      </div>

      {step === 0 && (
        <StepImport
          form={form}
          importMode={importMode}
          setImportMode={setImportMode}
          selectedFile={selectedFile}
          setSelectedFile={setSelectedFile}
          flImportFile={flImportFile}
          setFlImportFile={setFlImportFile}
          loading={loading}
          flImporting={flImporting}
          onUpload={handleUpload}
          onImportFeatureList={handleImportFeatureList}
          onFileSelect={handleFileSelect}
          message={message}
        />
      )}

      {step === 1 && document && (
        <StepConfirmItems
          document={document}
          selectedItems={selectedItems}
          setSelectedItems={setSelectedItems}
          scopeForm={scopeForm}
          setScopeForm={setScopeForm}
          scopeLoading={scopeLoading}
          scopeSaving={scopeSaving}
          flExporting={flExporting}
          loading={loading}
          onGenerateScope={handleGenerateScope}
          onSaveScope={handleSaveScope}
          onExportFeatureList={handleExportFeatureList}
          onAddItem={openAddItem}
          onEditItem={openEditItem}
          onRemoveItem={removeItem}
          onBack={() => setStep(0)}
          onConfirm={handleConfirm}
        />
      )}

      {step === 2 && (
        <StepStrategy
          document={document}
          strategies={strategies}
          selectedPreset={selectedPreset}
          onApplyPreset={applyPreset}
          specialistOptions={specialistOptions}
          specialistSkills={specialistSkills}
          onToggleSpecialistSkill={toggleSpecialistSkill}
          moduleGroups={moduleGroups}
          estimate={estimate}
          useKnowledge={useKnowledge}
          onToggleKnowledge={setUseKnowledge}
          knowledgeReadyCount={knowledgeReadyCount}
          projectId={projectId}
          loading={loading}
          onBack={() => setStep(1)}
          onOpenGenerateConfirm={openGenerateConfirm}
        />
      )}

      {step === 3 && task && (
        <StepReview
          task={task}
          draftSuiteFilter={draftSuiteFilter}
          setDraftSuiteFilter={setDraftSuiteFilter}
          draftExporting={draftExporting}
          selectedDrafts={selectedDrafts}
          setSelectedDrafts={setSelectedDrafts}
          pendingDraftCount={pendingDraftCount}
          onExportDrafts={handleExportDrafts}
          onEditDraft={openEditDraft}
          onSelectAllDrafts={handleSelectAllDrafts}
          onAdopt={handleAdopt}
          onReject={handleReject}
          onMarkConfirm={handleMarkConfirm}
          onReviewDraft={handleReviewSingle}
          onResume={handleResumeGeneration}
          resumeLoading={loading}
          onFinish={() => goToStep(4)}
          onBack={() => setStep(2)}
          onNewTask={handleNewTask}
        />
      )}

      {step === 4 && task && (
        <StepDone
          task={task}
          projectId={projectId}
          exporting={draftExporting}
          onExport={handleExportDrafts}
          onNewTask={handleNewTask}
        />
      )}

      <GenerateConfirmModal
        open={confirmModalOpen}
        loading={loading}
        strategies={strategies}
        selectedPreset={selectedPreset}
        specialistSkills={specialistSkills}
        specialistOptions={specialistOptions}
        estimate={estimate}
        moduleGroups={moduleGroups}
        onOk={handleGenerate}
        onCancel={() => setConfirmModalOpen(false)}
      />

      <ItemEditModal
        open={itemModalOpen}
        form={itemForm}
        editingItem={editingItem}
        loading={loading}
        onOk={saveItem}
        onCancel={() => setItemModalOpen(false)}
      />

      <DraftEditModal
        open={draftModalOpen}
        form={draftForm}
        loading={loading}
        onOk={saveDraft}
        onCancel={() => setDraftModalOpen(false)}
      />
    </div>
  );
}
