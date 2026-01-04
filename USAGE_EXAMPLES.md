# 模型运行器 - 完整使用示例

## 场景 1: 使用网络URL运行模型（推荐）

### 步骤 1: 准备数据

确保所有数据文件都已上传到可访问的服务器，获得以下 URL：

```
http://geomodeling.njnu.edu.cn/dataTransferServer/data/da686d2b-d0d6-4a8e-9667-f391be9a550c  (sz.zip)
http://geomodeling.njnu.edu.cn/dataTransferServer/data/ced8a86f-3c9f-413a-9d3e-1e7e205d97a3  (st_year.xml)
http://geomodeling.njnu.edu.cn/dataTransferServer/data/8003c4cf-1d6a-4e10-b3d2-84eee9238cc2  (first_sim_year.xml)
http://geomodeling.njnu.edu.cn/dataTransferServer/data/4711dc5e-769d-44a8-af30-e4cc973f4caf  (out_len.xml)
http://geomodeling.njnu.edu.cn/dataTransferServer/data/d363580b-1417-402e-b3cf-1ec60a4a5bf6  (land_demands.xml)
```

### 步骤 2: 提交模型任务

```bash
curl -X POST http://localhost:3000/api/model-runner/run \
  -H "Content-Type: application/json" \
  -d '{
    "modelName": "UrbanM2M计算模型（用于测试请勿调用）",
    "stateEvents": {
      "run": {
        "Years_zip": {
          "name": "sz.zip",
          "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/da686d2b-d0d6-4a8e-9667-f391be9a550c"
        },
        "st_year": {
          "name": "st_year.xml",
          "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/ced8a86f-3c9f-413a-9d3e-1e7e205d97a3"
        },
        "first_sim_year": {
          "name": "first_sim_year.xml",
          "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/8003c4cf-1d6a-4e10-b3d2-84eee9238cc2"
        },
        "out_len": {
          "name": "out_len.xml",
          "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/4711dc5e-769d-44a8-af30-e4cc973f4caf"
        },
        "land_demands": {
          "name": "land_demands.xml",
          "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/d363580b-1417-402e-b3cf-1ec60a4a5bf6",
          "value": "1000"
        }
      }
    }
  }'
```

### 步骤 3: 获取响应

```json
{
  "success": true,
  "message": "模型任务已启动",
  "data": {
    "taskId": "1g8h9i0j1k2l3m4n",
    "scriptPath": "/path/to/model-scripts/python-scripts/1g8h9i0j1k2l3m4n_model.py",
    "message": "模型任务已创建，正在后台执行"
  }
}
```

### 步骤 4: 轮询任务状态

```bash
# 使用 taskId 查询状态
curl http://localhost:3000/api/model-runner/status/1g8h9i0j1k2l3m4n
```

响应示例：

```json
{
  "success": true,
  "data": {
    "taskId": "1g8h9i0j1k2l3m4n",
    "modelName": "UrbanM2M计算模型（用于测试请勿调用）",
    "status": "running",
    "createdAt": "2024-01-04T10:30:00.000Z",
    "startedAt": "2024-01-04T10:31:00.000Z"
  }
}
```

### 步骤 5: 获取结果

当状态变为 `completed` 时：

```bash
curl http://localhost:3000/api/model-runner/result/1g8h9i0j1k2l3m4n
```

响应示例：

```json
{
  "success": true,
  "data": {
    "taskId": "1g8h9i0j1k2l3m4n",
    "modelName": "UrbanM2M计算模型（用于测试请勿调用）",
    "status": "completed",
    "result": {
      "output_layer": "/path/to/data/UrbanM2M计算模型（用于测试请勿调用）_a1b2c3d4/output-layer.tif",
      "statistics": "/path/to/data/UrbanM2M计算模型（用于测试请勿调用）_a1b2c3d4/statistics.json"
    },
    "completedAt": "2024-01-04T10:45:00.000Z"
  }
}
```

## 场景 2: 混合使用 URL 和参数值

有些事件可能不需要文件，只需要参数值：

```bash
curl -X POST http://localhost:3000/api/model-runner/run \
  -H "Content-Type: application/json" \
  -d '{
    "modelName": "MyCustomModel",
    "stateEvents": {
      "initialization": {
        "configuration": {
          "name": "config.xml",
          "url": "http://example.com/config.xml"
        },
        "year": {
          "name": "year",
          "value": 2020
        },
        "threshold": {
          "name": "threshold",
          "value": 0.8
        }
      }
    }
  }'
```

## 场景 3: 多个状态的复杂模型

对于包含多个状态的更复杂模型：

