/**
 * 共享的文件上传配置
 * 供多个模块使用（model, data 等）
 */

import { diskStorage } from 'multer';
import * as path from 'path';
import * as fs from 'fs';
import { Express as ExpressMulter } from 'multer';

/**
 * 上传配置选项
 */
export interface UploadConfigOptions {
  destination: string; // 上传目录
  maxFileSize?: number; // 最大文件大小（字节），默认 500MB
  allowedMimeTypes?: string[]; // 允许的 MIME 类型，undefined 表示允许所有
}

/**
 * 创建 multer diskStorage 配置
 */
export function createDiskStorageConfig(options: UploadConfigOptions) {
  const { destination, maxFileSize = 500 * 1024 * 1024 } = options;

  // 确保上传目录存在
  if (!fs.existsSync(destination)) {
    fs.mkdirSync(destination, { recursive: true });
  }

  return diskStorage({
    destination: (req, file, cb) => {
      // 如果需要按 sessionId 创建子目录，可从 req.body 中获取
      const sessionId = req.body?.sessionId || req.query?.sessionId || 'default';
      const sessionDir = path.join(destination, String(sessionId));

      if (!fs.existsSync(sessionDir)) {
        fs.mkdirSync(sessionDir, { recursive: true });
      }

      cb(null, sessionDir);
    },
    filename: (req, file, cb) => {
      // 处理中文文件名编码问题
      const originalName = Buffer.from(file.originalname, 'latin1').toString(
        'utf8'
      );
      const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1e9);
      const ext = path.extname(originalName);
      const nameWithoutExt = path.basename(originalName, ext);

      cb(null, `${nameWithoutExt}-${uniqueSuffix}${ext}`);
    },
  });
}

/**
 * 创建完整的 FileInterceptor 配置
 */
export function createFileInterceptorConfig(options: UploadConfigOptions) {
  return {
    storage: createDiskStorageConfig(options),
    limits: {
      fileSize: options.maxFileSize || 500 * 1024 * 1024,
    },
    fileFilter: (req: any, file: ExpressMulter.File, cb: Function) => {
      if (options.allowedMimeTypes) {
        if (!options.allowedMimeTypes.includes(file.mimetype)) {
          return cb(
            new Error(
              `不支持的文件类型: ${file.mimetype}。允许: ${options.allowedMimeTypes.join(', ')}`
            )
          );
        }
      }
      cb(null, true);
    },
  };
}

/**
 * 创建 AnyFilesInterceptor 配置（多文件）
 */
export function createAnyFilesInterceptorConfig(options: UploadConfigOptions) {
  return {
    storage: createDiskStorageConfig(options),
    limits: {
      fileSize: options.maxFileSize || 500 * 1024 * 1024,
    },
    fileFilter: (req: any, file: ExpressMulter.File, cb: Function) => {
      if (options.allowedMimeTypes) {
        if (!options.allowedMimeTypes.includes(file.mimetype)) {
          return cb(
            new Error(
              `不支持的文件类型: ${file.mimetype}。允许: ${options.allowedMimeTypes.join(', ')}`
            )
          );
        }
      }
      cb(null, true);
    },
  };
}
