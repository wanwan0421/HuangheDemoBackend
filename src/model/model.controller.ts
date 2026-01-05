import { Controller, Post, Body, Get, Param, HttpException, HttpStatus, UseInterceptors, UploadedFiles } from '@nestjs/common';
import { ModelRunnerService } from './model.service';
import { CreateModelRunRequest } from './dto/create-model-run.dto';
import { AnyFilesInterceptor } from '@nestjs/platform-express';
import { diskStorage } from 'multer';
import * as path from 'path';
import * as fs from 'fs';
import { Express as ExpressMulter } from 'multer';

// 确保上传目录存在
const UPLOAD_DIR = './model-scripts/uploads';
if (!fs.existsSync(UPLOAD_DIR)) {
  fs.mkdirSync(UPLOAD_DIR, { recursive: true });
}

@Controller('api/model')
export class ModelRunnerController {
  constructor(private readonly modelRunnerService: ModelRunnerService) {}

  /**
   * 创建并运行模型任务
   * @param createModelRunRequest 包含模型名称、状态和事件数据
   */
  @Post('run')
  // 使用拦截器处理多文件上传
  @UseInterceptors(AnyFilesInterceptor({
    storage: diskStorage({
      destination: UPLOAD_DIR,
      filename: (req, file, cb) => {
        file.originalname = Buffer.from(file.originalname, 'latin1').toString('utf8');
        const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
        cb(null, uniqueSuffix + '-' + file.originalname);
      },
    })
  }))
  async runModel(
    @Body() body: any,
    @UploadedFiles() files: Array<ExpressMulter.File>) {
    try {
      // 获取基础配置
      const info = JSON.parse(body.info);

      // 构造CreateModelRunRequest结构
      const formattedRequest: any = {
        modelName: info.modelName,
        states: {}
      };

      // 处理非文件字段（来自body）
      Object.keys(body).forEach(key => {
        if (key === 'info') return;
        if (key.includes('@@@')) {
          const [stateName, eventName, inputName, inputType] = key.split('@@@');
          this.ensureStructure(formattedRequest.states, stateName);
          formattedRequest.states[stateName][eventName] = {
            name: inputName,
            type: inputType,
            value: body[key],
          };
        }
      });

      // 处理文件字段（来自files）
      if (files) {
        files.forEach(file => {
          const [stateName, eventName, inputName, inputType] = file.fieldname.split('@@@');
          this.ensureStructure(formattedRequest.states, stateName);
          // 将本地存储路径存入，供后续Python驱动读取
          formattedRequest.states[stateName][eventName] = {
            name: file.originalname,
            filePath: path.resolve(file.path),
            type: 'file'
          };
        });
      }

      // console.log("formattedRequest:", JSON.stringify(formattedRequest, null, 2));

      const result = await this.modelRunnerService.createAndRunModel(formattedRequest);
      return { success: true, data: result };
    } catch (error) {
      throw new HttpException(error.message, HttpStatus.BAD_REQUEST);
    }
  }

  // 工具方法：确保对象层级存在
  private ensureStructure(states: any, sName: string) {
    if (!states[sName]) states[sName] = {};
  }

  /**
   * 获取模型任务状态
   */
  @Get('status/:taskId')
  async getTaskStatus(@Param('taskId') taskId: string) {
    try {
      const status = await this.modelRunnerService.getTaskStatus(taskId);
      return {
        success: true,
        data: status,
      };
    } catch (error) {
      throw new HttpException(
        error.message || '获取任务状态失败',
        HttpStatus.BAD_REQUEST,
      );
    }
  }

  /**
   * 获取模型结果
   */
  @Get('result/:taskId')
  async getTaskResult(@Param('taskId') taskId: string) {
    try {
      const result = await this.modelRunnerService.getTaskResult(taskId);
      return {
        success: true,
        data: result,
      };
    } catch (error) {
      throw new HttpException(
        error.message || '获取任务结果失败',
        HttpStatus.BAD_REQUEST,
      );
    }
  }

  /**
   * 获取所有任务列表
   */
  @Get('tasks')
  async getAllTasks() {
    try {
      const tasks = await this.modelRunnerService.getAllTasks();
      return {
        success: true,
        data: tasks,
      };
    } catch (error) {
      throw new HttpException(
        error.message || '获取任务列表失败',
        HttpStatus.BAD_REQUEST,
      );
    }
  }
}