```bash
curl -X POST http://localhost:3000/api/model-runner/run \
  -H "Content-Type: application/json" \
  -d '{
    "modelName": "ComplexModel",
    "stateEvents": {
      "preprocessing": {
        "input_data": {
          "name": "raw_data.zip",
          "url": "http://example.com/raw_data.zip"
        },
        "parameters": {
          "name": "params",
          "value": "standard"
        }
      },
      "processing": {
        "algorithm": {
          "name": "algorithm",
          "value": "kmeans"
        },
        "clusters": {
          "name": "clusters",
          "value": 5
        }
      },
      "postprocessing": {
        "output_format": {
          "name": "format",
          "value": "GeoTIFF"
        }
      }
    }
  }'
```

## JavaScript/Node.js 客户端示例

### 使用原生 fetch API

```javascript
// submitModel.js
async function submitAndTrackModel() {
  // 1. 提交模型任务
  const submitResponse = await fetch('http://localhost:3000/api/model-runner/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      modelName: "UrbanM2M计算模型（用于测试请勿调用）",
      stateEvents: {
        run: {
          Years_zip: {
            name: "sz.zip",
            url: "http://geomodeling.njnu.edu.cn/dataTransferServer/data/da686d2b-d0d6-4a8e-9667-f391be9a550c"
          },
          land_demands: {
            name: "land_demands.xml",
            url: "http://geomodeling.njnu.edu.cn/dataTransferServer/data/d363580b-1417-402e-b3cf-1ec60a4a5bf6",
            value: "1000"
          }
        }
      }
    })
  });

  const submitResult = await submitResponse.json();

  if (!submitResult.success) {
    console.error('提交失败:', submitResult.message);
    return;
  }

  const taskId = submitResult.data.taskId;
  console.log('任务已创建，ID:', taskId);

  // 2. 轮询任务状态
  return new Promise((resolve, reject) => {
    const pollInterval = setInterval(async () => {
      try {
        const statusResponse = await fetch(
          `http://localhost:3000/api/model-runner/status/${taskId}`
        );
        const statusResult = await statusResponse.json();

        if (!statusResult.success) {
          clearInterval(pollInterval);
          reject(new Error('获取状态失败'));
          return;
        }

        const { status, completedAt } = statusResult.data;
        console.log(`任务状态: ${status} (更新时间: ${completedAt})`);

        if (status === 'completed' || status === 'failed') {
          clearInterval(pollInterval);

          if (status === 'completed') {
            // 3. 获取结果
            const resultResponse = await fetch(
              `http://localhost:3000/api/model-runner/result/${taskId}`
            );
            const resultData = await resultResponse.json();
            resolve(resultData.data);
          } else {
            reject(new Error('任务执行失败'));
          }
        }
      } catch (error) {
        console.error('轮询错误:', error);
        clearInterval(pollInterval);
        reject(error);
      }
    }, 2000);

    // 超时保护
    setTimeout(() => {
      clearInterval(pollInterval);
      reject(new Error('任务超时'));
    }, 7200000); // 2小时
  });
}

// 使用示例
submitAndTrackModel()
  .then(result => {
    console.log('模型执行完成！');
    console.log('结果:', result);
  })
  .catch(error => {
    console.error('执行出错:', error);
  });
```

### 使用 axios

```javascript
// submitModel.js (使用 axios)
const axios = require('axios');

const apiClient = axios.create({
  baseURL: 'http://localhost:3000',
  headers: { 'Content-Type': 'application/json' }
});

async function submitAndTrackModel(modelData) {
  try {
    // 提交任务
    console.log('提交模型任务...');
    const submitResponse = await apiClient.post('/api/model-runner/run', modelData);
    const { taskId } = submitResponse.data.data;
    console.log('任务ID:', taskId);

    // 轮询状态
    let status = 'pending';
    while (status !== 'completed' && status !== 'failed') {
      await new Promise(resolve => setTimeout(resolve, 2000));
      const statusResponse = await apiClient.get(`/api/model-runner/status/${taskId}`);
      status = statusResponse.data.data.status;
      console.log('当前状态:', status);
    }

    // 获取结果
    if (status === 'completed') {
      const resultResponse = await apiClient.get(`/api/model-runner/result/${taskId}`);
      console.log('执行完成！结果:');
      console.log(resultResponse.data.data.result);
      return resultResponse.data.data;
    } else {
      throw new Error('任务执行失败');
    }
  } catch (error) {
    console.error('错误:', error.message);
    throw error;
  }
}

// 使用
const modelData = {
  modelName: "UrbanM2M计算模型（用于测试请勿调用）",
  stateEvents: {
    run: {
      Years_zip: {
        name: "sz.zip",
        url: "http://geomodeling.njnu.edu.cn/dataTransferServer/data/da686d2b-d0d6-4a8e-9667-f391be9a550c"
      }
    }
  }
};

submitAndTrackModel(modelData).catch(console.error);
```

## Python 客户端示例

```python
# submit_model.py
import requests
import time
import json

