/**
 * 生成唯一的任务ID
 * 使用时间戳和随机数来确保唯一性
 */
export function generateTaskId(): string {
  const timestamp = Date.now().toString(36);
  const randomPart = Math.random().toString(36).substring(2, 15);
  return `${timestamp}-${randomPart}`;
}

/**
 * 验证任务ID格式
 */
export function isValidTaskId(taskId: string): boolean {
  return /^[a-z0-9]+-[a-z0-9]+$/.test(taskId);
}
