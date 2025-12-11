// 定义后端API期望的filter参数类型
export interface ResourceFilter {
  categoryId: string; // 资源分类ID
  keyword: string; // 搜索关键字
}