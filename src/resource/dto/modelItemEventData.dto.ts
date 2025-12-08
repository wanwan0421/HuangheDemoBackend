import { IsString, IsNotEmpty, IsOptional, IsArray, ValidateNested } from "class-validator";
import { Type } from "class-transformer";
import { ModelItemEventDataNodeDto } from "./modelItemEventDataNode.dto";

// 描述Event使用了什么数据
// 例如：<ResponseParameter datasetReference="Years_zip" description="研究区域历史影像文件" />
export class ModelItemEventDataDto {
    @IsString()
    @IsNotEmpty()
    eventDataType: string; // external (外部文件输入) 或 internal (内部变量输入)

    @IsString()
    @IsOptional()
    eventDataText?: string;

    @IsString()
    @IsOptional()
    exentDataDesc?: string;

    @IsArray()
    @ValidateNested({ each: true })
    @Type(() => ModelItemEventDataNodeDto)
    nodeList: ModelItemEventDataNodeDto[] = []; // 节点列表
}
