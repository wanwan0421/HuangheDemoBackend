import { Injectable, Logger } from '@nestjs/common';
import { InjectModel } from '@nestjs/mongoose';
import { Model } from 'mongoose';
import * as fs from 'fs';
import * as path from 'path';
import { spawn } from 'child_process';
import { CreateModelRunRequest } from './dto/create-model-run.dto';
import { ModelRunRecord, ModelRunRecordDocument } from './schemas/model-run-record.schema';
import { generateTaskId } from './utils/task-id.util';

@Injectable()
export class ModelRunnerService {
  private readonly logger = new Logger(ModelRunnerService.name);
  private readonly modelDataDir = path.join(process.cwd(), 'model-scripts');
  private readonly jsonScriptsDir = path.join(this.modelDataDir, 'json-scripts');
  private readonly driverScriptsPath = path.join(this.modelDataDir, 'python-scripts', 'ogms_driver.py');

  constructor(
    @InjectModel(ModelRunRecord.name) private modelRunRecordModel: Model<ModelRunRecordDocument>,
  ) {
    this.initializeDirectories();
  }

  /**
   * 初始化必要的目录
   */
  private initializeDirectories() {
    [this.modelDataDir, this.jsonScriptsDir].forEach(dir => {
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
        this.logger.log(`创建目录: ${dir}`);
      }
    });

