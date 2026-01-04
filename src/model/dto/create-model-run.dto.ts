import { IsString, IsObject, IsNotEmpty, ValidateNested } from 'class-validator';
import { Type } from 'class-transformer';

/**
 * 事件数据项
 * 用户可以提供以下之一：
 * - url: 数据的网络地址
 * - filePath: 本地文件路径
 * - value: 参数值
 */
export class EventDataDto {
  @IsString()
  @IsNotEmpty()
  name: string;

  @IsString()
  url?: string;

  @IsString()
  filePath?: string;

  @IsNotEmpty()
  value?: any;
}

/**
 * 创建模型运行请求
 * 
 * 示例：
 * {
 *   "modelName": "UrbanM2M计算模型",
 *   "stateEvents": {
 *     "run": {
 *       "Years_zip": {
 *         "name": "sz.zip",
 *         "url": "http://example.com/sz.zip"
 *       },
 *       "st_year": {
 *         "name": "st_year.xml",
 *         "url": "http://example.com/st_year.xml"
 *       },
 *       "land_demands": {
 *         "name": "land_demands.xml",
 *         "url": "http://example.com/land_demands.xml",
 *         "value": "1000"
 *       }
 *     }
 *   }
 * }
 */
export class CreateModelRunRequest {
  @IsString()
  @IsNotEmpty()
  modelName: string;

  @IsObject()
  @IsNotEmpty()
  states: Record<string, Record<string, any>>;
}
