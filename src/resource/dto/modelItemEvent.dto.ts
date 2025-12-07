import { IsString, IsNotEmpty, IsOptional, IsArray, ValidateNested, IsBoolean } from "class-validator";
import { Type } from "class-transformer";
import { ModelItemEventDataDto } from "./modelItemEventData.dto";

// 描述模型State中的一个Event
export class ModelItemEventDto {
    @IsString()
    @IsNotEmpty()
    eventName: string; // 事件名称

    @IsString()
    @IsOptional()
    eventDescription?: string; // 事件描述

    @IsBoolean()
    @IsOptional()
    optional?: boolean; // 是否为可选事件

    @IsString()
    @IsNotEmpty()
    eventType: string; // 事件类型（response为输入，noresponse为输出）

    @ValidateNested()
    @Type(() => ModelItemEventDataDto)
    eventData: ModelItemEventDataDto; // 事件数据
}
