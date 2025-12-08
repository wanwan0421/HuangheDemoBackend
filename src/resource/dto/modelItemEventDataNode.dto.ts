// Describe single node information in event data
import { IsString, IsNotEmpty, IsOptional } from "class-validator";

// 描述Event使用了什么数据的细节结构（虽然是Event，但对应了DatasetItem）
// 例如：<DatasetItem name="Years_zip" type="external" description="研究区域历史影像文件"></DatasetItem>
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