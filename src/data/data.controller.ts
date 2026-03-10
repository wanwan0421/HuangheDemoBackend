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
  Body,
  Query,
} from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import * as path from 'path';
import * as fs from 'fs';
import { Express as ExpressMulter } from 'multer';
import { Req } from '@nestjs/common';
import express from "express";
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
  private buildFileUrls(absolutePath: string, req: any): { fileUrl: string; fileRelativeUrl: string } {
    const uploadRoot = path.resolve(TEMP_UPLOAD_DIR);
    const relativeFilePath = path.relative(uploadRoot, absolutePath).replace(/\\/g, '/');
    const fileRelativeUrl = `/uploads/${relativeFilePath}`;
    const protocol = req?.headers?.['x-forwarded-proto'] || req?.protocol || 'http';
    const host = req?.headers?.host || 'localhost:3000';
    const fileUrl = `${protocol}://${host}${fileRelativeUrl}`;

    return { fileUrl, fileRelativeUrl };
  }
  @Post('upload')
  @HttpCode(HttpStatus.OK)
  @UseInterceptors(
    FileInterceptor('file', createFileInterceptorConfig({
      destination: TEMP_UPLOAD_DIR,
      maxFileSize: 500 * 1024 * 1024,
    })),
  )
  async uploadFile(
    @UploadedFile() file: ExpressMulter.File,
    @Req() req: any,
  ): Promise<{
    success: boolean;
    message: string;
    filePath?: string;
    fileName?: string;
    originalFileName?: string;
    fileUrl?: string;
    fileRelativeUrl?: string;
    fileSize?: number;
    mimeType?: string;
  }> {
    if (!file) {
      throw new BadRequestException('请选择要上传的文件');
    }

    try {
      // 返回绝对路径，确保跨服务访问时路径正确
      const absolutePath = path.resolve(file.path);
      const { fileUrl, fileRelativeUrl } = this.buildFileUrls(absolutePath, req);

      return {
        success: true,
        message: '文件上传成功',
        filePath: absolutePath.replace(/\\/g, '/'), // 统一使用正斜杠
        fileName: file.filename,
        originalFileName: file.originalname,
        fileUrl,
        fileRelativeUrl,
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
  async cleanSessionTempFiles(
    @Param('sessionId') sessionId: string,
    @Req() req?: any,
  ): Promise<{
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

  /**
   * 上传并转换地理数据为 Mapbox 兼容格式
   * @param file 上传的地理数据文件
   * @param saveConverted 是否保存转换后的文件
   * @returns 转换结果（包含 GeoJSON 或栅格信息）
   */
  @Post('uploadAndConvert')
  @HttpCode(HttpStatus.OK)
  @UseInterceptors(
    FileInterceptor(
      'file',
      createFileInterceptorConfig({
        destination: TEMP_UPLOAD_DIR,
        maxFileSize: 500 * 1024 * 1024,
      }),
    ),
  )
  async uploadAndConvert(
    @UploadedFile() file: ExpressMulter.File,
    @Query('saveConverted') saveConverted?: string,
    @Req() req?: any,
  ): Promise<any> {
    if (!file) {
      throw new BadRequestException('请选择要上传的文件');
    }

    try {
      const absolutePath = path.resolve(file.path);
      const { fileUrl, fileRelativeUrl } = this.buildFileUrls(absolutePath, req);

      // 检查是否为支持的地理数据格式
      if (!this.dataService.isSupportedGeoFormat(file.originalname)) {
        // 不支持的格式仍然上传，但不进行转换
        return {
          success: true,
          message: '文件上传成功（不支持的地理数据格式，未进行转换）',
          fileName: file.filename,
          originalFileName: file.originalname,
          fileSize: file.size,
          filePath: absolutePath.replace(/\\/g, '/'),
          fileUrl,
          fileRelativeUrl,
          conversion: null,
          conversionStatus: 'unsupported',
        };
      }

      // 转换数据
      const shouldSave = saveConverted === 'true' || saveConverted === '1';
      const convertResult = await this.dataService.convertToMapboxFormat(
        absolutePath,
        shouldSave,
      );

      return {
        success: true,
        message: '文件上传并转换成功',
        fileName: file.filename,
        originalFileName: file.originalname,
        fileSize: file.size,
        filePath: absolutePath.replace(/\\/g, '/'),
        fileUrl,
        fileRelativeUrl,
        conversion: convertResult,
        conversionStatus: 'success',
      };
    } catch (error) {
      throw new BadRequestException(
        `文件上传或转换失败: ${error.message}`,
      );
    }
  }

  /**
   * 转换已上传的地理数据文件为 Mapbox 兼容格式
   * @param filePath 文件路径
   * @param saveConverted 是否保存转换后的文件
   * @returns 转换结果
   */
  @Post('convert')
  @HttpCode(HttpStatus.OK)
  async convertFile(
    @Body('filePath') filePath: string,
    @Body('saveConverted') saveConverted?: boolean,
  ): Promise<any> {
    if (!filePath) {
      throw new BadRequestException('文件路径不能为空');
    }

    try {
      // 验证文件存在
      if (!fs.existsSync(filePath)) {
        throw new BadRequestException('文件不存在');
      }

      // 检查是否为支持的格式
      if (!this.dataService.isSupportedGeoFormat(filePath)) {
        throw new BadRequestException(
          '不支持的文件格式。支持的格式: .shp, .geojson, .json, .tif, .tiff, .kml',
        );
      }

      // 转换数据
      const convertResult = await this.dataService.convertToMapboxFormat(
        filePath,
        saveConverted || false,
      );

      return {
        success: true,
        message: '数据转换成功',
        filePath: filePath,
        conversion: convertResult,
      };
    } catch (error) {
      throw new BadRequestException(`数据转换失败: ${error.message}`);
    }
  }

  /**
   * 批量转换地理数据文件
   * @param filePaths 文件路径列表
   * @param saveConverted 是否保存转换后的文件
   * @returns 转换结果列表
   */
  @Post('convert-batch')
  @HttpCode(HttpStatus.OK)
  async convertBatch(
    @Body('filePaths') filePaths: string[],
    @Body('saveConverted') saveConverted?: boolean,
  ): Promise<any> {
    if (!filePaths || filePaths.length === 0) {
      throw new BadRequestException('文件路径列表不能为空');
    }

    try {
      const results = await this.dataService.convertMultipleFiles(
        filePaths,
        saveConverted || false,
      );

      return {
        success: true,
        message: '批量转换完成',
        total: filePaths.length,
        results,
      };
    } catch (error) {
      throw new BadRequestException(`批量转换失败: ${error.message}`);
    }
  }
}
