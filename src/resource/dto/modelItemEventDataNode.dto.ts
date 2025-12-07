// Describe single node information in event data
import { IsString, IsNotEmpty, IsOptional } from "class-validator";

// 描述Event数据中的单个节点信息（例如：输入文件的参数）
export class ModelItemEventDataNodeDto {
    @IsString()
    @IsNotEmpty()
    text: string;

    @IsString()
    @IsOptional()
    description?: string;

    @IsString()
    @IsNotEmpty()
    dataType: string;
}