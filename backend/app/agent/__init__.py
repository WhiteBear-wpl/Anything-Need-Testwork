"""测试助手 Agent：基于 LangGraph 的项目查询与用例生成助手。

tools 提供六个只读查询工具和五个用例生成流水线工具，
runner 负责 ReAct 循环、Checkpoint 人机确认与事件流输出，
memory 负责 Token 窗口、滚动摘要和结构化流程记忆。
"""
