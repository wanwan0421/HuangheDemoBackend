import { Injectable, Logger } from '@nestjs/common';
import * as fs from 'fs';
import * as path from 'path';
import { spawn } from 'child_process';

const TEMP_UPLOAD_DIR = './model-scripts/uploads';
const CONVERTED_OUTPUT_DIR = './model-scripts/uploads/converted';

@Injectable()
export class DataService {
  private readonly logger = new Logger(DataService.name);
  
  // 使用 process.cwd() 获取项目根目录（更可靠）
  private readonly projectRoot = process.cwd();
  
  private readonly pythonConverterScript = path.join(
    this.projectRoot,
    'src',
    'data-mapping',
    'python',
    'geo_converter.py'
  );
  
  // Python 虚拟环境路径（支持 .venv 和 venv）
  private readonly pythonExe = this.findPythonExecutable();

  /**
   * 查找 Python 可执行文件
   * 支持 .venv 和 venv 两种虚拟环境目录名
   */
  private findPythonExecutable(): string {
    const possiblePaths = [
      path.join(this.projectRoot, '.venv', 'Scripts', 'python.exe'),
      path.join(this.projectRoot, '.venv', 'bin', 'python'),
      path.join(this.projectRoot, 'venv', 'Scripts', 'python.exe'),
      path.join(this.projectRoot, 'venv', 'bin', 'python'),
    ];

    for (const pythonPath of possiblePaths) {
      if (fs.existsSync(pythonPath)) {
        return pythonPath;
      }
    }

    // 如果虚拟环境不存在，尝试使用系统 Python
    return process.platform === 'win32' ? 'python.exe' : 'python';
  }

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

  /**
   * 将地理数据文件转换为 Mapbox 兼容格式
   * @param filePath 输入文件路径（绝对路径）
   * @param saveConverted 是否保存转换后的文件
   * @returns 转换结果
   */
  async convertToMapboxFormat(
    filePath: string,
    saveConverted: boolean = false,
  ): Promise<any> {
    return new Promise((resolve, reject) => {
      // 准备输出目录
      let outputDir: string | undefined = undefined;
      if (saveConverted) {
        outputDir = CONVERTED_OUTPUT_DIR;
        if (!fs.existsSync(outputDir)) {
          fs.mkdirSync(outputDir, { recursive: true });
        }
      }

      const args = ['convert', filePath];
      if (outputDir) {
        args.push(outputDir);
      }

      const python = spawn(this.pythonExe, [
        this.pythonConverterScript,
        ...args,
      ], {
        shell: process.platform === 'win32', // Windows 上需要 shell
        cwd: this.projectRoot,
        env: {
          ...process.env,
          PYTHONIOENCODING: 'utf-8',
          PYTHONUTF8: '1',
        },
        timeout: 5 * 60 * 1000, // 5 分钟超时
      });

      let stdoutData = '';
      let stderrData = '';
      let hasErrored = false;

      // 超时处理（防止无限期等待）
      const timeout = setTimeout(() => {
        if (!hasErrored) {
          hasErrored = true;
          python.kill('SIGTERM');
          reject(new Error(`Python 脚本执行超时，请检查文件大小或服务器资源`));
        }
      }, 5 * 60 * 1000);

      python.stdout.on('data', (data) => {
        stdoutData += data.toString();
      });

      python.stderr.on('data', (data) => {
        stderrData += data.toString();
      });

      python.on('close', (code) => {
        clearTimeout(timeout);
        
        if (hasErrored) {
          return; // 已经因为超时错误了
        }

        if (code !== 0) {
          reject(
            new Error(
              `地理数据转换失败: ${stderrData || '未知错误'}`,
            ),
          );
        } else {
          try {
            const lines = stdoutData.trim().split('\n');
            const lastLine = lines[lines.length - 1];
            
            const result = JSON.parse(lastLine);

            if (!result.success) {
              reject(new Error(result.error || '转换失败'));
            } else {
              resolve(result);
            }
          } catch (error) {
            reject(new Error(`解析转换结果失败: ${error}`));
          }
        }
      });

      python.on('error', (error) => {
        clearTimeout(timeout);
        
        if (!hasErrored) {
          hasErrored = true;
          reject(
            new Error(
              `执行转换脚本时出错: ${error.message}。` +
              `请确保已安装 Python 依赖: pip install -r requirements_geo.txt`,
            ),
          );
        }
      });
    });
  }

  /**
   * 批量转换地理数据文件
   * @param filePaths 文件路径列表
   * @param saveConverted 是否保存转换后的文件
   * @returns 转换结果列表
   */
  async convertMultipleFiles(
    filePaths: string[],
    saveConverted: boolean = false,
  ): Promise<any[]> {
    const results: any[] = [];

    for (const filePath of filePaths) {
      try {
        const result = await this.convertToMapboxFormat(filePath, saveConverted);
        results.push({
          filePath,
          ...result,
        });
      } catch (error) {
        results.push({
          filePath,
          success: false,
          error: error,
        });
      }
    }

    return results;
  }

  /**
   * 检测文件是否为支持的地理数据格式
   * @param filePath 文件路径
   * @returns 是否支持
   */
  isSupportedGeoFormat(filePath: string): boolean {
    const ext = path.extname(filePath).toLowerCase();
    const supportedFormats = [
      '.shp',
      '.geojson',
      '.json',
      '.tif',
      '.tiff',
      '.geotiff',
      '.kml',
      '.gml',
    ];
    return supportedFormats.includes(ext);
  }
}
