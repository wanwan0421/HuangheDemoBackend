import {
  Controller,
  Post,
  UploadedFile,
  UseInterceptors,
  BadRequestException,
  HttpCode,
  HttpStatus,
  Delete,
  Param,
} from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import * as path from 'path';
import * as fs from 'fs';
import { Express as ExpressMulter } from 'multer';
import { DataService } from './data.service';
import { createFileInterceptorConfig } from '../common/upload-config';

// 临时文件上传目录
const TEMP_UPLOAD_DIR = './model-scripts/uploads';

@Controller('api/data')
export class DataController {
  constructor(private readonly dataService: DataService) {}

  /**
   * 上传数据文件，获取临时路径
   * @param file 上传的文件
   * @param sessionId 会话ID（可选，用于关联数据）
   * @returns 返回上传结果和临时文件路径
   */
  @Post('upload')
  @HttpCode(HttpStatus.OK)
  @UseInterceptors(
    FileInterceptor('file', createFileInterceptorConfig({
      destination: TEMP_UPLOAD_DIR,
      maxFileSize: 500 * 1024 * 1024,
    })),
  )
  async uploadFile(@UploadedFile() file: ExpressMulter.File): Promise<{
    success: boolean;
    message: string;
    filePath?: string;
    fileName?: string;
    fileSize?: number;
    mimeType?: string;
  }> {
    if (!file) {
      throw new BadRequestException('请选择要上传的文件');
    }

    try {
      // 返回绝对路径，确保跨服务访问时路径正确
      const absolutePath = path.resolve(file.path);

      return {
        success: true,
        message: '文件上传成功',
        filePath: absolutePath.replace(/\\/g, '/'), // 统一使用正斜杠
        fileName: file.originalname,
        fileSize: file.size,
        mimeType: file.mimetype,
      };
    } catch (error) {
      throw new BadRequestException(`文件上传失败: ${error.message}`);
    }
  }

  /**
   * 删除临时文件
   * @param filePath 相对文件路径（base64编码）
   */
  @Delete('temp/:filePath')
  @HttpCode(HttpStatus.OK)
  async deleteTempFile(@Param('filePath') encodedFilePath: string): Promise<{
    success: boolean;
    message: string;
  }> {
    try {
      // 解码路径
      const filePath = Buffer.from(encodedFilePath, 'base64').toString('utf-8');
      const fullPath = path.join(process.cwd(), filePath);

      // 安全检查：确保路径在 TEMP_UPLOAD_DIR 内
      const resolvedPath = path.resolve(fullPath);
      const resolvedTempDir = path.resolve(TEMP_UPLOAD_DIR);
      
      if (!resolvedPath.startsWith(resolvedTempDir)) {
        throw new BadRequestException('非法文件路径');
      }

      if (fs.existsSync(fullPath)) {
        fs.unlinkSync(fullPath);
        return {
          success: true,
          message: '文件删除成功',
        };
      } else {
        return {
          success: false,
          message: '文件不存在',
        };
      }
    } catch (error) {
      throw new BadRequestException(`文件删除失败: ${error.message}`);
    }
  }

  /**
   * 清理指定会话的所有临时文件
   * @param sessionId 会话ID
   */
  @Delete('temp-session/:sessionId')
  @HttpCode(HttpStatus.OK)
  async cleanSessionTempFiles(@Param('sessionId') sessionId: string): Promise<{
    success: boolean;
    message: string;
  }> {
    try {
      await this.dataService.cleanSessionTempFiles(sessionId);
      return {
        success: true,
        message: '会话临时文件清理成功',
      };
    } catch (error) {
      throw new BadRequestException(`清理失败: ${error.message}`);
    }
  }
}
