/**
 * 文件上传相关的类型定义
 */

/**
 * 文件上传响应
 */
export interface UploadResponse {
  success: boolean;
  message: string;
  filePath?: string;
  fileName?: string;
  fileSize?: number;
  mimeType?: string;
}

/**
 * 删除文件响应
 */
export interface DeleteFileResponse {
  success: boolean;
  message: string;
}

/**
 * 清理会话响应
 */
export interface CleanSessionResponse {
  success: boolean;
  message: string;
}

/**
 * 文件信息
 */
export interface FileInfo {
  exists: boolean;
  size?: number;
  createdAt?: Date;
  updatedAt?: Date;
}

/**
 * 文件上传配置
 */
export interface UploadConfig {
  backUrl: string;
  sessionId: string;
  maxFileSize?: number; // 字节，默认 500MB
  allowedMimeTypes?: string[]; // 允许的 MIME 类型，不限制时为 undefined
  timeout?: number; // 超时时间（毫秒），默认 60000
}

/**
 * 文件上传事件回调
 */
export interface FileUploadCallbacks {
  onStart?: (file: File) => void;
  onProgress?: (percent: number) => void;
  onSuccess?: (filePath: string, file: File) => void;
  onError?: (error: Error, file: File) => void;
  onComplete?: (file: File) => void;
}

/**
 * 批量上传结果
 */
export interface BatchUploadResult {
  successful: string[]; // 成功上传的文件路径
  failed: {
    fileName: string;
    error: string;
  }[];
  total: number;
}

/**
 * 文件管理器配置
 */
export interface FileManagerConfig extends UploadConfig {
  enableAutoCleanup?: boolean; // 自动清理过期文件
  cleanupInterval?: number; // 清理间隔（毫秒），默认 3600000（1小时）
  fileExpiretime?: number; // 文件过期时间（毫秒），默认 86400000（24小时）
}

/**
 * 文件上传状态
 */
export interface FileUploadState {
  fileName: string;
  filePath?: string;
  status: 'uploading' | 'success' | 'error' | 'idle';
  progress: number; // 0-100
  error?: Error;
  size: number;
  mimeType: string;
  uploadedAt?: Date;
}
