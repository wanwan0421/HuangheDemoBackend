# 前端集成指南

## 概述

本指南说明如何在前端集成模型运行功能，通过调用后端 API 提交模型数据并跟踪执行进度。

## 前端流程

### 1. 用户输入模型信息

```typescript
// React/Vue 组件中的表单数据
interface ModelFormData {
  modelName: string;
  stateEvents: {
    [stateName: string]: {
      [eventName: string]: {
        name: string;
        url?: string;
        filePath?: string;
        value?: any;
      }
    }
  }
}

// 示例数据
const formData: ModelFormData = {
  modelName: "UrbanM2M计算模型（用于测试请勿调用）",
  stateEvents: {
    run: {
      Years_zip: {
        name: "sz.zip",
        url: "http://geomodeling.njnu.edu.cn/dataTransferServer/data/da686d2b-d0d6-4a8e-9667-f391be9a550c"
      },
      st_year: {
        name: "st_year.xml",
        url: "http://geomodeling.njnu.edu.cn/dataTransferServer/data/ced8a86f-3c9f-413a-9d3e-1e7e205d97a3"
      },
      land_demands: {
        name: "land_demands.xml",
        url: "http://geomodeling.njnu.edu.cn/dataTransferServer/data/d363580b-1417-402e-b3cf-1ec60a4a5bf6",
        value: "1000"
      }
    }
  }
}
```

### 2. 提交模型任务

```typescript
async function submitModel(formData: ModelFormData): Promise<string> {
  const response = await fetch('http://localhost:3000/api/model-runner/run', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(formData)
  });

  const result = await response.json();
  
  if (result.success) {
    // 返回 taskId，用于后续状态查询
    return result.data.taskId;
  } else {
    throw new Error(result.message || '提交失败');
  }
}
```

### 3. 轮询查询任务状态

```typescript
async function pollTaskStatus(
  taskId: string,
  onStatusChange?: (status: any) => void
): Promise<any> {
  const maxRetries = 7200; // 2小时超时
  let retries = 0;
  const pollInterval = 2000; // 2秒轮询一次

  while (retries < maxRetries) {
    try {
      const response = await fetch(
        `http://localhost:3000/api/model-runner/status/${taskId}`
      );
      const result = await response.json();

      if (result.success) {
        const { status } = result.data;
        onStatusChange?.(result.data);

        if (status === 'completed' || status === 'failed') {
          return result.data;
        }
      }

      await new Promise(resolve => setTimeout(resolve, pollInterval));
      retries++;
    } catch (error) {
      console.error('查询状态失败:', error);
      await new Promise(resolve => setTimeout(resolve, pollInterval));
      retries++;
    }
  }

  throw new Error('任务超时');
}
```

### 4. 获取任务结果

```typescript
async function getTaskResult(taskId: string): Promise<any> {
  const response = await fetch(
    `http://localhost:3000/api/model-runner/result/${taskId}`
  );

  const result = await response.json();

  if (result.success) {
    return result.data;
  } else {
    throw new Error(result.message || '获取结果失败');
  }
}
```

## React 组件示例

```typescript
import React, { useState } from 'react';
import './ModelRunner.css';

interface TaskStatus {
  taskId: string;
  modelName: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
}

interface TaskResult {
  taskId: string;
  modelName: string;
  status: string;
  result: Record<string, string>;
  completedAt: string;
}

