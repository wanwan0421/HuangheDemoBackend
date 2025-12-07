import { IsString, IsNotEmpty, IsOptional, ValidateNested } from "class-validator";
import { Type } from "class-transformer";
import { ModelItemEventDto } from "./modelItemEvent.dto";

// 描述模型mdl定义中的一个State
export class ModelItemStateDto {
    @IsString()
    @IsNotEmpty()
    stateName: string; // State名称

    @IsString()
    @IsOptional()
    stateDescription?: string; // State描述

    @ValidateNested({ each: true })
    @Type(() => ModelItemEventDto)
    events: ModelItemEventDto[] = []; // State中的事件列表
}