    if (!fs.existsSync(this.driverScriptsPath)) {
      this.logger.warn(`警告: Python驱动脚本未找到，请确保文件存在于: ${this.driverScriptsPath}`);
    }
  }

  /**
   * 创建并运行模型
   */
  async createAndRunModel(request: CreateModelRunRequest) {
    const taskId = crypto.randomUUID();
    this.logger.log(`创建新模型任务: ${taskId}, 模型: ${request.modelName}`);

    // 验证请求数据，后续扩展更多验证逻辑（数据检查+AI）
    this.validateRequest(request);

    // 准备数据文件，生成JSON数据（替代原来的Python代码）
    const jsonPath = await this.generateInputJson(taskId, request);
    // const scriptPath = await this.generatePythonScript(taskId, request);

    // 创建任务记录
    const runRecord = await this.createRunRecord(taskId, request, jsonPath);

    // 异步运行模型（传递JSON文件路径给驱动脚本）
    this.runModelAsync(taskId, jsonPath, runRecord._id.toString());

    return {
      taskId,
      message: '模型任务已创建，正在后台执行',
    };
  }

  /**
   * 验证用户上传的模型输入数据
   */
  private validateRequest(request: CreateModelRunRequest) {
    if (!request.modelName) {
      throw new Error('模型名称不能为空');
    }

    if (!request.states || Object.keys(request.states).length === 0) {
      throw new Error('状态事件数据不能为空');
    }

    // 验证每个state下的event数据
    for (const [stateName, events] of Object.entries(request.states)) {
      if (!events || typeof events !== 'object') {
        throw new Error(`状态 "${stateName}" 的事件数据格式不正确`);
      }

      for (const [eventName, eventData] of Object.entries(events)) {
        if (typeof eventData !== 'object') {
          throw new Error(`状态 "${stateName}" 的事件 "${eventName}" 数据格式不正确`);
        }

        // 至少需要 url 或 value
        if (!eventData.name && !eventData.url && !eventData.value) {
          throw new Error(`状态 "${stateName}" 的事件 "${eventName}" 必须包含 name、url 或 value`);
        }
      }
    }
  }

  /**
    * 将用户上传的模型以及数据生成JSON文件
    * @param taskId 任务ID
    * @param request 创建模型运行请求
    * @returns JSON文件路径
  */
  private async generateInputJson(taskId: string, request: CreateModelRunRequest): Promise<string> {
    const lists = this.buildRunLists(request.states);

    // 构造传递给Python的完整数据包
    const inputData = {
      modelName: request.modelName,
      lists,
    };

    const jsonPath = path.join(this.jsonScriptsDir, `${taskId}_input.json`);
    await fs.promises.writeFile(jsonPath, JSON.stringify(inputData, null, 2), 'utf-8');
    return jsonPath;
  }

  /**
    * 构建run列表，即lists中的run部分，直接生成对象存JSON格式
    * @param states 状态及其事件数据
    * @returns 构建好的run对象
  */
  private buildRunLists(states: Record<string, Record<string, any>>): Record<string, any> {
    const run: Record<string, any> = {};

    for (const [stateName, events] of Object.entries(states)) {
      run[stateName] = {};

      for (const [eventName, eventData] of Object.entries(events)) {
        // 文件型参数
        if (eventData.url || eventData.filePath) {
          const filePath = eventData.url ?? eventData.filePath;

          run[stateName][eventName] = {
            name: eventData.name ?? path.basename(filePath),
            url: filePath,
          };
        }
        // 数值 / 字符串参数
        else if (eventData.value !== undefined) {
          run[stateName][eventName] = {
            value: String(eventData.value),
          };
        }
      }
    }

    return run;
  }

  /**
    * 创建模型运行任务记录
    * @param taskId 任务ID
    * @param request 创建模型运行请求
    * @param jsonPath JSON文件路径
    * @returns 任务记录文档
  */
  private async createRunRecord(taskId: string, request: CreateModelRunRequest, jsonPath: string): Promise<ModelRunRecordDocument> {
    const record = new this.modelRunRecordModel({
      taskId,
      modelName: request.modelName,
      jsonPath: jsonPath,
      states: request.states,
      status: 'Init',
      createdAt: new Date(),
    });

    return record.save();
  }

  /**
 * 异步运行模型
 * @param taskId 任务ID
 * @param jsonPath JSON文件路径
 * @param recordId 任务记录ID
 */
  private runModelAsync(taskId: string, jsonPath: string, recordId: string) {
    setImmediate(async () => {
      try {
        this.logger.log(`开始执行模型任务: ${taskId}`);

        // 更新状态为运行中
        await this.modelRunRecordModel.updateOne(
          { _id: recordId },
          { status: 'Started', startedAt: new Date() },
        );

        // 调用python驱动脚本，传入JSON文件路径
        const result = await this.executePythonDriver(jsonPath);

        if (result.status === 'error') {
          throw new Error(result.message || '模型执行出错');
        }

        // 更新状态为完成
        await this.modelRunRecordModel.updateOne(
          { _id: recordId },
          {
            status: 'Finished',
            result: result,
            FinishedAt: new Date(),
          },
        );

        this.logger.log(`模型任务完成: ${taskId}`);
      } catch (error) {
        this.logger.error(`模型任务失败: ${taskId}, 错误: ${error.message}`);

        // 更新状态为失败
        await this.modelRunRecordModel.updateOne(
          { _id: recordId },
          {
            status: 'Error',
            error: error.message,
            FinishedAt: new Date(),
          },
        );
      }
    });
  }

  /**
   * 执行Python驱动脚本
   * @param jsonPath 输入JSON文件路径
   * @returns 脚本执行结果
  */
  private executePythonDriver(jsonPath: string): Promise<any> {
    return new Promise((resolve, reject) => {
      // 检查驱动脚本是否存在
      if (!fs.existsSync(this.driverScriptsPath)) {
        return reject(new Error(`驱动脚本不存在: ${this.driverScriptsPath}`));
      }

      // 运行python：ogms_driver.py
      const python = spawn('python', [this.driverScriptsPath, jsonPath], {
        cwd: path.dirname(this.driverScriptsPath),
        env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
      });

      let stdoutData = '';
      let stderrData = '';

      python.stdout.on('data', (data) => {
        stdoutData += data.toString();
      });

      python.stderr.on('data', (data) => {
        stderrData += data.toString();
        this.logger.debug(`[Python Log]: ${data.toString().trim()}`);
      });

      python.on('close', (code) => {
        if (code !== 0) {
          reject(new Error(`Python驱动脚本执行失败，退出码: ${code}, 错误: ${stderrData}`));
        } else {
          try {
            const lines = stdoutData.trim().split('\n');
            const lastLine = lines[lines.length - 1];
            const result = JSON.parse(lastLine);
            resolve(result);
          } catch (error) {
            this.logger.error(`解析Python输出时出错: ${error.message}`);
            resolve({ rawOutput: stdoutData });
          }
        }
      });

      python.on('error', (error) => {
        reject(new Error(`执行Python驱动脚本时出错: ${error.message}`));
      })
    })
  }

  /**
   * 获取任务状态
   */
  async getTaskStatus(taskId: string) {
    const record = await this.modelRunRecordModel.findOne({ taskId });

    if (!record) {
      throw new Error(`任务不存在: ${taskId}`);
    }

    return {
      taskId: record.taskId,
      modelName: record.modelName,
      status: record.status,
      createdAt: record.createdAt,
      startedAt: record.startedAt,
      FinishedAt: record.FinishedAt,
    };
  }

  /**
   * 获取任务结果
   */
  async getTaskResult(taskId: string) {
    const record = await this.modelRunRecordModel.findOne({ taskId });

    if (!record) {
      throw new Error(`任务不存在: ${taskId}`);
    }

    if (record.status === 'Init' || record.status === 'Started') {
      throw new Error(`任务仍在运行中，状态: ${record.status}`);
    }

    if (record.status === 'Error') {
      throw new Error(`任务执行失败: ${record.error}`);
    }

    return {
      taskId: record.taskId,
      modelName: record.modelName,
      status: record.status,
      result: record.result,
      FinishedAt: record.FinishedAt,
    };
  }

  /**
   * 获取所有任务列表
   */
  async getAllTasks(limit = 50) {
    const records = await this.modelRunRecordModel
      .find()
      .sort({ createdAt: -1 })
      .limit(limit)
      .select('taskId modelName status createdAt startedAt FinishedAt');

    return records;
  }
}
