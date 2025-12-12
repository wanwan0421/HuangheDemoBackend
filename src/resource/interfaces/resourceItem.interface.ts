// 定义返回给前端的资源类型
export interface ResourceItem {
  name: string;
  description: string;
  type: string;
  author: string;
  keywords: string[];
  createdTime: string;
}