class ModelRunnerClient:
    def __init__(self, base_url='http://localhost:3000'):
        self.base_url = base_url
        self.session = requests.Session()

    def submit_model(self, model_data):
        """提交模型任务"""
        url = f"{self.base_url}/api/model-runner/run"
        response = self.session.post(url, json=model_data)
        result = response.json()

        if result['success']:
            return result['data']['taskId']
        else:
            raise Exception(f"提交失败: {result.get('message', '未知错误')}")

    def get_status(self, task_id):
        """获取任务状态"""
        url = f"{self.base_url}/api/model-runner/status/{task_id}"
        response = self.session.get(url)
        result = response.json()

        if result['success']:
            return result['data']
        else:
            raise Exception(f"获取状态失败: {result.get('message', '未知错误')}")

    def get_result(self, task_id):
        """获取任务结果"""
        url = f"{self.base_url}/api/model-runner/result/{task_id}"
        response = self.session.get(url)
        result = response.json()

        if result['success']:
            return result['data']
        else:
            raise Exception(f"获取结果失败: {result.get('message', '未知错误')}")

    def wait_for_completion(self, task_id, timeout=7200):
        """等待任务完成"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                status_info = self.get_status(task_id)
                status = status_info['status']

                print(f"任务 {task_id} 状态: {status}")

                if status in ['completed', 'failed']:
                    if status == 'completed':
                        return self.get_result(task_id)
                    else:
                        raise Exception("任务执行失败")

                time.sleep(2)
            except Exception as e:
                print(f"错误: {e}")
                time.sleep(2)

        raise TimeoutError(f"任务超时 (>{timeout}秒)")


# 使用示例
if __name__ == '__main__':
    client = ModelRunnerClient()

    model_data = {
        "modelName": "UrbanM2M计算模型（用于测试请勿调用）",
        "stateEvents": {
            "run": {
                "Years_zip": {
                    "name": "sz.zip",
                    "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/da686d2b-d0d6-4a8e-9667-f391be9a550c"
                },
                "land_demands": {
                    "name": "land_demands.xml",
                    "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/d363580b-1417-402e-b3cf-1ec60a4a5bf6",
                    "value": "1000"
                }
            }
        }
    }

    try:
        print("提交模型任务...")
        task_id = client.submit_model(model_data)
        print(f"任务已创建: {task_id}")

        print("等待任务完成...")
        result = client.wait_for_completion(task_id)

        print("任务完成！")
        print("结果:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"发生错误: {e}")
```

## 生成的 Python 脚本示例

当你提交上述请求时，系统会自动生成类似以下的 Python 脚本：

```python
# /path/to/model-scripts/python-scripts/1g8h9i0j1k2l3m4n_model.py
import sys
import os
import json

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from ogmsServer import openModel

    lists = {
        "run": {
            "Years_zip": {
                "name": "sz.zip",
                "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/da686d2b-d0d6-4a8e-9667-f391be9a550c"
            },
            "st_year": {
                "name": "st_year.xml",
                "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/ced8a86f-3c9f-413a-9d3e-1e7e205d97a3"
            },
            "first_sim_year": {
                "name": "first_sim_year.xml",
                "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/8003c4cf-1d6a-4e10-b3d2-84eee9238cc2"
            },
            "out_len": {
                "name": "out_len.xml",
                "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/4711dc5e-769d-44a8-af30-e4cc973f4caf"
            },
            "land_demands": {
                "name": "land_demands.xml",
                "url": "http://geomodeling.njnu.edu.cn/dataTransferServer/data/d363580b-1417-402e-b3cf-1ec60a4a5bf6",
                "value": "1000"
            }
        }
    }

    taskServer = openModel.OGMSTaskAccess(modelName="UrbanM2M计算模型（用于测试请勿调用）")
    result = taskServer.createTaskWithURL(params_with_url=lists)
    downloadResult = taskServer.downloadAllData()
    print("模型运行完成")
    print(json.dumps(downloadResult))

except ImportError as e:
    print(f"导入模块时出错：{e}")
    print("请确保 'ogmsServer' 文件夹位于正确的路径。")
except Exception as e:
    print(f"在运行模型时发生了一个错误：{e}")
    sys.exit(1)
```

## 故障排除

### 问题 1: 任务始终在 "running" 状态

**解决方案**：
1. 检查 Python 进程是否正确启动
2. 检查 ogmsServer 模块是否正确导入
3. 查看 NestJS 日志获取更多信息

### 问题 2: 获取结果时出现 404 错误

**解决方案**：
1. 确保使用了正确的 taskId
2. 等待任务状态变为 'completed'
3. 检查 MongoDB 是否正常运行

### 问题 3: Python 脚本执行失败

**解决方案**：
1. 验证所有 URL 是否可访问
2. 检查 config.ini 配置是否正确
3. 运行手动测试：`python model_script.py`

## 最佳实践

1. **始终验证模型名称**：确保模型名称在 OGMS 系统中存在
2. **使用完整的 URL**：避免使用相对 URL
3. **添加错误重试机制**：网络可能不稳定，加入重试逻辑
4. **监控磁盘空间**：大文件可能占用大量磁盘空间
5. **定期清理数据**：删除不需要的任务记录和输出文件
