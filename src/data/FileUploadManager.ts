import type {
  UploadResponse,
  DeleteFileResponse,
  CleanSessionResponse,
  FileUploadCallbacks,
  FileManagerConfig,
  FileUploadState,
  BatchUploadResult,
} from './types';

export class FileUploadManager {
  private backUrl: string;
  private sessionId: string;
  private maxFileSize: number = 500 * 1024 * 1024; // 500MB
  private allowedMimeTypes?: string[];
  private timeout: number = 60000; // 60s
  private uploadedFiles: Map<string, FileUploadState> = new Map();
  private activeUploads: Map<string, AbortController> = new Map();

  constructor(config: FileManagerConfig | string, sessionId?: string) {
    if (typeof config === 'string') {
      // 简化构造器：new FileUploadManager(backUrl, sessionId)
      this.backUrl = config;
      this.sessionId = sessionId || 'default';
    } else {
      // 完整构造器：new FileUploadManager({ backUrl, sessionId, ... })
      this.backUrl = config.backUrl;
      this.sessionId = config.sessionId;
      this.maxFileSize = config.maxFileSize || this.maxFileSize;
      this.allowedMimeTypes = config.allowedMimeTypes;
      this.timeout = config.timeout || this.timeout;
    }
  }

  /**
   * 上传单个文件
   */
  async upload(
    file: File,
    callbacks?: FileUploadCallbacks
  ): Promise<string> {
    // 验证文件
    this.validateFile(file);

    callbacks?.onStart?.(file);

    // 创建中止控制器
    const abortController = new AbortController();
    const uploadId = `${file.name}-${Date.now()}`;
    this.activeUploads.set(uploadId, abortController);

    try {
      // 创建 FormData
      const formData = new FormData();
      formData.append('file', file);
      formData.append('sessionId', this.sessionId);

      // 创建请求
      const response = await fetch(`${this.backUrl}/data/upload`, {
        method: 'POST',
        body: formData,
        signal: abortController.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const result = (await response.json()) as UploadResponse;

      if (!result.success) {
        throw new Error(result.message || '文件上传失败');
      }

      if (!result.filePath) {
        throw new Error('服务器未返回文件路径');
      }

      // 记录上传状态
      const uploadState: FileUploadState = {
        fileName: file.name,
        filePath: result.filePath,
        status: 'success',
        progress: 100,
        size: file.size,
        mimeType: file.type,
        uploadedAt: new Date(),
      };

      this.uploadedFiles.set(result.filePath, uploadState);

      callbacks?.onSuccess?.(result.filePath, file);
      callbacks?.onProgress?.(100);

      return result.filePath;
    } catch (error) {
      const err = error instanceof Error ? error : new Error(String(error));

      // 更新上传状态
      const uploadState: FileUploadState = {
        fileName: file.name,
        status: 'error',
        progress: 0,
        error: err,
        size: file.size,
        mimeType: file.type,
      };

      this.uploadedFiles.set(file.name, uploadState);

      callbacks?.onError?.(err, file);

      throw err;
    } finally {
      this.activeUploads.delete(uploadId);
      callbacks?.onComplete?.(file);
    }
  }

  /**
   * 批量上传文件
   */
  async uploadMultiple(
    files: File[],
    options?: {
      maxConcurrent?: number;
      callbacks?: FileUploadCallbacks;
    }
  ): Promise<BatchUploadResult> {
    const maxConcurrent = options?.maxConcurrent || 3;
    const callbacks = options?.callbacks;
    const result: BatchUploadResult = {
      successful: [],
      failed: [],
      total: files.length,
    };

    for (let i = 0; i < files.length; i += maxConcurrent) {
      const batch = files.slice(i, i + maxConcurrent);

      const promises = batch.map((file) =>
        this.upload(file, callbacks)
          .then((filePath) => {
            result.successful.push(filePath);
            return { success: true };
          })
          .catch((error) => {
            result.failed.push({
              fileName: file.name,
              error: error.message,
            });
            return { success: false };
          })
      );

      await Promise.all(promises);
    }

    return result;
  }

  /**
   * 删除指定文件
   */
  async deleteFile(filePath: string): Promise<void> {
    try {
      const encodedPath = this.encodeFilePath(filePath);

      const response = await fetch(
        `${this.backUrl}/data/temp/${encodedPath}`,
        { method: 'DELETE' }
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const result = (await response.json()) as DeleteFileResponse;

      if (!result.success) {
        throw new Error(result.message || '文件删除失败');
      }

      // 清除记录
      for (const [key, value] of this.uploadedFiles.entries()) {
        if (value.filePath === filePath) {
          this.uploadedFiles.delete(key);
          break;
        }
      }
    } catch (error) {
      throw error instanceof Error
        ? error
        : new Error(`删除文件失败: ${String(error)}`);
    }
  }

  /**
   * 删除多个文件
   */
  async deleteMultiple(filePaths: string[]): Promise<void> {
    const promises = filePaths.map((path) => this.deleteFile(path));
    await Promise.all(promises);
  }

  /**
   * 清理整个会话的所有文件
   */
  async cleanSession(): Promise<void> {
    try {
      const response = await fetch(
        `${this.backUrl}/data/temp-session/${this.sessionId}`,
        { method: 'DELETE' }
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const result = (await response.json()) as CleanSessionResponse;

      if (!result.success) {
        throw new Error(result.message || '会话清理失败');
      }

      this.uploadedFiles.clear();
    } catch (error) {
      throw error instanceof Error
        ? error
        : new Error(`清理会话失败: ${String(error)}`);
    }
  }

  /**
   * 中止正在进行的上传
   */
  abortUpload(fileNameOrId: string): void {
    const abortController = this.activeUploads.get(fileNameOrId);
    if (abortController) {
      abortController.abort();
      this.activeUploads.delete(fileNameOrId);
    }
  }

  /**
   * 中止所有上传
   */
  abortAll(): void {
    for (const controller of this.activeUploads.values()) {
      controller.abort();
    }
    this.activeUploads.clear();
  }

  /**
   * 获取已上传文件列表
   */
  getUploadedFiles(): FileUploadState[] {
    return Array.from(this.uploadedFiles.values());
  }

  /**
   * 获取特定文件的上传状态
   */
  getFileStatus(filePath: string): FileUploadState | undefined {
    return this.uploadedFiles.get(filePath);
  }

  /**
   * 检查文件是否已上传
   */
  hasFile(filePath: string): boolean {
    return this.uploadedFiles.has(filePath);
  }

  /**
   * 获取上传统计信息
   */
  getStats(): {
    total: number;
    successful: number;
    failed: number;
    totalSize: number;
  } {
    const files = Array.from(this.uploadedFiles.values());
    const successful = files.filter((f) => f.status === 'success').length;
    const failed = files.filter((f) => f.status === 'error').length;
    const totalSize = files.reduce((sum, f) => sum + f.size, 0);

    return {
      total: files.length,
      successful,
      failed,
      totalSize,
    };
  }

  /**
   * 设置新的会话ID
   */
  setSessionId(sessionId: string): void {
    this.sessionId = sessionId;
  }

  /**
   * 验证文件
   */
  private validateFile(file: File): void {
    if (!file) {
      throw new Error('请选择文件');
    }

    if (file.size > this.maxFileSize) {
      const maxSizeMB = Math.round(this.maxFileSize / 1024 / 1024);
      throw new Error(`文件过大，最大支持 ${maxSizeMB}MB`);
    }

    if (
      this.allowedMimeTypes &&
      !this.allowedMimeTypes.includes(file.type)
    ) {
      throw new Error(
        `不支持的文件类型，允许: ${this.allowedMimeTypes.join(', ')}`
      );
    }
  }

  /**
   * 编码文件路径为 Base64
   */
  private encodeFilePath(filePath: string): string {
    return btoa(unescape(encodeURIComponent(filePath)));
  }
}

/**
 * 创建文件上传管理实例
 */
export function createFileUploadManager(
  backUrl: string,
  sessionId: string,
  config?: Partial<FileManagerConfig>
): FileUploadManager {
  return new FileUploadManager(
    {
      backUrl,
      sessionId,
      ...config,
    }
  );
}

/**
 * 简单的文件上传函数
 */
export async function uploadFile(
  file: File,
  backUrl: string,
  sessionId: string
): Promise<string> {
  const manager = new FileUploadManager(backUrl, sessionId);
  return manager.upload(file);
}
