// describe the I/O state list of model resource
import { Type } from "class-transformer";
import { IsString,IsNotEmpty, IsOptional, IsArray, ValidateNested } from "class-validator";
import { ModelItemStateDto } from "./modelItemState.dto";

// 定义和验证mdl解析后的复杂输入和输出结构
export class ModelItemDataDto {
    @IsArray()
    @ValidateNested({ each: true }) // 确保数组中的每个元素都被验证
    @Type(() => ModelItemStateDto) // 指定数组元素的类型转换
    input: ModelItemStateDto[] = []; // 输入数据状态列表

    @IsArray()
    @ValidateNested({ each: true })
    @Type(() => ModelItemStateDto)
    output: ModelItemStateDto[] = []; // 输出数据状态列表
}