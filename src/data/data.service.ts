import { Injectable } from '@nestjs/common';
import * as fs from 'fs';
import * as path from 'path';

const TEMP_UPLOAD_DIR = './model-scripts/uploads';

@Injectable()
export class DataService {
  /**
   * 清理指定会话的所有临时文件
   * @param sessionId 会话ID
   */
  async cleanSessionTempFiles(sessionId: string): Promise<void> {
    const sessionDir = path.join(TEMP_UPLOAD_DIR, sessionId);

    if (fs.existsSync(sessionDir)) {
      const files = fs.readdirSync(sessionDir);
      
      for (const file of files) {
        const filePath = path.join(sessionDir, file);
        const stat = fs.statSync(filePath);
        
        if (stat.isFile()) {
          fs.unlinkSync(filePath);
        }
      }

      // 删除空目录
      try {
        fs.rmdirSync(sessionDir);
      } catch (error) {
        // 目录不为空或其他错误，忽略
      }
    }
  }

  /**
   * 清理所有过期的临时文件（超过指定时间）
   * @param maxAgeMs 最大文件年龄（毫秒），默认24小时
   */
  async cleanExpiredTempFiles(maxAgeMs: number = 24 * 60 * 60 * 1000): Promise<number> {
    let deletedCount = 0;
    const now = Date.now();

    if (!fs.existsSync(TEMP_UPLOAD_DIR)) {
      return deletedCount;
    }

    const sessionDirs = fs.readdirSync(TEMP_UPLOAD_DIR);

    for (const sessionDir of sessionDirs) {
      const sessionPath = path.join(TEMP_UPLOAD_DIR, sessionDir);
      const stat = fs.statSync(sessionPath);

      if (stat.isDirectory()) {
        const files = fs.readdirSync(sessionPath);

        for (const file of files) {
          const filePath = path.join(sessionPath, file);
          const fileStat = fs.statSync(filePath);

          if (fileStat.isFile()) {
            const fileAge = now - fileStat.mtimeMs;
            
            if (fileAge > maxAgeMs) {
              fs.unlinkSync(filePath);
              deletedCount++;
            }
          }
        }

        // 删除空目录
        try {
          fs.rmdirSync(sessionPath);
        } catch (error) {
          // 目录不为空，忽略
        }
      }
    }

    return deletedCount;
  }

  /**
   * 验证文件是否存在且可访问
   * @param filePath 相对文件路径
   */
  validateFilePath(filePath: string): boolean {
    const fullPath = path.join(process.cwd(), filePath);
    return fs.existsSync(fullPath);
  }

  /**
   * 获取文件信息
   * @param filePath 相对文件路径
   */
  getFileInfo(filePath: string): {
    exists: boolean;
    size?: number;
    createdAt?: Date;
    updatedAt?: Date;
  } {
    const fullPath = path.join(process.cwd(), filePath);
    
    if (!fs.existsSync(fullPath)) {
      return { exists: false };
    }

    const stat = fs.statSync(fullPath);
    return {
      exists: true,
      size: stat.size,
      createdAt: stat.birthtime,
      updatedAt: stat.mtime,
    };
  }
}
