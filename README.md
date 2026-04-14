# Huanghe Demo Backend

一个面向地理建模任务的后端项目，采用双服务架构：

- `NestJS`（TypeScript）：提供业务 API、数据管理、文件上传与模型资源接口。
- `FastAPI + LangGraph`（Python，位于 `intelligent-server/`）：提供智能体编排与流式推理能力。

## 核心功能

- 任务需求解析：从用户自然语言中提取地理建模任务规范（领域、目标对象、时空范围、分辨率）。
- 模型推荐：基于任务语义检索候选模型，并获取模型详情进行匹配。
- 数据契约生成：根据推荐模型工作流，生成模型输入槽位的准入契约（语义/空间/时间/格式要求）。
- 数据扫描与对齐：分析数据画像，并执行任务需求、模型契约、数据可用性之间的三角校验。
- 流式交互：通过 SSE 实时返回智能体过程事件（token、tool_call、tool_result、final）。

## 目录概览

- `src/`：NestJS 业务模块（chat、data、model、index、resource 等）。
- `intelligent-server/`：FastAPI 智能体服务（model_recommend、data_scan、alignment）。
- `model-scripts/`、`python-scripts/`：模型脚本与 Python 辅助脚本。
- `uploads/`：上传文件目录。

## 快速启动

### 1) 启动 NestJS 服务

```bash
npm install
npm run start:dev
```

### 2) 启动智能体服务（FastAPI）

```bash
cd intelligent-server
# 建议先激活虚拟环境并安装依赖
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 常用脚本（NestJS）

```bash
npm run build
npm run start:dev
npm run test
npm run test:e2e
```

## 说明

- 项目依赖 MongoDB 存储模型与索引数据。
- 智能体调用外部大模型时受配额与限流影响，建议在 `.env` 中配置可用模型与 API Key。