const ModelRunner: React.FC = () => {
  const [modelName, setModelName] = useState<string>('');
  const [eventData, setEventData] = useState<Record<string, any>>({
    run: {}
  });
  const [currentTask, setCurrentTask] = useState<TaskStatus | null>(null);
  const [taskResult, setTaskResult] = useState<TaskResult | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const handleAddEvent = () => {
    setEventData({
      ...eventData,
      run: {
        ...eventData.run,
        [`event_${Date.now()}`]: {
          name: '',
          url: '',
          value: ''
        }
      }
    });
  };

  const handleEventChange = (eventKey: string, field: string, value: string) => {
    setEventData({
      ...eventData,
      run: {
        ...eventData.run,
        [eventKey]: {
          ...eventData.run[eventKey],
          [field]: value
        }
      }
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      // 构建请求数据
      const cleanedEventData: Record<string, any> = { run: {} };
      Object.entries(eventData.run).forEach(([key, val]: [string, any]) => {
        if (val.name) {
          const eventObj: any = { name: val.name };
          if (val.url) eventObj.url = val.url;
          if (val.value) eventObj.value = val.value;
          cleanedEventData.run[key] = eventObj;
        }
      });

      const response = await fetch('http://localhost:3000/api/model-runner/run', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          modelName,
          stateEvents: cleanedEventData
        })
      });

      const result = await response.json();

      if (result.success) {
        setCurrentTask({
          taskId: result.data.taskId,
          modelName,
          status: 'pending',
          createdAt: new Date().toISOString()
        });

        // 开始轮询状态
        pollStatus(result.data.taskId);
      } else {
        setError(result.message || '提交失败');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '网络错误');
    } finally {
      setLoading(false);
    }
  };

  const pollStatus = async (taskId: string) => {
    const pollInterval = setInterval(async () => {
      try {
        const response = await fetch(
          `http://localhost:3000/api/model-runner/status/${taskId}`
        );
        const result = await response.json();

        if (result.success) {
          setCurrentTask(result.data);

          if (result.data.status === 'completed' || result.data.status === 'failed') {
            clearInterval(pollInterval);

            // 获取结果
            if (result.data.status === 'completed') {
              const resultResponse = await fetch(
                `http://localhost:3000/api/model-runner/result/${taskId}`
              );
              const resultData = await resultResponse.json();
              if (resultData.success) {
                setTaskResult(resultData.data);
              }
            }
          }
        }
      } catch (err) {
        console.error('轮询状态失败:', err);
      }
    }, 2000);
  };

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      pending: '#ffa500',
      running: '#0066cc',
      completed: '#00cc00',
      failed: '#ff0000'
    };
    return colors[status] || '#666';
  };

  const getStatusText = (status: string) => {
    const texts: Record<string, string> = {
      pending: '待执行',
      running: '运行中',
      completed: '已完成',
      failed: '已失败'
    };
    return texts[status] || status;
  };

  return (
    <div className="model-runner-container">
      <h1>模型运行器</h1>

      {!currentTask ? (
        <form onSubmit={handleSubmit} className="form">
          <div className="form-group">
            <label>模型名称</label>
            <input
              type="text"
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              placeholder="输入模型名称"
              required
            />
          </div>

          <div className="form-group">
            <label>事件数据</label>
            {Object.entries(eventData.run).map(([key, val]: [string, any]) => (
              <div key={key} className="event-item">
                <input
                  type="text"
                  placeholder="事件名称"
                  value={val.name}
                  onChange={(e) => handleEventChange(key, 'name', e.target.value)}
                />
                <input
                  type="text"
                  placeholder="URL (可选)"
                  value={val.url}
                  onChange={(e) => handleEventChange(key, 'url', e.target.value)}
                />
                <input
                  type="text"
                  placeholder="值 (可选)"
                  value={val.value}
                  onChange={(e) => handleEventChange(key, 'value', e.target.value)}
                />
              </div>
            ))}
            <button type="button" onClick={handleAddEvent} className="btn-secondary">
              添加事件
            </button>
          </div>

          {error && <div className="error-message">{error}</div>}

          <button type="submit" disabled={loading} className="btn-primary">
            {loading ? '提交中...' : '提交任务'}
          </button>
        </form>
      ) : (
        <div className="task-info">
          <h2>任务进度</h2>
          <div className="status-box">
            <p><strong>任务ID:</strong> {currentTask.taskId}</p>
            <p><strong>模型名称:</strong> {currentTask.modelName}</p>
            <p>
              <strong>状态:</strong>
              <span style={{ color: getStatusColor(currentTask.status) }}>
                {getStatusText(currentTask.status)}
              </span>
            </p>
            <p><strong>创建时间:</strong> {new Date(currentTask.createdAt).toLocaleString()}</p>
            {currentTask.startedAt && (
              <p><strong>开始时间:</strong> {new Date(currentTask.startedAt).toLocaleString()}</p>
            )}
            {currentTask.completedAt && (
              <p><strong>完成时间:</strong> {new Date(currentTask.completedAt).toLocaleString()}</p>
            )}
          </div>

          {taskResult && (
            <div className="result-box">
              <h3>执行结果</h3>
              <table className="result-table">
                <thead>
                  <tr>
                    <th>输出名称</th>
                    <th>文件路径</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(taskResult.result).map(([key, value]) => (
                    <tr key={key}>
                      <td>{key}</td>
                      <td>{value as string}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {currentTask.status === 'running' && (
            <div className="loading-spinner">执行中...</div>
          )}
        </div>
      )}
    </div>
  );
};

export default ModelRunner;
```

## CSS 样式示例

```css
.model-runner-container {
  max-width: 800px;
  margin: 0 auto;
  padding: 20px;
  font-family: Arial, sans-serif;
}

.form {
  background: #f5f5f5;
  padding: 20px;
  border-radius: 8px;
  margin-bottom: 20px;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: bold;
  color: #333;
}

.form-group input {
  display: block;
  width: 100%;
  padding: 10px;
  margin-bottom: 8px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}

.event-item {
  background: white;
  padding: 10px;
  margin-bottom: 10px;
  border-radius: 4px;
  border-left: 3px solid #0066cc;
}

.event-item input {
  margin-bottom: 8px;
}

.btn-primary, .btn-secondary {
  padding: 10px 20px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}

.btn-primary {
  background: #0066cc;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #0052a3;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-secondary {
  background: #666;
  color: white;
}

.btn-secondary:hover {
  background: #555;
}

.error-message {
  color: #ff0000;
  padding: 10px;
  background: #ffe6e6;
  border-radius: 4px;
  margin-bottom: 10px;
}

.task-info {
  background: white;
  padding: 20px;
  border-radius: 8px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.status-box {
  background: #f9f9f9;
  padding: 15px;
  border-radius: 4px;
  border-left: 4px solid #0066cc;
  margin-bottom: 20px;
}

.result-box {
  background: #f9f9f9;
  padding: 15px;
  border-radius: 4px;
  margin-bottom: 20px;
}

.result-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 10px;
}

.result-table th, .result-table td {
  padding: 10px;
  text-align: left;
  border-bottom: 1px solid #ddd;
}

.result-table th {
  background: #f0f0f0;
  font-weight: bold;
}

.loading-spinner {
  text-align: center;
  padding: 20px;
  color: #0066cc;
  font-weight: bold;
}
```

## 使用建议

1. **错误处理**：添加完整的错误处理和用户提示
2. **数据验证**：在提交前验证所有必需字段
3. **超时处理**：实现请求超时和自动重试逻辑
4. **用户体验**：提供清晰的进度反馈和结果展示
5. **缓存管理**：缓存任务列表避免频繁查询
